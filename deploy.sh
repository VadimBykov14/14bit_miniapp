#!/usr/bin/env bash
# Выкатка собранного проекта: поднимает контейнеры из образов, которые
# собрал build.sh, перечитывает Caddy и регистрирует вебхук.
# Вызывается раннером GitHub Actions на сервере после build.sh.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/max26}"
cd "$APP_DIR"

echo "==> поднимаю контейнеры"
# Миграции API применяются сами при старте контейнера.
docker compose up -d

# Caddyfile смонтирован файлом и сам не перечитывается.
echo "==> перечитываю конфиг Caddy"
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile \
  || docker compose restart caddy

# Подписка с message_callback — иначе «Не присылать такие» не дойдёт до бота.
echo "==> регистрирую вебхук"
docker compose run --rm bot python set_webhook.py

echo "==> состояние"
docker compose ps

DOMAIN="$(grep '^BOT_DOMAIN=' .env | cut -d= -f2-)"
echo "==> проверяю https://$DOMAIN/health"
curl -fsS --retry 10 --retry-delay 3 --retry-all-errors "https://$DOMAIN/health"
echo
echo "Готово."
