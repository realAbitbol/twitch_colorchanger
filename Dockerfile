# Use Python 3.13 Alpine for minimal image size and latest Python features
FROM python:3.13-alpine

# Set metadata
LABEL maintainer="Twitch ColorChanger Bot"
LABEL description="Multi-user Twitch chat color changer bot"
LABEL version="2.0"

# Set working directory
WORKDIR /app

# Create non-root user for security and install Python dependencies
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir requests

# Copy application code
COPY --chown=appuser:appgroup twitch_colorchanger.py /app/twitch_colorchanger.py

# Ensure the script is executable
RUN chmod +x /app/twitch_colorchanger.py

# Switch to non-root user
USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1

# Health check to ensure the container is working
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Run the application
CMD ["python", "twitch_colorchanger.py"]
