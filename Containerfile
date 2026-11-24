# Two stages:
#   base  what production needs: requirements.txt on Prefect's image.
#   dev   base plus requirements-dev.txt. All local work happens in here, there
#         is no venv. It's the last stage, so it's what a plain build produces:
#
#   podman build -t broke-lakehouse .
#   podman build --target base -t broke-lakehouse:base .
#
# Base is the same image Prefect's managed work pool runs, pinned rather than
# tracking :3-latest so it can't move underneath us. Bump this together with
# the prefect pin in requirements.txt.
#
# Registry is spelled out: podman has no unqualified-search default, and an
# explicit registry is one less thing that resolves differently on another box.
FROM docker.io/prefecthq/prefect:3.8.3-python3.12 AS base

WORKDIR /workspace

# requirements.txt is the entry point for runtime dependencies: `-e .[pipeline]`,
# whose pins live in pyproject.toml — prefect included, reinstalled here over
# the copy baked into the base image. The managed work pool installs from this
# same file at run time.
#
# Editable, so the package points at /workspace/broke_lakehouse and its source
# is needed at build time. At run time the repo is mounted over /workspace, and
# the same path is the live code.
COPY requirements.txt pyproject.toml ./
COPY broke_lakehouse/ broke_lakehouse/
RUN pip install --no-cache-dir -r requirements.txt

# Bake the DuckDB extensions in so containers don't fetch them on every start.
# ducklake: the lakehouse format;  httpfs: S3-compatible object storage;
# postgres: the Neon-backed catalog;  tpch: the dbgen data generator.
RUN python -c "import duckdb; duckdb.sql('INSTALL ducklake; INSTALL httpfs; INSTALL postgres; INSTALL tpch;')"

CMD ["bash"]

FROM base AS dev

COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

# OpenTofu, for infra/ only, so dev-only: the managed pool never runs it.
# 1.11+ is required (ephemeral resources, write-only arguments). @docs/infrastructure.md
ARG TOFU_VERSION=1.13.8
ARG TARGETARCH
ADD https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_linux_${TARGETARCH}.tar.gz /tmp/tofu.tar.gz
RUN tar -xzf /tmp/tofu.tar.gz -C /usr/local/bin tofu && rm /tmp/tofu.tar.gz && tofu version
