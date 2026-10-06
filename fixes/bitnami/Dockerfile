# Bitnami's PostgreSQL image with pgvector rebuilt to run on any CPU of its architecture.
#
# Bitnami's vector.so is compiled with pgvector's default -march=native, so it needs the build
# machine's CPU: AVX-512 on amd64 (vpermt2d in array_to_vector), FP16 on arm64 (fabs h in
# vector_to_halfvec). This rebuilds the same pgvector version against Bitnami's own pg_config with
# OPTFLAGS="", which drops -march=native and keeps -O2.
#
#   docker build -t postgresql:portable fixes/bitnami
#   docker build --build-arg BASE=bitnami/postgresql:17 -t postgresql:17-portable fixes/bitnami
ARG BASE=bitnami/postgresql:latest

FROM ${BASE} AS build
USER root
RUN set -eux; \
    install_packages build-essential ca-certificates curl; \
    pg=/opt/bitnami/postgresql; \
    v="$(sed -n "s/^default_version = '\(.*\)'/\1/p" "$pg/share/extension/vector.control")"; \
    test -n "$v"; \
    test -f "$("$pg/bin/pg_config" --pgxs)"; \
    curl -fsSL "https://github.com/pgvector/pgvector/archive/refs/tags/v$v.tar.gz" | tar -xz -C /tmp; \
    cd "/tmp/pgvector-$v"; \
    make OPTFLAGS="" with_llvm=no CC=gcc PG_CONFIG="$pg/bin/pg_config"; \
    make install with_llvm=no DESTDIR=/out PG_CONFIG="$pg/bin/pg_config"; \
    ls -l "/out$pg/lib/vector.so"

FROM ${BASE}
COPY --from=build /out/ /
# the JIT bitcode next to the old vector.so was compiled with -march=native too
USER root
RUN rm -rf /opt/bitnami/postgresql/lib/bitcode/vector /opt/bitnami/postgresql/lib/bitcode/vector.index.bc
USER 1001
