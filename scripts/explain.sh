#!/usr/bin/env bash
# Names the instruction that killed PostgreSQL on an emulated CPU, from the guest core QEMU wrote.
# Usage: scripts/explain.sh ROOTFS PG_BIN CORE
# Prints: one summary line "<instruction>\t<function + library>" then the raw gdb output.
set -uo pipefail
rootfs="$1" pg_bin="$2" core="$3"
raw="$(gdb-multiarch -nx -batch -q \
  -ex "set debuginfod enabled off" -ex "set auto-load safe-path /" -ex "set pagination off" \
  -ex "set sysroot $rootfs" -ex "set solib-search-path $rootfs$(dirname "$pg_bin")/lib" \
  -ex "file $rootfs$pg_bin/postgres" -ex "core-file $core" \
  -ex 'x/i $pc' -ex 'info symbol $pc' -ex 'bt 10' -ex 'info sharedlibrary' 2>&1)"
insn="$(grep -m1 -E '^=> 0x' <<<"$raw" | sed -E 's/^=> 0x[0-9a-f]+( <[^>]*>)?:\s*//')"
sym="$(grep -m1 -E ' in section ' <<<"$raw" | sed -E "s# in section [^ ]+( of )?# in #; s#$rootfs##")"
[[ -n "$sym" ]] || sym="$(grep -m1 -E '^#0 ' <<<"$raw" | sed "s#$rootfs##")"
printf '%s\t%s\n' "${insn:-?}" "${sym:-?}"
printf '%s\n' "$raw"
