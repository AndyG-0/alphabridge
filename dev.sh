#!/usr/bin/env bash
# Native dev loop with auto-reload: Flask debug reloader (:5001) + Vite HMR (:5173).
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  # Not `source`d: values like EDGAR_IDENTITY contain unquoted spaces.
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && export "$key=$value"
  done < .env
fi
# .env holds the container path (/app/data); flask's own dotenv loading never overrides existing env.
export DATABASE_URL="${DEV_DATABASE_URL:-sqlite:///$PWD/data/alphabridge.db}"
# The reloader forks a child, so the scheduler would run twice; opt in explicitly.
export ENABLE_SCHEDULER="${ENABLE_SCHEDULER:-0}"

trap 'kill 0' EXIT INT TERM

(
  cd backend
  source .venv/bin/activate
  alembic upgrade head
  exec flask --app wsgi run --debug -p 5001
) &

(
  cd frontend
  exec npm run dev
) &

wait
