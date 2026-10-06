#!/usr/bin/env bash
# Times pgvector work natively inside an image: a single-worker HNSW build over 20,000 x 768 random
# vectors, then 500 nearest-neighbour queries. Same data (setseed) for every image; run the images being
# compared on the same runner, alternating, and compare medians. Timing comes from psql's \timing
# (busybox date in Alpine images has no nanoseconds).
# Usage: scripts/bench.sh IMAGE      Prints: build_ms<TAB>query_ms
set -euo pipefail
image="$1"
docker run --rm --entrypoint "" --user postgres --shm-size=1g "$image" sh -c '
  set -e
  export PGHOST=/tmp PGUSER=postgres PGDATABASE=postgres
  initdb -D /tmp/d -U postgres --auth=trust >/dev/null
  pg_ctl -D /tmp/d -l /tmp/log -o "-k /tmp -c listen_addresses= -c shared_buffers=512MB -c maintenance_work_mem=1GB -c max_parallel_maintenance_workers=0 -c jit=off" -w start >/dev/null
  psql -qAt -c "CREATE EXTENSION vector" -c "SELECT setseed(0.42)" \
    -c "CREATE TABLE items AS SELECT g AS id, (SELECT array_agg(random()::real) FROM generate_series(1, 768) i WHERE g > 0)::vector(768) AS e FROM generate_series(1, 20000) g" \
    -c "CREATE TABLE qs AS SELECT e AS q FROM items WHERE id % 40 = 0" >/dev/null
  build=$(psql -qAt -c "\\timing on" -c "CREATE INDEX ON items USING hnsw (e vector_cosine_ops)" | sed -n "s/^Time: \([0-9.]*\) ms.*/\1/p")
  query=$(psql -qAt -c "SET enable_seqscan = off" -c "\\timing on" -c "SELECT count(*) FROM qs, LATERAL (SELECT id FROM items ORDER BY e <=> qs.q LIMIT 10) n" | sed -n "s/^Time: \([0-9.]*\) ms.*/\1/p")
  printf "%s\t%s\n" "${build%.*}" "${query%.*}"
'
