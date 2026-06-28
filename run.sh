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
# LocalAI (Apache 2.0, zero VC) — https://localai.io
# Default port: 8080. Override with LOCALAI_BASE_URL env var.
LOCALAI_BASE_URL="${LOCALAI_BASE_URL:-http://localhost:8080/v1}"
# Apertus 8B Instruct — Swiss AI Initiative (EPFL/ETH/CSCS), Apache 2.0, 1000+ languages
# https://huggingface.co/swiss-ai/Apertus-8B-Instruct-2509-GGUF
MODEL_WORLD="${MODEL_WORLD:-apertus-8b-instruct}"
# EuroLLM 22B Instruct — EU Horizon Europe / EuroHPC, Apache 2.0, 35 EU languages
# https://huggingface.co/utter-project/EuroLLM-22B-Instruct-GGUF
MODEL_EU="${MODEL_EU:-eurollm-22b-instruct}"
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

export LOCALAI_BASE_URL
export MODEL_WORLD
export MODEL_EU
export ALLOWED_ORIGINS

echo "Starting Terms & Policies Reviewer..."
echo "App dir:     $APP_DIR"
echo "App URL:     http://localhost:$PORT"
echo "Backend dir: $BACKEND_DIR"
echo "Backend URL: http://localhost:$BACKEND_PORT"
echo "LocalAI:     $LOCALAI_BASE_URL"
echo "  world model: $MODEL_WORLD (Apertus — Swiss AI Initiative)"
echo "  EU model:    $MODEL_EU (EuroLLM — EU Horizon Europe)"
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
