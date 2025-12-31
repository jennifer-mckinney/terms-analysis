#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT_DIR/src/webapp"
BACKEND_DIR="$ROOT_DIR/src/backend"
VENV_PATH="$BACKEND_DIR/.venv"
ENV_FILE="$ROOT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  echo "Loading environment from $ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

PORT="${PORT:-8000}"
BACKEND_PORT="${BACKEND_PORT:-9000}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
LM_STUDIO_BASE_URL="${LM_STUDIO_BASE_URL:-http://127.0.0.1:1234/v1}"
LM_STUDIO_MODEL="${LM_STUDIO_MODEL:-qwen3-vl-4b-instruct-mlx}"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-http://localhost:${PORT},http://127.0.0.1:${PORT}}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "error: app directory not found: $APP_DIR" >&2
  exit 1
fi

if [[ ! -d "$BACKEND_DIR" ]]; then
  echo "error: backend directory not found: $BACKEND_DIR" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required. Install with: brew install python" >&2
  exit 1
fi

export LM_STUDIO_BASE_URL
export LM_STUDIO_MODEL
export ALLOWED_ORIGINS

echo "Starting Terms & Policies Reviewer..."
echo "App dir: $APP_DIR"
echo "App URL: http://localhost:$PORT"
echo "Backend dir: $BACKEND_DIR"
echo "Backend URL: http://localhost:$BACKEND_PORT"
echo "LM Studio: $LM_STUDIO_BASE_URL ($LM_STUDIO_MODEL)"
echo "Press Ctrl+C to stop."

if [[ ! -d "$VENV_PATH" ]]; then
  echo "Creating backend virtualenv..."
  python3 -m venv "$VENV_PATH"
fi

echo "Installing backend requirements..."
"$VENV_PATH/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt" >/dev/null

echo "Starting backend..."
"$VENV_PATH/bin/python" -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload --app-dir "$BACKEND_DIR" &
BACKEND_PID=$!

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

cd "$APP_DIR"
"$VENV_PATH/bin/python" -m http.server "$PORT"
