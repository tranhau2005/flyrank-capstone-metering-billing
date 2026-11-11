#!/bin/sh
set -eu
python -m app.worker &
worker_pid=$!
cleanup() { kill "$worker_pid" 2>/dev/null || true; wait "$worker_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true; cleanup; exit 0' INT TERM
wait "$api_pid"
