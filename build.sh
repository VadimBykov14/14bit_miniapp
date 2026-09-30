#!/usr/bin/env bash
# Сборка проекта на сервере стенда: код из рабочей копии — в /opt/max26,
# затем образы docker compose. Контейнеры не трогает — их поднимает deploy.sh.
# Вызывается раннером GitHub Actions на сервере при пуше в main.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-/opt/max26}"

command -v rsync >/dev/null || { echo "Нет rsync: sudo apt-get install -y rsync" >&2; exit 1; }
docker compose version >/dev/null 2>&1 \
  || { echo "Нет docker с плагином compose: curl -fsSL https://get.docker.com | sh" >&2; exit 1; }

# .env с токеном бота, секретом вебхука и паролем БД живёт только на сервере:
# в репозитории и в GitHub секретов нет. Пароль БД менять нельзя — живой том
# базы создан с ним.
if [ ! -s "$APP_DIR/.env" ]; then
  echo "Нет $APP_DIR/.env. Нужны MAX_BOT_TOKEN, BOT_DOMAIN, WEBHOOK_SECRET," >&2
  echo "MAX_API_BASE=https://botapi.max.ru и POSTGRES_PASSWORD — заполните один раз." >&2
  exit 1
fi

echo "==> копирую проект в $APP_DIR"
# .env исключён, поэтому --delete его не тронет.
rsync -a --delete \
  --exclude '.git/' --exclude '.github/' --exclude 'docs/' \
  --exclude 'node_modules/' --exclude 'dist/' \
  --exclude '__pycache__/' --exclude '*.pyc' --exclude '*.pdf' \
  --exclude '.env' --exclude '.env.*' \
  "$HERE/" "$APP_DIR/"

echo "==> собираю образы"
cd "$APP_DIR"
docker compose build
