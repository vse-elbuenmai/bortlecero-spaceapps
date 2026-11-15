FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv
FROM python:3.14-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b AS python-base

FROM python-base AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
ENV UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --locked --no-dev --no-install-project --no-cache

FROM python-base AS runtime
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY src/spherex_ingest ./spherex_ingest
RUN groupadd --gid 10001 spherex \
    && useradd --uid 10001 --gid 10001 --home-dir /scratch --no-create-home spherex \
    && mkdir /scratch \
    && chown 10001:10001 /scratch

ENV PATH="/opt/venv/bin:$PATH" \
    HOME=/scratch \
    TMPDIR=/scratch \
    SPHEREX_CACHE_DIR=/scratch/fits \
    SPHEREX_OUTPUT_DIR=/scratch/output \
    SPHEREX_LEGACY_SYNC_ENABLED=false \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

USER 10001:10001
EXPOSE 8080
CMD ["/bin/sh", "-c", "exec uvicorn spherex_ingest.api:app --host 0.0.0.0 --port ${PORT:-8080} --timeout-graceful-shutdown 8"]
