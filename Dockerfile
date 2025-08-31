FROM python:3.13-alpine

LABEL maintainer="Twitch ColorChanger Bot"
LABEL description="Multi-user Twitch chat color changer bot"
LABEL version="2.2"

# Create non-root user for security
RUN addgroup -g 1000 -S appgroup && \
    adduser -u 1000 -S appuser -G appgroup

WORKDIR /app

# Install dependencies and handle RISCV64 build requirements
RUN pip install --no-cache-dir --upgrade pip && \
    if [ "$(uname -m)" = "riscv64" ]; then \
        apk add --no-cache --virtual .build-deps gcc musl-dev python3-dev; \
    fi

# Copy and install Python requirements (separate layer for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$(uname -m)" = "riscv64" ]; then \
        apk del .build-deps; \
    fi

# Copy application files
COPY src/ ./src/

# Create config directory and set permissions
RUN mkdir -p /app/config && \
    chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TWITCH_CONF_FILE=/app/config/twitch_colorchanger.conf

VOLUME ["/app/config"]

# Optimized healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import os,json,subprocess,sys; cf=os.environ.get('TWITCH_CONF_FILE','/app/config/twitch_colorchanger.conf'); f=open(cf); c=json.load(f); f.close(); sys.exit(0 if c.get('users') and subprocess.run(['pgrep','-f','python.*src/main.py'],capture_output=True).returncode==0 else 1)" || exit 1

CMD ["python", "-m", "src.main"]
