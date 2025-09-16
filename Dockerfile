# syntax=docker/dockerfile:1.7-labs
ARG PYTHON_VERSION=3.13-alpine

# =========================
# Builder stage
# =========================
FROM python:${PYTHON_VERSION} AS builder
WORKDIR /app
ARG TARGETARCH

# Build args for metadata (captured into final image via runtime labels)
ARG VCS_REF="unknown"
ARG BUILD_DATE="unknown"

# Install build dependencies
RUN apk add --no-cache build-base libffi-dev openssl-dev

# Upgrade pip and install build tools
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-tools-${TARGETARCH} \
    pip install --upgrade hatchling pip setuptools wheel

# Copy metadata and source code
COPY pyproject.toml LICENSE README.md ./
COPY src/ ./src/

# Build wheels for the project and its dependencies
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-wheels-${TARGETARCH} \
    pip wheel . -w /app/wheels && \
    find /app/wheels -name '*.so' -exec strip --strip-unneeded {} + || true

# =========================
# Runtime (hardened) stage
# =========================
FROM python:${PYTHON_VERSION} AS runtime
WORKDIR /app

# OCI labels (populate via build-args)
ARG VCS_REF="unknown"
ARG BUILD_DATE="unknown"
LABEL org.opencontainers.image.title="twitch-colorchanger" \
      org.opencontainers.image.description="Multi-user Twitch chat color changer bot" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.source="https://github.com/realAbitbol/twitch_colorchanger" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      maintainer="Twitch ColorChanger Bot"

# Recommended Python / pip environment flags + app-specific envs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TWITCH_CONF_FILE=/app/config/twitch_colorchanger.conf \
    TWITCH_BROADCASTER_CACHE=/app/config/broadcaster_ids.cache.json

# Config directory that users can mount
VOLUME ["/app/config"]

# Create a non-root user and install tini for a proper init
RUN addgroup -g 1000 -S appgroup && \
    adduser -u 1000 -S appuser -G appgroup && \
    apk add --no-cache tini && \
    mkdir -p /app/config && chown appuser:appgroup /app/config

# Copy built wheels from builder stage
COPY --from=builder /app/wheels /wheels

# Install the prebuilt wheel and remove pip/setuptools/wheel to harden the runtime
RUN pip install --no-index --find-links=/wheels twitch_colorchanger && \
    pip uninstall -y pip setuptools wheel

# Run as non-root
USER appuser

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["twitch-colorchanger"]
