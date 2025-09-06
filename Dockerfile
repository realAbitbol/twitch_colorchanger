# syntax=docker/dockerfile:1.7-labs
ARG PYTHON_VERSION=3.13-alpine
FROM python:${PYTHON_VERSION} AS runtime

# Optional build metadata passed from CI (safe defaults if not provided)
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

# System deps only when needed (riscv64 edge case). Keep layer small.
ARG TARGETARCH
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    if [ "$TARGETARCH" = "riscv64" ]; then \
        apk add --no-cache --virtual .build-deps gcc musl-dev python3-dev; \
    fi

# Copy dependency spec first for better build caching
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt && \
    if [ "$TARGETARCH" = "riscv64" ]; then \
        apk del .build-deps; \
    fi

# Copy source
COPY --chown=appuser:appgroup src/ ./src/

# Prepare config directory and adjust ownership
RUN mkdir -p /app/config && chown appuser:appgroup /app/config

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
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
