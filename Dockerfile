FROM python:3.13-alpine

LABEL maintainer="Twitch ColorChanger Bot"
LABEL description="Multi-user Twitch chat color changer bot"
LABEL version="2.2"

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip && \
    if [ "$(uname -m)" = "riscv64" ]; then \
        apk add --no-cache --virtual .build-deps gcc musl-dev python3-dev; \
    fi

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$(uname -m)" = "riscv64" ]; then \
        apk del .build-deps; \
    fi

COPY main.py /app/main.py
COPY src/ /app/src/

RUN mkdir -p /app/config && chmod +x /app/main.py

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TWITCH_CONF_FILE=/app/config/twitch_colorchanger.conf

VOLUME ["/app/config"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import os,json,subprocess,sys; cf=os.environ.get('TWITCH_CONF_FILE','/app/config/twitch_colorchanger.conf'); f=open(cf); c=json.load(f); f.close(); sys.exit(0 if c.get('users') and subprocess.run(['pgrep','-f','python.*main.py'],capture_output=True).returncode==0 else 1)" || exit 1

CMD ["python", "main.py"]
