# timescaledb-ha with pgvectorscale rebuilt to run on any x86-64 CPU.
#
# pgvectorscale compiles the whole crate with -Ctarget-feature=+avx2,+fma, so the server dies with
# SIGILL on a CPU without AVX2 before its own CPU check can run. load-on-any-x86-cpu.patch builds
# the crate for baseline x86-64, compiles only the distance kernels with AVX2+FMA, and picks those
# kernels or the SSE2 ones once, when the library loads. On arm64 the image was already fine.
#
#   docker build -t timescaledb-ha:portable fixes/pgvectorscale
ARG BASE=timescale/timescaledb-ha:pg17.11-ts2.30.2

FROM ${BASE} AS build
USER root
ARG PGVECTORSCALE_VERSION=0.9.1
ARG PGRX_VERSION=0.16.1
RUN set -eux; \
    pg="$(sed -n 's/^PG_MAJOR="\(.*\)"/\1/p' /.image_config)"; \
    have="$(sed -n "s/^default_version = '\(.*\)'/\1/p" "/usr/share/postgresql/$pg/extension/vectorscale.control")"; \
    [ "$have" = "$PGVECTORSCALE_VERSION" ] || { echo "image ships pgvectorscale $have, patch is for $PGVECTORSCALE_VERSION"; exit 1; }; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential ca-certificates curl git pkg-config libssl-dev \
        libclang-dev clang "postgresql-server-dev-$pg"; \
    rm -rf /var/lib/apt/lists/*; \
    echo "$pg" > /tmp/pg_major
COPY load-on-any-x86-cpu.patch /tmp/
# cargo pgrx init runs initdb, which refuses to run as root
USER postgres
ENV CARGO_HOME=/home/postgres/.cargo RUSTUP_HOME=/home/postgres/.rustup PATH=/home/postgres/.cargo/bin:$PATH
RUN set -eux; \
    pg="$(cat /tmp/pg_major)"; \
    curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal; \
    cargo install cargo-pgrx --version "$PGRX_VERSION" --locked; \
    cargo pgrx init "--pg$pg" "/usr/lib/postgresql/$pg/bin/pg_config"; \
    git clone -q --depth 1 --branch "$PGVECTORSCALE_VERSION" https://github.com/timescale/pgvectorscale /tmp/src; \
    cd /tmp/src; \
    git apply /tmp/load-on-any-x86-cpu.patch; \
    cd pgvectorscale; \
    cargo pgrx package --pg-config "/usr/lib/postgresql/$pg/bin/pg_config"; \
    so="$(find /tmp/src/target/release -name "vectorscale-$PGVECTORSCALE_VERSION.so" | head -n1)"; \
    test -n "$so"; \
    mkdir -p /tmp/out; \
    cp "$so" /tmp/out/

FROM ${BASE}
ARG PGVECTORSCALE_VERSION=0.9.1
USER root
COPY --from=build /tmp/out/ /tmp/vectorscale/
RUN set -eux; \
    pg="$(sed -n 's/^PG_MAJOR="\(.*\)"/\1/p' /.image_config)"; \
    install -m 0755 "/tmp/vectorscale/vectorscale-$PGVECTORSCALE_VERSION.so" "/usr/lib/postgresql/$pg/lib/"; \
    rm -rf /tmp/vectorscale
USER postgres
