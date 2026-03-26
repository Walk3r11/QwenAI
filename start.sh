#!/usr/bin/env bash

MODEL_DIR="${MODEL_DIR:-/models}"
MODEL_PATH="${MODEL_DIR}/qwen.gguf"
MMPROJ_PATH="${MODEL_DIR}/mmproj.gguf"
PORT="${PORT:-8000}"

mkdir -p "${MODEL_DIR}"

if [ ! -f "${MODEL_PATH}" ] && [ -n "${MODEL_URL:-}" ]; then
  echo "Downloading qwen.gguf..."
  if wget -q -O "${MODEL_PATH}.tmp" "${MODEL_URL}"; then
    mv "${MODEL_PATH}.tmp" "${MODEL_PATH}"
    echo "Downloaded qwen.gguf."
  else
    echo "FAILED to download qwen.gguf"
    rm -f "${MODEL_PATH}.tmp"
  fi
fi

if [ ! -f "${MMPROJ_PATH}" ] && [ -n "${MMPROJ_URL:-}" ]; then
  echo "Downloading mmproj.gguf from: ${MMPROJ_URL}"
  if wget -q --max-redirect=5 -O "${MMPROJ_PATH}.tmp" "${MMPROJ_URL}"; then
    mv "${MMPROJ_PATH}.tmp" "${MMPROJ_PATH}"
    echo "Downloaded mmproj.gguf."
  else
    echo "FAILED to download mmproj.gguf (exit code: $?)"
    rm -f "${MMPROJ_PATH}.tmp"
  fi
fi

if [ -f "${MODEL_PATH}" ] && [ -f "${MMPROJ_PATH}" ]; then
  echo "Starting llama-server..."
  /llama.cpp/build/bin/llama-server \
    -m "${MODEL_PATH}" \
    --mmproj "${MMPROJ_PATH}" \
    --host 127.0.0.1 \
    --port 8081 \
    --ctx-size 2048 \
    --batch-size 256 \
    --parallel 1 \
    -ngl 0 &
else
  echo "Model files missing — AI will not be available."
  echo "  qwen.gguf: $([ -f "${MODEL_PATH}" ] && echo 'OK' || echo 'MISSING')"
  echo "  mmproj.gguf: $([ -f "${MMPROJ_PATH}" ] && echo 'OK' || echo 'MISSING')"
fi

echo "Starting API server..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
