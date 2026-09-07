FROM python:3.12-slim

WORKDIR /app
COPY . /app

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Kyiv \
    STATE_PATH=/app/data/state.json

RUN mkdir -p /app/data

# Зависимостей нет — только stdlib.
CMD ["python", "bot.py", "--loop"]
