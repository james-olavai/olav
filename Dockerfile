# OLAV — CLI/TUI agent runtime.
#
# Deliberately NOT a long-running service. `olav` is an interactive terminal
# application, so the image's job is to give you a shell-ready environment and
# the entrypoint is the CLI itself. Use `docker compose run --rm olav …`, not
# `up`; a `up`-style daemon would idle doing nothing (see compose.yaml).
#
# Two stages so the runtime image carries no build toolchain: the wheel is built
# once, then installed into a clean layer.

# ── build ────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS build

# uv gives reproducible resolution and is what CI uses, so the image and CI
# install the same way.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /src
# Copy only what the build needs before the source, so a source-only edit does
# not invalidate the dependency layer.
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN uv build --wheel --out-dir /dist

# olav-netops is built here too but installed only by the netops target below,
# so the platform-only image does not carry it.
COPY olav-netops/pyproject.toml olav-netops/README.md* /src/olav-netops/
COPY olav-netops/src/ /src/olav-netops/src/
RUN cd /src/olav-netops && uv build --wheel --out-dir /dist || \
    echo "olav-netops wheel skipped (source not present)"

# ── runtime: platform only ───────────────────────────────────────────────────
FROM python:3.12-slim AS olav

# git: `olav agent install <git-url>` accepts a repository.
# curl: health probes against the LLM/embedding endpoints (olav doctor).
# ca-certificates: TLS to hosted providers.
RUN apt-get update && apt-get install --no-install-recommends -y \
        git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=build /dist/olav-*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/olav-*.whl && rm /tmp/*.whl

# Non-root. OLAV writes only under OLAV_HOME, so a plain user is enough and
# keeps a mounted host directory from acquiring root-owned files.
RUN useradd --create-home --uid 1000 olav
USER olav

# OLAV_HOME is the parent of `.olav/` — not the `.olav` directory itself. Passing
# the inner path produces `.olav/.olav/config/api.json` and a doctor that reports
# missing scaffolding; it is an easy mistake and worth naming here.
ENV OLAV_HOME=/data \
    OLAV_AUTH_MODE=none \
    PYTHONUNBUFFERED=1
WORKDIR /data

ENTRYPOINT ["olav"]
CMD ["--help"]

# ── runtime: platform + netops ───────────────────────────────────────────────
FROM olav AS olav-netops

USER root
# openssh-client + iputils: netops reaches devices over SSH and pings them.
# The netops agent also drives containerlab and Batfish, which run as their own
# containers — see compose.yaml for how they are reached.
RUN apt-get update && apt-get install --no-install-recommends -y \
        openssh-client iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /dist/olav_netops-*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/olav_netops-*.whl && rm /tmp/*.whl

USER olav
# Batfish runs as a sibling container; the netops code defaults to localhost,
# which inside a container is the container itself.
ENV BATFISH_HOST=batfish
