ARG PYTHON_VERSION=3.13-alpine

# Builder stage: install build tools & dependencies (wheels cached for copy)
FROM python:${PYTHON_VERSION} AS builder

WORKDIR /build

# Install build dependencies only here
RUN apk add --no-cache --virtual .build-deps \
    gcc \
    musl-dev \
    python3-dev

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && rm -rf ~/.cache/pip

COPY src/ ./src/

# Remove build dependencies to shrink the layer (artifacts already compiled)
RUN apk del .build-deps || true

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

# Copy only installed site-packages and scripts from builder (keeps wheels out)
COPY --from=builder /usr/local/lib/python*/site-packages /usr/local/lib/python*/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/src/ ./src/

# Prepare config directory and adjust ownership
RUN mkdir -p /app/config && chown -R appuser:appgroup /app

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
