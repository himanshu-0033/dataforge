#!/bin/sh
set -eu
test -n "${DATABASE_PATH:-}"
rm -f "$DATABASE_PATH" "$DATABASE_PATH-shm" "$DATABASE_PATH-wal"
exec ../.venv/bin/uvicorn pickmate.api.app:app --app-dir ../backend --host 127.0.0.1 --port 8001
