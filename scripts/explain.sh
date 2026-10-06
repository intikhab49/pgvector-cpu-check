#!/usr/bin/env bash
# Names the instruction that killed PostgreSQL, from a core file (QEMU's guest core for emulated CPUs,
# the kernel's core for native crashes) and the image's own files.
# Usage: scripts/explain.sh ARCH ROOTFS PG_EXE CORE   (PG_EXE: the postgres ELF inside the image)
# Prints: one summary line "<instruction>\t<function+off in library>" then the raw gdb output.
set -uo pipefail
arch="$1" rootfs="$2" pg_exe="$3" core="$4"
here="$(cd "$(dirname "$0")" && pwd)"
raw="$(gdb-multiarch -nx -batch -q \
  -ex "set debuginfod enabled off" -ex "set auto-load safe-path /" -ex "set pagination off" \
  -ex "set sysroot $rootfs" -ex "file $rootfs$pg_exe" -ex "core-file $core" \
  -ex 'x/i $pc' -ex 'info symbol $pc' -ex 'bt 10' -ex 'info registers' -ex 'info sharedlibrary' 2>&1 \
  | grep -v "during file-backed mapping note processing")"
pc="$(grep -m1 -oE '^#0 +0x[0-9a-f]+' <<<"$raw" | grep -oE '0x[0-9a-f]+' || grep -m1 -oE '^=> 0x[0-9a-f]+' <<<"$raw" | grep -oE '0x[0-9a-f]+')"
summary=""
map="$(mktemp)"
# QEMU guest cores lack the file-mapping note gdb needs; recover the link_map from the core instead.
[[ -n "$pc" ]] && summary="$(python3 "$here/corelibs.py" "$arch" "$core" "$rootfs" "$pc" "$pg_exe" "${PKGLIB:-}" 2>"$map" | tail -n1)"
if [[ -z "$summary" || "$summary" == '?'* ]]; then
  insn="$(grep -m1 -E '^=> 0x' <<<"$raw" | sed -E 's/^=> 0x[0-9a-f]+( <[^>]*>)?:\s*//')"
  sym="$(grep -m1 -E ' in section ' <<<"$raw" | sed -E "s# in section [^ ]+( of )?# in #; s#$rootfs##")"
  summary="${insn:-?}	${sym:-${summary:-?}}"
fi
printf '%s\n' "$summary"
printf '%s\n' "$raw"
cat "$map" 2>/dev/null; rm -f "$map"
ls -l "$core" | awk '{print "CORE\t" $5 " bytes"}'
readelf -lW "$core" 2>/dev/null | awk '$1=="LOAD"' | sort -k3 | awk '{print "SEG\t" $3 "\tfilesz=" $5 "\tmemsz=" $6 "\t" $7}' | tail -n 60
