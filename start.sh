#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-/models}"
MODEL_PATH="${MODEL_DIR}/qwen.gguf"
MMPROJ_PATH="${MODEL_DIR}/mmproj.gguf"
PORT="${PORT:-8000}"

model_worker() {
  mkdir -p "${MODEL_DIR}"

  if [ ! -f "${MODEL_PATH}" ] && [ -n "${MODEL_URL:-}" ]; then
    wget -O "${MODEL_PATH}" "${MODEL_URL}"
  fi

  if [ ! -f "${MMPROJ_PATH}" ] && [ -n "${MMPROJ_URL:-}" ]; then
    wget -O "${MMPROJ_PATH}" "${MMPROJ_URL}"
  fi

  if [ -f "${MODEL_PATH}" ] && [ -f "${MMPROJ_PATH}" ]; then
    exec /llama.cpp/build/bin/llama-server \
      -m "${MODEL_PATH}" \
      --mmproj "${MMPROJ_PATH}" \
      --host 127.0.0.1 \
      --port 8080
  fi
}

model_worker &
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
