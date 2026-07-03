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

STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"
BACKEND_PORT="${BACKEND_PORT:-9000}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
# Streamlit UI feature flag: v2 (default, issue #19 plain-language redesign) or v1 (legacy)
STREAMLIT_UI="${STREAMLIT_UI:-v2}"
case "$STREAMLIT_UI" in
  v2) STREAMLIT_ENTRY="app_streamlit_v2.py" ;;
  v1) STREAMLIT_ENTRY="app_streamlit_legacy.py" ;;
  *)
    echo "error: STREAMLIT_UI must be 'v1' or 'v2' (got: $STREAMLIT_UI)" >&2
    exit 1
    ;;
esac
# LocalAI (Apache 2.0, zero VC) — https://localai.io
# Default port: 8080. Override with LOCALAI_BASE_URL env var.
LOCALAI_BASE_URL="${LOCALAI_BASE_URL:-http://localhost:8080/v1}"
# Apertus 8B Instruct — Swiss AI Initiative (EPFL/ETH/CSCS), Apache 2.0, 1000+ languages
# https://huggingface.co/swiss-ai/Apertus-8B-Instruct-2509-GGUF
MODEL_WORLD="${MODEL_WORLD:-apertus-8b-instruct}"
# EuroLLM 22B Instruct — EU Horizon Europe / EuroHPC, Apache 2.0, 35 EU languages
# https://huggingface.co/utter-project/EuroLLM-22B-Instruct-GGUF
MODEL_EU="${MODEL_EU:-eurollm-22b-instruct}"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-http://localhost:${STREAMLIT_PORT},http://127.0.0.1:${STREAMLIT_PORT}}"
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
echo "UI (Streamlit $STREAMLIT_UI -> $STREAMLIT_ENTRY): http://localhost:$STREAMLIT_PORT"
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

# Webapp requirements are tracked separately so backend deployments don't drag
# in the Streamlit UI stack. Streamlit + requests are only needed when the UI
# process is launched from this script. Audit finding GAP-014.
if [[ -f "$APP_DIR/requirements.txt" ]]; then
  echo "Installing webapp requirements..."
  "$VENV_PATH/bin/python" -m pip install -r "$APP_DIR/requirements.txt" >/dev/null
fi

echo "Starting backend..."
"$VENV_PATH/bin/python" -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload --app-dir "$BACKEND_DIR" &
BACKEND_PID=$!

echo "Starting UI (Streamlit $STREAMLIT_UI: $STREAMLIT_ENTRY)..."
(cd "$APP_DIR" && "$VENV_PATH/bin/python" -m streamlit run "$STREAMLIT_ENTRY" \
  --server.port "$STREAMLIT_PORT" \
  --server.headless true) &
STREAMLIT_PID=$!

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${STREAMLIT_PID:-}" ]]; then
    kill "$STREAMLIT_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# Wait on both so the script (and thus the EXIT trap) stays alive until
# one exits or the script is signaled — this ensures cleanup() actually runs
# for both processes even under a non-interactive SIGTERM, not just Ctrl+C.
wait -n "$BACKEND_PID" "$STREAMLIT_PID"
