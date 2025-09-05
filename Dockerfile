# syntax=docker/dockerfile:1.7-labs
ARG PYTHON_VERSION=3.13-alpine

# Builder stage: install build tools & dependencies (wheels cached for copy)
FROM python:${PYTHON_VERSION} AS builder

WORKDIR /build

# Ensure no .pyc compiled & faster installs (pyc disabled) during build.
# Allow pip's cache (remove PIP_NO_CACHE_DIR & --no-cache-dir) so BuildKit cache mount is effective.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt ./

# (1 & 2 & 4) Single-layer build deps + pip install with BuildKit cache + removal + no bytecode
# Uses BuildKit cache mount to persist wheel/pip cache across builds without baking it into layers.
RUN --mount=type=cache,target=/root/.cache/pip \
        apk add --no-cache --virtual .build-deps \
            gcc \
            musl-dev \
            python3-dev \
        && pip install --no-compile -r requirements.txt \
        && apk del .build-deps

# Copy application source (not installed as package; executed via -m)
COPY src/ ./src/

# Package site-packages with ABI marker for reliable copy without knowing version later
RUN ABI_DIR=$(python -c 'import sys;import pathlib;print(f"python{sys.version_info.major}.{sys.version_info.minor}")') \
    && echo "${ABI_DIR}" > PYTHON_ABI \
    && tar -C /usr/local/lib -cf site-packages.tar ${ABI_DIR}/site-packages

# Runtime stage: minimal image with only runtime deps + app
FROM python:${PYTHON_VERSION} AS runtime

# Supply optional build metadata (pass with --build-arg VCS_REF, --build-arg BUILD_DATE)
ARG VCS_REF="unknown"
ARG BUILD_DATE="unknown"

LABEL org.opencontainers.image.title="twitch-colorchanger" \
    org.opencontainers.image.description="Multi-user Twitch chat color changer bot" \
    org.opencontainers.image.version="2.3" \
    org.opencontainers.image.source="https://github.com/realAbitbol/twitch_colorchanger" \
    org.opencontainers.image.revision="${VCS_REF}" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    maintainer="Twitch ColorChanger Bot"

# Create non-root user (explicit IDs for reproducibility) and install tini as minimal init
RUN addgroup -g 1000 -S appgroup \
 && adduser -u 1000 -S appuser -G appgroup \
 && apk add --no-cache tini

WORKDIR /app

# (3) Auto-detected ABI: extract packaged site-packages tar and copy source
COPY --from=builder /build/PYTHON_ABI /PYTHON_ABI
COPY --from=builder /build/site-packages.tar /site-packages.tar
RUN ABI=$(cat /PYTHON_ABI) \
    && mkdir -p /usr/local/lib/${ABI} \
    && tar -C /usr/local/lib -xf /site-packages.tar \
    && rm /site-packages.tar /PYTHON_ABI
COPY --from=builder /build/src/ ./src/

# Prepare config directory and adjust ownership
RUN mkdir -p /app/config && chown -R appuser:appgroup /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TWITCH_CONF_FILE=/app/config/twitch_colorchanger.conf \
    TWITCH_BROADCASTER_CACHE=/app/config/broadcaster_ids.cache.json

VOLUME ["/app/config"]

# Lean healthcheck uses built-in mode; avoids long inline Python one-liner.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -m src.main --health-check || exit 1

# Use tini as PID 1 to handle signals & reap zombies (safer long-running operation)
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python", "-m", "src.main"]
