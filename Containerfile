# Local development environment. There is no venv — all work happens in here.
#
# Base is the same image Prefect's managed work pool runs, pinned rather than
# tracking :3-latest so it can't move underneath us. Bump this together with
# the prefect pin in requirements.txt.
#
# Registry is spelled out: podman has no unqualified-search default, and an
# explicit registry is one less thing that resolves differently on another box.
FROM docker.io/prefecthq/prefect:3.8.3-python3.12

WORKDIR /workspace

# requirements.txt is the single source of truth for dependencies, including
# prefect itself — reinstalled here over the copy baked into the base image.
# The managed work pool installs from this same file at run time.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the DuckDB extensions in so containers don't fetch them on every start.
# ducklake: the lakehouse format;  httpfs: S3 access to Tigris;
# postgres: the Neon-backed catalog.
RUN python -c "import duckdb; duckdb.sql('INSTALL ducklake; INSTALL httpfs; INSTALL postgres;')"

CMD ["bash"]
