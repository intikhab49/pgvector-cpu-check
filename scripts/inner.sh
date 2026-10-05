#!/usr/bin/env bash
# Runs inside the image under test. Phase 1 (root) finds PostgreSQL and a non-root user, then
# re-runs itself as that user. Phase 2 starts the real server per test suite: once natively and
# once per emulated CPU model (the server process is launched under QEMU user mode, so every
# backend and parallel worker it forks stays on the emulated CPU), and prints one RESULT line each.
set -uo pipefail

find_pg_bin() {
  local d
  if command -v pg_config >/dev/null 2>&1; then
    d="$(pg_config --bindir 2>/dev/null)"
    [[ -x "$d/postgres" ]] && { echo "$d"; return; }
  fi
  if command -v postgres >/dev/null 2>&1; then dirname "$(command -v postgres)"; return; fi
  for d in /opt/bitnami/postgresql/bin /usr/lib/postgresql/*/bin /usr/local/pgsql/bin /usr/local/bin; do
    [[ -x "$d/postgres" ]] && { echo "$d"; return; }
  done
  d="$(find / -xdev -type f -name postgres -path '*/bin/*' 2>/dev/null | head -n1)"
  [[ -n "$d" ]] && dirname "$d"
}

as_user() { # as_user UID GID CMD...
  local u="$1" g="$2"; shift 2
  if command -v setpriv >/dev/null 2>&1; then setpriv --reuid "$u" --regid "$g" --clear-groups "$@"
  elif command -v gosu >/dev/null 2>&1; then gosu "$u:$g" "$@"
  elif command -v su-exec >/dev/null 2>&1; then su-exec "$u:$g" "$@"
  else chroot --userspec="$u:$g" --skip-chdir / "$@"; fi
}

if [[ "${1:-}" != phase2 ]]; then
  pg_bin="$(find_pg_bin)"
  [[ -n "$pg_bin" ]] || { printf 'RESULT\t-\t-\tERROR\tpostgres binary not found\n'; exit 1; }
  export PG_BIN="$pg_bin"
  echo "INFO	pg_bin	$pg_bin"
  echo "INFO	version	$("$pg_bin/postgres" --version 2>&1)"
  if [[ -x "$pg_bin/pg_config" ]]; then echo "INFO	pkglibdir	$("$pg_bin/pg_config" --pkglibdir)"; fi
  if [[ "$(id -u)" != 0 ]]; then exec bash "$0" phase2; fi
  if id postgres >/dev/null 2>&1; then
    uid="$(id -u postgres)" gid="$(id -g postgres)"
  else
    uid=4242 gid=4242
    echo "cpuaudit:x:$uid:$gid::/tmp:/bin/sh" >> /etc/passwd
    echo "cpuaudit:x:$gid:" >> /etc/group
  fi
  mkdir -p /tmp/cpuaudit && chown "$uid:$gid" /tmp/cpuaudit
  export HOME=/tmp/cpuaudit
  exec as_user "$uid" "$gid" bash "$0" phase2
fi

# ---------- phase 2: non-root ----------
work=/tmp/cpuaudit; mkdir -p "$work"; cd "$work" || exit 1
data="$work/data" sock="$work" log="$work/server.log"
export PGHOST="$sock" PGUSER=postgres PGDATABASE=postgres
psql_bin="$PG_BIN/psql"
"$PG_BIN/initdb" -D "$data" -U postgres --auth=trust --encoding=UTF8 --no-locale >"$work/initdb.log" 2>&1 \
  || { printf 'RESULT\tserver\tnative\tERROR\tinitdb failed: %s\n' "$(tail -n1 "$work/initdb.log")"; exit 1; }

items_sql="CREATE TABLE items AS
  SELECT g AS id,
         (SELECT array_agg(sin(g * 7 + i)::real ORDER BY i) FROM generate_series(1, 128) i)::vector(128) AS e
  FROM generate_series(1, 3000) g;
CREATE TABLE q AS SELECT e AS q FROM items WHERE id = 1;"

declare -A SUITE_SQL SUITE_PRELOAD SUITE_EXT
SUITE_EXT[server]=""
SUITE_SQL[server]="SELECT 'cpuaudit-ok';"

SUITE_EXT[pgvector]=vector
SUITE_SQL[pgvector]="CREATE EXTENSION IF NOT EXISTS vector;
SET max_parallel_maintenance_workers = 2; SET min_parallel_table_scan_size = 0; SET maintenance_work_mem = '256MB';
$items_sql
SELECT sum(e <-> q)::numeric(14,3) AS l2, sum(e <=> q)::numeric(14,3) AS cos, sum(e <#> q)::numeric(14,3) AS ip,
       sum(l1_distance(e, q))::numeric(14,3) AS l1 FROM items, q;
SELECT sum(e::halfvec(128) <-> q::halfvec(128))::numeric(14,2) AS l2_half,
       sum(e::halfvec(128) <=> q::halfvec(128))::numeric(14,2) AS cos_half FROM items, q;
SELECT sum(e::sparsevec <-> q::sparsevec)::numeric(14,2) AS l2_sparse FROM items, q;
SELECT sum(binary_quantize(e) <~> binary_quantize(q)) AS hamming FROM items, q;
CREATE INDEX ON items USING hnsw (e vector_l2_ops);
CREATE INDEX ON items USING hnsw ((e::halfvec(128)) halfvec_cosine_ops);
CREATE INDEX ON items USING ivfflat (e vector_ip_ops) WITH (lists = 20);
SET enable_seqscan = off;
SELECT array_agg(id) AS knn FROM (SELECT id FROM items, q ORDER BY e <-> q LIMIT 5) s;
SELECT array_agg(id) AS knn_half FROM (SELECT id FROM items, q ORDER BY e::halfvec(128) <=> q::halfvec(128) LIMIT 5) s;
SELECT 'cpuaudit-ok';"

SUITE_EXT[vectorscale]=vectorscale
SUITE_SQL[vectorscale]="CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;
$items_sql
CREATE INDEX ON items USING diskann (e vector_cosine_ops);
SET enable_seqscan = off;
SELECT array_agg(id) AS knn FROM (SELECT id FROM items, q ORDER BY e <=> q LIMIT 5) s;
SELECT 'cpuaudit-ok';"

SUITE_EXT[vchord]=vchord
SUITE_PRELOAD[vchord]=vchord
SUITE_SQL[vchord]="CREATE EXTENSION IF NOT EXISTS vchord CASCADE;
$items_sql
CREATE INDEX ON items USING vchordrq (e vector_l2_ops) WITH (options = \$\$
residual_quantization = true
[build.internal]
lists = [20]
\$\$);
SET enable_seqscan = off;
SELECT array_agg(id) AS knn FROM (SELECT id FROM items, q ORDER BY e <-> q LIMIT 5) s;
SELECT 'cpuaudit-ok';"

SUITE_EXT[pgvecto_rs]=vectors
SUITE_PRELOAD[pgvecto_rs]=vectors.so
SUITE_SQL[pgvecto_rs]="CREATE EXTENSION IF NOT EXISTS vectors;
SET search_path = public, vectors;
CREATE TABLE items2 AS
  SELECT g AS id,
         ('[' || (SELECT string_agg(sin(g * 7 + i)::real::text, ',' ORDER BY i) FROM generate_series(1, 128) i) || ']')::vectors.vector(128) AS e
  FROM generate_series(1, 3000) g;
SELECT sum(e <-> (SELECT e FROM items2 WHERE id = 1))::numeric(14,2) AS l2 FROM items2;
CREATE INDEX ON items2 USING vectors (e vectors.vector_l2_ops) WITH (options = '[indexing.hnsw]');
SET enable_seqscan = off;
SELECT array_agg(id) AS knn FROM (SELECT id FROM items2 ORDER BY e <-> (SELECT e FROM items2 WHERE id = 1) LIMIT 5) s;
SELECT 'cpuaudit-ok';"

SUITE_EXT[pg_search]=pg_search
SUITE_SQL[pg_search]="CREATE EXTENSION IF NOT EXISTS pg_search;
CREATE TABLE docs AS SELECT g AS id, 'word' || (g % 50) || ' text number ' || g AS body FROM generate_series(1, 3000) g;
CREATE INDEX docs_bm25 ON docs USING bm25 (id, body) WITH (key_field = 'id');
SELECT count(*) AS hits FROM docs WHERE body @@@ 'word7';
SELECT 'cpuaudit-ok';"

SUITES="server pgvector vectorscale vchord pgvecto_rs pg_search"

server_pid=""
start_server() { # start_server CPU PRELOAD
  local cpu="$1" preload="$2" runner=() i
  [[ "$cpu" == native ]] || runner=(/usr/local/bin/cpuaudit-qemu -cpu "$cpu")
  rm -f "$data/postmaster.pid"
  : > "$log"
  "${runner[@]}" "$PG_BIN/postgres" -D "$data" -k "$sock" -c listen_addresses='' \
    -c shared_preload_libraries="$preload" -c max_worker_processes=16 -c fsync=off \
    -c log_min_messages=log >>"$log" 2>&1 &
  server_pid=$!
  for i in $(seq 1 240); do
    "$psql_bin" -Atqc 'SELECT 1' >/dev/null 2>&1 && return 0
    kill -0 "$server_pid" 2>/dev/null || return 1
    sleep 0.5
  done
  return 1
}
stop_server() {
  [[ -n "$server_pid" ]] || return 0
  kill -INT "$server_pid" 2>/dev/null
  for _ in $(seq 1 120); do kill -0 "$server_pid" 2>/dev/null || break; sleep 0.5; done
  kill -9 "$server_pid" 2>/dev/null; wait "$server_pid" 2>/dev/null
  server_pid=""
}
crash_detail() {
  local sig stmt
  sig="$(grep -m1 -oE 'terminated by signal [0-9]+: [A-Za-z ]+|uncaught target signal [0-9]+ \([^)]*\)' "$log")"
  stmt="$(grep -m1 -oE 'Failed process was running: .{0,80}' "$log" | sed 's/Failed process was running: //')"
  if [[ -n "$sig" ]]; then echo "$sig${stmt:+ during: $stmt}"; return; fi
  grep -m1 -oE '(ERROR|FATAL|PANIC):.{0,120}' "$work/out.txt" "$log" 2>/dev/null | head -n1 | sed 's/^[^:]*://'
}

run_suite() { # run_suite SUITE CPU -> prints status
  local s="$1" cpu="$2" db
  db="t_${s}_$(echo "$cpu" | tr -c 'a-zA-Z0-9\n' '_')"
  if ! start_server "$cpu" "${SUITE_PRELOAD[$s]:-}"; then
    printf 'FAIL\tserver did not start: %s' "$(crash_detail || tail -n1 "$log")"; stop_server; return
  fi
  "$psql_bin" -qc "CREATE DATABASE $db" >/dev/null 2>&1
  if printf '%s\n' "${SUITE_SQL[$s]}" | timeout 900 "$psql_bin" -d "$db" -v ON_ERROR_STOP=1 -At >"$work/out.txt" 2>&1 \
     && grep -q 'cpuaudit-ok' "$work/out.txt"; then
    printf 'PASS\t%s' "$(grep -E '^[0-9{]' "$work/out.txt" | tr '\n' ' ' | cut -c1-160)"
  else
    sleep 1
    printf 'FAIL\t%s' "$(crash_detail)"
  fi
  "$psql_bin" -qc "DROP DATABASE IF EXISTS $db" >/dev/null 2>&1
  stop_server
}

# Which extensions does the image ship?
start_server native "" || { printf 'RESULT\tserver\tnative\tFAIL\t%s\n' "$(tail -n2 "$log" | tr '\n' ' ')"; exit 1; }
available="$("$psql_bin" -Atc "SELECT string_agg(name || '=' || default_version, ' ') FROM pg_available_extensions
  WHERE name IN ('vector','vectorscale','vchord','vectors','pg_search','timescaledb','postgis')")"
stop_server
echo "INFO	extensions	$available"

cpus_ok=""
for cpu in $CPUS; do
  if /usr/local/bin/cpuaudit-qemu -cpu help 2>/dev/null | grep -qiw -- "$cpu"; then cpus_ok="$cpus_ok $cpu"
  else printf 'RESULT\t-\t%s\tSKIP\tQEMU has no such CPU model\n' "$cpu"; fi
done

for s in $SUITES; do
  ext="${SUITE_EXT[$s]}"
  if [[ -n "$ext" && " $available " != *" $ext="* ]]; then continue; fi
  native="$(run_suite "$s" native)"
  printf 'RESULT\t%s\tnative\t%s\n' "$s" "$native"
  if [[ "$native" != PASS* ]]; then
    for cpu in $cpus_ok; do printf 'RESULT\t%s\t%s\tN/A\tsuite fails natively\n' "$s" "$cpu"; done
    continue
  fi
  for cpu in $cpus_ok; do printf 'RESULT\t%s\t%s\t%s\n' "$s" "$cpu" "$(run_suite "$s" "$cpu")"; done
done
