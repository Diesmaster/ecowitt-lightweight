# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS base

# Install uv by copying its static binary from Astral's own distroless
# image, rather than pip-installing it or curling an install script -
# this is the pattern Astral's own docs recommend, and avoids pinning
# to a compound base-image tag (e.g. "python3.12-bookworm-slim") whose
# exact availability has shifted over time.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Install dependencies first, separately from app code, so this layer
# is only invalidated when pyproject.toml/uv.lock actually change, not
# on every source edit.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Now add the actual application code and finish the sync. This
# deliberately does NOT pass --no-dev: the dev group (httpx, websockets)
# is what scripts/add_weather_station.py, scripts/add_api_key.py, and
# the test_*.py scripts need, and those are meant to be run with
# `docker exec` against the running container for provisioning - not
# just locally on your laptop.
COPY app ./app
COPY admin_scripts ./scripts
COPY main.py ./
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

# --- Persistent state ---
# Three things need to survive a container restart/recreate and are
# NOT baked into the image: the data/ directory (parquet files),
# keys.json, and stations.json. All three are plain relative paths off
# the working directory (see app/storage/registry.py, DATA_DIR, and
# app/security/dependencies.py / station_auth.py, KEYS_FILE /
# STATIONS_FILE) - bind-mount or volume-mount each of them explicitly,
# e.g.:
#
#   docker run \
#     -v weather-data:/app/data \
#     -v $(pwd)/keys.json:/app/keys.json \
#     -v $(pwd)/stations.json:/app/stations.json \
#     ...
#
# A VOLUME declaration is only added for data/ here since keys.json/
# stations.json don't exist until the first `add_weather_station.py` /
# `add_api_key.py` run - bind-mounting a not-yet-existing file works
# fine in Docker (it creates an empty file to mount over), an anonymous
# VOLUME for a not-yet-existing file does not behave the same way.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Configurable at `docker run` time via -e; see app/config.py for the
# full list and defaults (STORAGE_WARNING_GB, STORAGE_ERROR_GB,
# CORS_ORIGINS, DATA_DIR).
EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
