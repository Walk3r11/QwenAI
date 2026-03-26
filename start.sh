#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-/models}"
MODEL_PATH="${MODEL_DIR}/qwen.gguf"
MMPROJ_PATH="${MODEL_DIR}/mmproj.gguf"
PORT="${PORT:-8000}"

mkdir -p "${MODEL_DIR}"

if [ ! -f "${MODEL_PATH}" ] && [ -n "${MODEL_URL:-}" ]; then
  echo "Downloading qwen.gguf..."
  wget -q -O "${MODEL_PATH}.tmp" "${MODEL_URL}"
  mv "${MODEL_PATH}.tmp" "${MODEL_PATH}"
  echo "Downloaded qwen.gguf."
fi

if [ ! -f "${MMPROJ_PATH}" ] && [ -n "${MMPROJ_URL:-}" ]; then
  echo "Downloading mmproj.gguf..."
  wget -q -O "${MMPROJ_PATH}.tmp" "${MMPROJ_URL}"
  mv "${MMPROJ_PATH}.tmp" "${MMPROJ_PATH}"
  echo "Downloaded mmproj.gguf."
fi

if [ -f "${MODEL_PATH}" ] && [ -f "${MMPROJ_PATH}" ]; then
  echo "Starting llama-server..."
  /llama.cpp/build/bin/llama-server \
    -m "${MODEL_PATH}" \
    --mmproj "${MMPROJ_PATH}" \
    --host 127.0.0.1 \
    --port 8080 &
fi

echo "Starting API server..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
