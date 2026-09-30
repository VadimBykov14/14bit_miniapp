FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY services/bot-service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./
COPY services/bot-service/ ./

# Бот не делает ничего, что требует root.
RUN useradd --system --uid 10001 bot && chown -R bot /app
USER bot

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
