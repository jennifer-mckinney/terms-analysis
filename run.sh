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
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"
BACKEND_PORT="${BACKEND_PORT:-9000}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
LOCALAI_BASE_URL="${LOCALAI_BASE_URL:-http://localhost:8080/v1}"
MODEL_WORLD="${MODEL_WORLD:-apertus-8b-instruct}"
MODEL_EU="${MODEL_EU:-eurollm-22b-instruct}"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-http://localhost:${PORT},http://127.0.0.1:${PORT},http://localhost:${STREAMLIT_PORT},http://127.0.0.1:${STREAMLIT_PORT}}"
API_BASE_URL="${API_BASE_URL:-http://localhost:${BACKEND_PORT}}"

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
export API_BASE_URL

echo "Starting Terms & Policies Reviewer..."
echo "Primary UI (Streamlit): http://localhost:$STREAMLIT_PORT"
echo "Fallback UI (vanilla JS SPA): http://localhost:$PORT"
echo "Backend dir: $BACKEND_DIR"
echo "Backend URL: http://localhost:$BACKEND_PORT"
echo "LocalAI: $LOCALAI_BASE_URL (world=$MODEL_WORLD, eu=$MODEL_EU)"
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

echo "Starting fallback UI (vanilla JS SPA)..."
(cd "$APP_DIR" && "$VENV_PATH/bin/python" -m http.server "$PORT") &
FALLBACK_PID=$!

echo "Starting primary UI (Streamlit)..."
(cd "$APP_DIR" && "$VENV_PATH/bin/python" -m streamlit run app_streamlit.py \
  --server.port "$STREAMLIT_PORT" \
  --server.headless true) &
STREAMLIT_PID=$!

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${FALLBACK_PID:-}" ]]; then
    kill "$FALLBACK_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${STREAMLIT_PID:-}" ]]; then
    kill "$STREAMLIT_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# Wait on all three so the script (and thus the EXIT trap) stays alive until
# one exits or the script is signaled — this ensures cleanup() actually runs
# for all three processes even under a non-interactive SIGTERM, not just Ctrl+C.
wait -n "$BACKEND_PID" "$FALLBACK_PID" "$STREAMLIT_PID"
