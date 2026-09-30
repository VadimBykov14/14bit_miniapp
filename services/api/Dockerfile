FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY services/api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./
COPY services/api/app ./app
COPY services/api/alembic.ini ./
COPY services/api/migrations ./migrations

RUN useradd --system --uid 10002 api && chown -R api /app
USER api

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
