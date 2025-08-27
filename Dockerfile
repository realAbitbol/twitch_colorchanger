# Use Python 3.13 Alpine for minimal image size and latest Python features
FROM python:3.13-alpine

# Set metadata
LABEL maintainer="Twitch ColorChanger Bot"
LABEL description="Multi-user Twitch chat color changer bot"
LABEL version="2.1"

# Set working directory
WORKDIR /app

# Install dependencies, create base user (will be adjusted at runtime), and add startup script
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup && \
    apk add --no-cache su-exec && \
    pip install --no-cache-dir --upgrade pip && \
    if [ "$(uname -m)" = "riscv64" ]; then \
        apk add --no-cache --virtual .build-deps gcc musl-dev python3-dev; \
    fi && \
    printf '%s\n' \
    '#!/bin/sh' \
    '' \
    'set -e' \
    '' \
    '# Optional forced root mode before any remap' \
    'if [ "${RUN_AS_ROOT:-0}" = "1" ]; then' \
    '  echo "[INFO] RUN_AS_ROOT=1 - running as root without dropping privileges"' \
    '  exec "$@"' \
    'fi' \
    '' \
    '# Dynamic user remap (runs as root here)' \
    'TARGET_UID="${PUID:-1001}"' \
    'TARGET_GID="${PGID:-1001}"' \
    '' \
    '# Recreate group/user if IDs differ' \
    'CURRENT_UID=$(id -u appuser 2>/dev/null || echo 0)' \
    'CURRENT_GID=$(getent group appgroup 2>/dev/null | cut -d: -f3 || echo 0)' \
    'if [ "$CURRENT_UID" != "$TARGET_UID" ] || [ "$CURRENT_GID" != "$TARGET_GID" ]; then' \
    '  deluser appuser 2>/dev/null || true' \
    '  delgroup appgroup 2>/dev/null || true' \
    '  # Try to find existing group with TARGET_GID' \
    '  # Lookup existing group by GID (portable, avoid awk extensions)' \
    '  EXISTING_GROUP=""' \
    '  while IFS=: read -r NAME _ GID _; do' \
    '    if [ "$GID" = "$TARGET_GID" ]; then EXISTING_GROUP="$NAME"; break; fi' \
    '  done < /etc/group' \
    '  if [ -n "$EXISTING_GROUP" ]; then' \
    '    adduser -u "$TARGET_UID" -S appuser -G "$EXISTING_GROUP"' \
    '  else' \
    '    addgroup -g "$TARGET_GID" -S appgroup || addgroup -S appgroup' \
    '    adduser -u "$TARGET_UID" -S appuser -G appgroup' \
    '  fi' \
    'fi' \
    '' \
    '# Ensure config dir exists (handle volume mount race)' \
    'mkdir -p /app/config' \
    'sleep 0.2' \
    'chown -R appuser:appgroup /app/config 2>/dev/null || true' \
    'chmod 755 /app/config 2>/dev/null || true' \
    '' \
    '# Pre-create config file as root if missing to avoid later write failure after privilege drop' \
    'CONF_FILE="${TWITCH_CONF_FILE:-/app/config/twitch_colorchanger.conf}"' \
    'if [ ! -f "$CONF_FILE" ]; then' \
    '  echo "{\"users\": []}" > "$CONF_FILE" 2>/dev/null || true' \
    'fi' \
    '# Ensure ownership & perms (ignore failures on restrictive NAS)' \
    'chown appuser:appgroup "$CONF_FILE" 2>/dev/null || true' \
    'chmod 644 "$CONF_FILE" 2>/dev/null || true' \
    '' \
    '# If file still not writable by target user, warn' \
    'if ! su-exec appuser:appgroup sh -c "[ -w \"$CONF_FILE\" ]"; then' \
    '  echo "[WARN] Config file not writable by remapped user (UID=$TARGET_UID GID=$TARGET_GID). Check NAS share permissions." >&2' \
    '  if [ "${AUTO_ROOT_FALLBACK:-1}" = "1" ]; then' \
    '    echo "[WARN] AUTO_ROOT_FALLBACK=1 - continuing as root to allow writes" >&2' \
    '    exec "$@"' \
    '  fi' \
    'fi' \
    '' \
    '# Drop privileges and exec' \
    'exec su-exec appuser:appgroup "$@"' \
    > /usr/local/bin/start.sh && \
    chmod +x /usr/local/bin/start.sh

# Copy and install requirements
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    # Clean up build dependencies for RISC-V
    if [ "$(uname -m)" = "riscv64" ]; then \
        apk del .build-deps; \
    fi

# Copy application code
COPY --chown=appuser:appgroup main.py /app/main.py
COPY --chown=appuser:appgroup src/ /app/src/

# Create config directory and ensure main script is executable
RUN mkdir -p /app/config && \
    chown appuser:appgroup /app/config && \
    chmod +x /app/main.py

# (Intentionally run as root; start.sh will drop privileges with su-exec)

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1

# Set default config file path to the volume directory
ENV TWITCH_CONF_FILE=/app/config/twitch_colorchanger.conf

# Create volume for configuration persistence only
VOLUME ["/app/config"]

# Health check to ensure the application can start
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "from src.config import get_docker_config; users = get_docker_config(); exit(0 if users else 1)" || exit 1

# Run the application (start.sh drops privileges to appuser/appgroup or remapped IDs)
CMD ["/usr/local/bin/start.sh", "python", "main.py"]
