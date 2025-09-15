# syntax=docker/dockerfile:1.7-labs
ARG PYTHON_VERSION=3.13-alpine

# Builder stage: build wheels for all dependencies (compile C-exts when needed)
FROM python:${PYTHON_VERSION} AS builder
WORKDIR /app
ARG TARGETARCH
COPY pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip wheel -e . -w /app/wheels && \
    # Strip all .so files in built wheels (if any)
    find /app/wheels -name '*.so' -exec strip --strip-unneeded {} + || true

    # Runtime stage: minimal image, install from prebuilt wheels only
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

# Install app dependencies from wheels (no compiler in final image)
COPY --from=builder /app/wheels /wheels
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-index --find-links=/wheels --no-compile -e . && \
    pip uninstall -y pip setuptools wheel

# Copy source
COPY --chown=appuser:appgroup src/ ./src/

# Prepare config directory and adjust ownership
RUN mkdir -p /app/config && chown appuser:appgroup /app/config

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TWITCH_CONF_FILE=/app/config/twitch_colorchanger.conf \
    TWITCH_BROADCASTER_CACHE=/app/config/broadcaster_ids.cache.json

VOLUME ["/app/config"]


# Use tini as PID 1 to handle signals & reap zombies (safer long-running operation)
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python", "-m", "src.main"]
