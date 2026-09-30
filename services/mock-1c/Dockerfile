FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN pip install --no-cache-dir "fastapi==0.141.1" "uvicorn[standard]==0.54.0" "httpx==0.28.1"

COPY services/mock-1c/app.py services/mock-1c/store.py services/mock-1c/ui.html services/mock-1c/ui.js services/mock-1c/reset_demo.py ./
COPY services/mock-1c/data.json ./

# Базы переживают перезапуск: номенклатуру не заводят заново после деплоя.
RUN mkdir -p /data

RUN useradd --system --uid 10003 onec && chown -R onec /app /data
USER onec

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
