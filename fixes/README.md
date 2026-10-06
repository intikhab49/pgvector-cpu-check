# Fixes for the three build bugs

Each fix is built and run on all 7 CPU models by [`.github/workflows/fixes.yml`](../.github/workflows/fixes.yml),
next to the unfixed image on the same runner. That job fails if a fixed image still crashes anywhere.

| Image | Bug | Fix here | Upstream |
|---|---|---|---|
| `tecnativa/postgres-autoconf` | `make CFLAGS=-march=x86-64-v2` is overridden by pgvector's later `-march=native`, and drops `-O2` | [`tecnativa/Dockerfile.patch`](tecnativa/Dockerfile.patch): `make OPTFLAGS=""` | [PR #42](https://github.com/Tecnativa/docker-postgres-autoconf/pull/42), open |
| `timescale/timescaledb-ha` | pgvectorscale builds the whole crate with `+avx2,+fma`, so its own CPU check is compiled out and the server dies with SIGILL | [`pgvectorscale/`](pgvectorscale/): patch + Dockerfile | [issue #288](https://github.com/timescale/pgvectorscale/issues/288), open |
| `bitnami/postgresql` | pgvector built with `-march=native`: needs AVX-512 on amd64, FP16 on arm64 | [`bitnami/Dockerfile`](bitnami/Dockerfile): pgvector rebuilt with `OPTFLAGS=""` | not reported; or use [lifeboat](https://github.com/intikhab49/lifeboat) |

## Use one

```sh
# Bitnami: same image, portable vector.so
docker build -t postgresql:portable fixes/bitnami

# timescaledb-ha: same image, portable pgvectorscale (amd64; arm64 was already fine)
docker build -t timescaledb-ha:portable fixes/pgvectorscale

# Tecnativa: their Dockerfile with the patch
git clone https://github.com/Tecnativa/docker-postgres-autoconf && cd docker-postgres-autoconf
git apply /path/to/pgvector-cpu-check/fixes/tecnativa/Dockerfile.patch
docker build --build-arg BASE_TAG=18-alpine -t postgres-autoconf:portable .
```

## The pgvectorscale patch

[`load-on-any-x86-cpu.patch`](pgvectorscale/load-on-any-x86-cpu.patch), against pgvectorscale 0.9.1:

1. Removes the crate-wide `-Ctarget-feature=+avx2,+fma`, so everything outside the distance kernels
   (pgrx glue, `foldhash`, `_PG_init`) is plain x86-64.
2. Compiles the distance kernels (L2, inner product, cosine, SBQ's XOR popcount) with
   `#[target_feature(enable = "avx2,fma")]`. The simdeez bodies are `#[inline(always)]`, so they get
   the same AVX2 and FMA code as before.
3. `init()` checks the CPU once; the kernels use AVX2+FMA when it has them and simdeez's SSE2 versions
   otherwise, instead of refusing to load.

So the extension runs on every x86-64 CPU, and the workflow times it against the original on the same
runner to show what the AVX2 path costs, if anything.
