#!/usr/bin/env bash
# Probes one PostgreSQL image for one architecture on an amd64 host.
#   dynamic: scripts/inner.sh runs the real server natively and on emulated CPU models
#            amd64: Nehalem (SSE4.2, no AVX), SandyBridge (AVX), IvyBridge (AVX + F16C), Haswell (AVX2 + FMA, no AVX-512)
#            arm64: cortex-a53, cortex-a72 (ARMv8.0, Raspberry Pi 3/4), neoverse-n1 (ARMv8.2 + FP16, Graviton2/Ampere)
#            arm64 "native" is QEMU's default "max" CPU via binfmt, since the host is amd64.
#   static:  counts AVX/AVX2/AVX-512/FMA/F16C instructions in the vector extensions' .so files (amd64 only).
# Usage: scripts/probe.sh IMAGE ARCH OUTDIR      Writes OUTDIR/results.tsv and OUTDIR/info.tsv
set -euo pipefail
image="$1" arch="$2" out="$3"
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$out"
case "$arch" in
  amd64) qemu=qemu-x86_64-static  cpus="Nehalem SandyBridge IvyBridge Haswell" ;;
  arm64) qemu=qemu-aarch64-static cpus="cortex-a53 cortex-a72 neoverse-n1" ;;
  *) echo "unsupported arch $arch" >&2; exit 2 ;;
esac

if ! docker pull -q --platform "linux/$arch" "$image" >/dev/null 2>"$out/pull.err"; then
  printf 'RESULT\t-\t-\tNO-IMAGE\t%s\n' "$(tail -n1 "$out/pull.err")" | cut -f2- > "$out/results.tsv"
  exit 0
fi
image_arch="$(docker image inspect -f '{{.Architecture}}' "$image")"
if [[ "$image_arch" != "$arch" ]]; then
  printf -- '-\t-\tNO-IMAGE\tno linux/%s variant (got %s)\n' "$arch" "$image_arch" > "$out/results.tsv"
  exit 0
fi
{
  printf 'image\t%s\n' "$image"
  printf 'digest\t%s\n' "$(docker image inspect -f '{{join .RepoDigests " "}}' "$image")"
  printf 'host_cpu\t%s\n' "$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ //')"
  printf 'host_flags\t%s\n' "$(grep -m1 '^flags' /proc/cpuinfo | grep -oE '\b(avx|avx2|fma|f16c|avx512f|avx512fp16|avx512_fp16|amx_tile)\b' | sort -u | tr '\n' ' ')"
} > "$out/info.tsv"

ctx="$(mktemp -d)"
cp "$here/inner.sh" "$ctx/inner.sh"
cat > "$ctx/Dockerfile" <<EOF
FROM --platform=linux/amd64 debian:bookworm-slim AS qemu
RUN apt-get -o Acquire::Retries=5 update \
 && apt-get -o Acquire::Retries=5 install -y --no-install-recommends qemu-user-static \
 && rm -rf /var/lib/apt/lists/*
FROM $image
COPY --from=qemu /usr/bin/$qemu /usr/local/bin/cpuaudit-qemu
COPY inner.sh /usr/local/bin/cpuaudit-inner.sh
EOF
tag="cpuaudit-probe:$$"
docker build -q --platform "linux/$arch" -t "$tag" "$ctx" >/dev/null

timeout 7200 docker run --rm --platform "linux/$arch" --user 0 --entrypoint "" -e CPUS="$cpus" \
  "$tag" bash /usr/local/bin/cpuaudit-inner.sh > "$out/inner.log" 2>&1 || true
grep '^RESULT' "$out/inner.log" | cut -f2- > "$out/results.tsv" || true
grep '^INFO' "$out/inner.log" | cut -f2- >> "$out/info.tsv" || true
[[ -s "$out/results.tsv" ]] || printf -- '-\t-\tERROR\t%s\n' "$(tail -n1 "$out/inner.log")" > "$out/results.tsv"

if [[ "$arch" == amd64 ]]; then
  pkglib="$(awk -F'\t' '$1=="pkglibdir"{print $2}' "$out/info.tsv")"
  if [[ -n "$pkglib" ]]; then
    cid="$(docker create "$tag")"
    mkdir -p "$ctx/lib"
    docker cp -L "$cid:$pkglib/." "$ctx/lib/" >/dev/null 2>&1 || true
    docker rm "$cid" >/dev/null
    : > "$out/static.tsv"
    while IFS= read -r f; do
      d="$(objdump -d --no-show-raw-insn "$f" 2>/dev/null)" || continue
      printf '%s\tymm=%s\tzmm=%s\tfma=%s\tf16c=%s\n' "$(basename "$f")" \
        "$(grep -c '%ymm' <<<"$d")" "$(grep -c '%zmm' <<<"$d")" \
        "$(grep -cE '\svfn?m(add|sub)' <<<"$d")" "$(grep -cE '\svcvt(ph2ps|ps2ph)' <<<"$d")" >> "$out/static.tsv"
    done < <(find "$ctx/lib" -type f \( -name 'vector.so' -o -name 'vectorscale*.so' -o -name 'vchord.so' \
                -o -name 'vectors.so' -o -name 'pg_search*.so' \) 2>/dev/null)
  fi
fi
docker rmi -f "$tag" >/dev/null 2>&1 || true
rm -rf "$ctx"
cat "$out/results.tsv"
