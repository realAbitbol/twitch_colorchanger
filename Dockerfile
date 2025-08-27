# Use Python 3.13 Alpine for minimal image size and latest Python features
FROM python:3.13-alpine

# Set metadata
LABEL maintainer="Twitch ColorChanger Bot"
LABEL description="Multi-user Twitch chat color changer bot"
LABEL version="2.1"

# Set working directory
WORKDIR /app

# Create non-root user for security and install Python dependencies
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup && \
    pip install --no-cache-dir --upgrade pip && \
    # Install build dependencies for RISC-V and other architectures that need compilation
    if [ "$(uname -m)" = "riscv64" ]; then \
        apk add --no-cache --virtual .build-deps gcc musl-dev python3-dev; \
    fi && \
    # Create startup script to handle dynamic PUID/PGID
    echo '#!/bin/sh' > /usr/local/bin/start.sh && \
    echo 'if [ -n "$PUID" ] && [ -n "$PGID" ]; then' >> /usr/local/bin/start.sh && \
    echo '    # Change appuser UID/GID to match PUID/PGID' >> /usr/local/bin/start.sh && \
    echo '    if [ "$PUID" != "1001" ] || [ "$PGID" != "1001" ]; then' >> /usr/local/bin/start.sh && \
    echo '        deluser appuser 2>/dev/null || true' >> /usr/local/bin/start.sh && \
    echo '        delgroup appgroup 2>/dev/null || true' >> /usr/local/bin/start.sh && \
    echo '        addgroup -g "$PGID" -S appgroup 2>/dev/null || true' >> /usr/local/bin/start.sh && \
    echo '        adduser -u "$PUID" -S appuser -G appgroup 2>/dev/null || true' >> /usr/local/bin/start.sh && \
    echo '        # Change ownership AFTER creating the new user' >> /usr/local/bin/start.sh && \
    echo '        chown -R appuser:appgroup /app' >> /usr/local/bin/start.sh && \
    echo '        # Ensure config directory exists and is writable' >> /usr/local/bin/start.sh && \
    echo '        mkdir -p /app/config' >> /usr/local/bin/start.sh && \
    echo '        chmod 755 /app/config' >> /usr/local/bin/start.sh && \
    echo '    fi' >> /usr/local/bin/start.sh && \
    echo 'fi' >> /usr/local/bin/start.sh && \
    echo 'exec "$@"' >> /usr/local/bin/start.sh && \
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

# Switch to non-root user
USER appuser

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

# Run the application
CMD ["/usr/local/bin/start.sh", "python", "main.py"]
