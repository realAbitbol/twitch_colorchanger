FROM python:3.12-alpine

WORKDIR /app

COPY twitch_colorchanger.py /app/twitch_colorchanger.py

RUN pip install --no-cache-dir requests

ENV PYTHONUNBUFFERED=1

CMD ["python", "twitch_colorchanger.py"]
