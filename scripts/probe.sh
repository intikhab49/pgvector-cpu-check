#!/usr/bin/env bash
# Probes one PostgreSQL image for one architecture on an amd64 host.
#   dynamic: scripts/inner.sh runs the real server natively and on emulated CPU models
#            amd64: Nehalem (SSE4.2, no AVX), SandyBridge (AVX), IvyBridge (AVX + F16C), Haswell (AVX2 + FMA, no AVX-512)
#            arm64: cortex-a53, cortex-a72 (ARMv8.0, Raspberry Pi 3/4), neoverse-n1 (ARMv8.2 + FP16, Graviton2/Ampere)
#            arm64 "native" is QEMU's default "max" CPU via binfmt, since the host is amd64.
#   static:  scripts/fingerprint.py: instruction-set classes per function + CPU-dispatch evidence.
#   crash:   QEMU writes the guest core on SIGILL; scripts/explain.sh opens it in gdb-multiarch.
# Usage: scripts/probe.sh IMAGE ARCH OUTDIR
# Writes OUTDIR/{results,info,fingerprint,explain}.tsv and OUTDIR/explain/*.txt
set -euo pipefail
image="$1" arch="$2" out="$3"
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
case "$arch" in
  amd64) qemu=qemu-x86_64-static  cpus="Nehalem SandyBridge IvyBridge Haswell" ;;
  arm64) qemu=qemu-aarch64-static cpus="cortex-a53 cortex-a72 neoverse-n1" ;;
  *) echo "unsupported arch $arch" >&2; exit 2 ;;
esac

pulled=""
# LOCAL_IMAGE=1: the image was just built on this runner (docker buildx --load), nothing to pull.
[[ -n "${LOCAL_IMAGE:-}" ]] && docker image inspect "$image" >/dev/null 2>&1 && pulled=1
for attempt in 1 2 3 4; do
  [[ -n "$pulled" ]] && break   # registries rate-limit bursts of parallel pulls (ghcr.io "toomanyrequests")
  docker pull -q --platform "linux/$arch" "$image" >/dev/null 2>"$out/pull.err" && { pulled=1; break; }
  sleep $((attempt * 20))
done
if [[ -z "$pulled" ]]; then
  printf -- '-\t-\tNO-IMAGE\t%s\n' "$(tail -n1 "$out/pull.err")" > "$out/results.tsv"
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
FROM --platform=linux/amd64 debian:${QEMU_DEBIAN:-trixie}-slim AS qemu
RUN apt-get -o Acquire::Retries=5 update \
 && apt-get -o Acquire::Retries=5 install -y --no-install-recommends "$( [ "${QEMU_DEBIAN:-trixie}" = bookworm ] && echo qemu-user-static || echo qemu-user )" file \
 && rm -rf /var/lib/apt/lists/* \
 && q="\$(ls /usr/bin/$qemu /usr/bin/${qemu%-static} 2>/dev/null | head -n1)" \
 && cp -L "\$q" /cpuaudit-qemu && file /cpuaudit-qemu | grep -qE 'statically linked|static-pie linked' \
 && /cpuaudit-qemu --version | head -n1 > /cpuaudit-qemu.version
FROM $image
COPY --from=qemu /cpuaudit-qemu /usr/local/bin/cpuaudit-qemu
COPY --from=qemu /cpuaudit-qemu.version /usr/local/share/cpuaudit-qemu.version
COPY inner.sh /usr/local/bin/cpuaudit-inner.sh
EOF
tag="cpuaudit-probe:$$"
docker build -q --platform "linux/$arch" -t "$tag" "$ctx" >/dev/null

mkdir -p "$out/cores" && chmod 777 "$out/cores"
timeout 7200 docker run --rm --platform "linux/$arch" --user 0 --entrypoint "" -e CPUS="$cpus" \
  --ulimit core=-1 --shm-size=1g -v "$out/cores:/cores" \
  "$tag" bash /usr/local/bin/cpuaudit-inner.sh > "$out/inner.log" 2>&1 || true
grep '^RESULT' "$out/inner.log" | cut -f2- > "$out/results.tsv" || true
grep '^INFO' "$out/inner.log" | cut -f2- >> "$out/info.tsv" || true
[[ -s "$out/results.tsv" ]] || printf -- '-\t-\tERROR\t%s\n' "$(tail -n1 "$out/inner.log")" > "$out/results.tsv"

# Static fingerprint of the extension libraries, and gdb on every core QEMU dumped.
pkglib="$(awk -F'\t' '$1=="pkglibdir"{print $2}' "$out/info.tsv")"
pg_bin="$(awk -F'\t' '$1=="pg_bin"{print $2}' "$out/info.tsv")"
pg_exe="$(awk -F'\t' '$1=="pg_exe"{print $2}' "$out/info.tsv")"; pg_exe="${pg_exe:-$pg_bin/postgres}"
cid="$(docker create --platform "linux/$arch" "$tag")"
if [[ -n "$pkglib" ]]; then
  mkdir -p "$ctx/lib"
  docker cp -L "$cid:$pkglib/." "$ctx/lib/" >/dev/null 2>&1 || true
  python3 "$here/fingerprint.py" "$arch" "$ctx/lib" > "$out/fingerprint.tsv" 2>"$out/fingerprint.err" || true
fi
if compgen -G "$out/cores/*.core" >/dev/null && [[ -n "$pg_bin" ]]; then
  mkdir -p "$ctx/rootfs" "$out/explain"
  sudo chmod -R a+rX "$out/cores" 2>/dev/null || true   # cores are 0600, owned by the container's postgres user
  docker export "$cid" | tar -x -C "$ctx/rootfs" --exclude='dev/*' --exclude='proc/*' --exclude='sys/*' 2>/dev/null || true
  : > "$out/explain.tsv"
  for core in "$out"/cores/*.core; do
    key="$(basename "$core" .core)"
    PKGLIB="$pkglib" bash "$here/explain.sh" "$arch" "$ctx/rootfs" "$pg_exe" "$core" > "$out/explain/$key.txt" 2>&1 || true
    printf '%s\t%s\t%s\n' "${key%@*}" "${key#*@}" "$(head -n1 "$out/explain/$key.txt")" >> "$out/explain.tsv"
  done
fi
sudo rm -rf "$out/cores" 2>/dev/null || rm -rf "$out/cores"
docker rm "$cid" >/dev/null
docker rmi -f "$tag" >/dev/null 2>&1 || true
rm -rf "$ctx" 2>/dev/null || sudo rm -rf "$ctx"
cat "$out/results.tsv"
