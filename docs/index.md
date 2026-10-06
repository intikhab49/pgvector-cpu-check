---
title: "pgvector \"Illegal instruction\" (SIGILL): which PostgreSQL Docker images crash on which CPUs"
description: "An audit of 13 PostgreSQL vector images (pgvector, pgvectorscale, VectorChord, pgvecto.rs, ParadeDB) on emulated Nehalem, Sandy Bridge, Ivy Bridge, Haswell, Raspberry Pi and Graviton2 CPUs: which crash with signal 4, the exact faulting instruction, and how to fix the build."
image: /assets/banner.png
---

<img class="banner" src="{{ '/assets/banner.png' | relative_url }}" alt="Your Postgres image works here. On older CPUs it crashes: pgvector-cpu-check replays the crash on 7 CPU models and names the faulting instruction">

## The error

```
LOG:  server process (PID 376) was terminated by signal 4: Illegal instruction
DETAIL:  Failed process was running: CREATE INDEX ON items USING hnsw (embedding vector_cosine_ops)
LOG:  terminating any other active server processes
```

Every connection drops, the server restarts, and it happens again on the next insert. The PostgreSQL extension in
your image (most often pgvector's `vector.so`) contains instructions your CPU does not have: it was compiled for the
machine that built it. That machine might have had AVX-512, AVX2, or on ARM, SVE or FP16 arithmetic. Your server,
VM, Raspberry Pi or Graviton2 instance does not.

This page is an audit of popular images, run with
[pgvector-cpu-check](https://github.com/intikhab49/pgvector-cpu-check), which you can also run on your own image in CI.

## Which images are affected (October 2026)

| Image | amd64 | arm64 |
|---|---|---|
| `pgvector/pgvector` (pg17, pg18) | ✅ every CPU | ✅ every CPU |
| CloudNativePG `postgresql:17-standard-trixie` | ✅ | ✅ |
| `supabase/postgres:17.11.0.004` | ✅ | ✅ |
| `paradedb/paradedb:0.26.0-pg18` (pgvector, pg_search) | ✅ | ✅ |
| Immich `postgres` (VectorChord 0.4.3 + pgvecto.rs 0.2.0; VectorChord 1.1.1) | ✅ | ✅ |
| `tensorchord/vchord-postgres:pg17-v1.1.1` | ✅ | ✅ |
| `ankane/pgvector` (frozen, pgvector 0.5.1) | ✅ | ✅ |
| `timescale/timescaledb-ha:pg17.11-ts2.30.2` | ❌ pgvectorscale needs Haswell (AVX2 + FMA); the rest ✅ | ✅ |
| `bitnami/postgresql:latest` | ❌ needs **AVX-512** | ❌ needs ARMv8.2 FP16: not Raspberry Pi 3/4 |
| `tecnativa/postgres-autoconf:18-alpine` | ❌ needs Haswell | ❌ needs **SVE**: not Raspberry Pi, Graviton2, Ampere Altra |

CPU models tested: Nehalem (SSE4.2, no AVX), Sandy Bridge (AVX), Ivy Bridge (AVX + F16C), Haswell (AVX2 + FMA),
Cortex-A53 and Cortex-A72 (Raspberry Pi 3 and 4), Neoverse N1 (AWS Graviton2, Ampere Altra), plus the native
runner CPU. Bitnami's amd64 image also crashed natively on real AMD EPYC 7763 servers, and on an EPYC 9V74 VM
whose hypervisor hid AVX-512 (it passed on the same model when AVX-512 was exposed).

## The exact instructions

| Image | CPU | Instruction | Function | Why |
|---|---|---|---|---|
| Bitnami amd64 | without AVX-512 | `vpermt2d` (AVX-512VL) | `array_to_vector` | `-march=native` on an AVX-512 build machine |
| Bitnami arm64 | Cortex-A53/A72 | `fabs h1, h2` (FP16) | `vector_to_halfvec` | `-march=native` on an ARMv8.2+ build machine |
| Tecnativa amd64 | below Haswell | `shlx`, `vcvtps2ph`, VEX `vmovsd` | `binary_quantize`, `Float4ToHalfUnchecked`, `HnswInit` | `make CFLAGS=-march=x86-64-v2`: pgvector's `-march=native` comes after it and wins |
| Tecnativa arm64 | A53, A72, N1 | `cntd x4` (SVE) | `array_to_vector` | built under QEMU emulation, where "native" is QEMU's max CPU |
| pgvectorscale 0.9.1 | Sandy/Ivy Bridge | `vinserti128` (AVX2) | `foldhash ... GlobalSeed::init_slow` | crate-wide `-Ctarget-feature=+avx2,+fma` |
| pgvectorscale 0.9.1 | Nehalem | VEX `vxorps` | pgrx glue in `_PG_init` | same |

Two of these are worth a closer look.

**A fix that does not take effect.** `make CFLAGS=-march=x86-64-v2` looks like it pins a portable baseline. The
compiler command it produces is `gcc -march=x86-64-v2 -march=native ...`: the later flag wins. It also replaces
PostgreSQL's own CFLAGS, so pgvector is compiled without `-O2`, `-fwrapv` and `-fno-strict-aliasing` (810 of its 982
functions set up a frame pointer, against 3 of 697 when built with `make OPTFLAGS=""`). And because "native"
depends on the build machine, the same Dockerfile built on an AVX-512 runner produced a library that crashes on
Haswell too.

**A guard that is compiled away.** pgvectorscale checks `is_x86_feature_detected!("avx2")` and `("fma")` in
`_PG_init` and panics with a clear message. Built with `-Ctarget-feature=+avx2,+fma`, Rust evaluates both checks to
`true` at compile time; the panic message is not in the released library. A CPU without AVX2 gets a backend crash
in Rust's hash-map seeding instead of an error.

## How to fix a build

- pgvector from source: `make OPTFLAGS=""` (never `CFLAGS=...`).
- Building arm64 images under QEMU: never `-march=native` / `-mcpu=native`; they mean QEMU's emulated max CPU.
- Rust extensions: no crate-wide `target-feature` / `target-cpu`; `#[target_feature]` kernels picked at runtime.
- Check the result in CI on old CPU models: [pgvector-cpu-check](https://github.com/intikhab49/pgvector-cpu-check).

## Method

The real PostgreSQL server runs natively and under QEMU 10 user mode with each CPU model; backends and parallel
workers it forks stay on the emulated CPU. Suites cover pgvector (HNSW, IVFFlat, halfvec, sparsevec, bit),
pgvectorscale DiskANN, VectorChord, pgvecto.rs, ParadeDB BM25 and TimescaleDB compression. On a crash the guest
core is analysed: the dynamic loader's `link_map` is rebuilt from raw core memory and checked against each library's
`.dynamic` address, and the faulting instruction is disassembled from the image's own files. A static fingerprint
of every extension library (instruction classes per function, runtime-dispatch evidence) agrees with the dynamic
results on all 28 image/architecture pairs. Scripts, workflows and raw results:
[github.com/intikhab49/pgvector-cpu-check](https://github.com/intikhab49/pgvector-cpu-check).
