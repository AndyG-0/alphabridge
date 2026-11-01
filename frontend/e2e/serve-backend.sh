#!/usr/bin/env bash
# Starts Flask on :5001 against a fresh seeded SQLite DB (demo data only).
set -euo pipefail
cd "$(dirname "$0")/../../backend"
DB="$(mktemp -d)/e2e.db"
export DATABASE_URL="sqlite:///$DB" ENABLE_SCHEDULER=0 ACCESS_TOKEN="" APP_SECRET="e2e-secret"
[ -f .venv/bin/activate ] && source .venv/bin/activate
alembic upgrade head
python -m seed
exec flask --app wsgi run -p "${API_PORT:-5001}"
