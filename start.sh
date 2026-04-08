#!/usr/bin/env bash

MODEL_DIR="${MODEL_DIR:-/models}"
MODEL_PATH="${MODEL_DIR}/qwen.gguf"
MMPROJ_PATH="${MODEL_DIR}/mmproj.gguf"
PORT="${PORT:-8000}"
ENABLE_AI_RAW="${ENABLE_AI:-false}"
ENABLE_AI_NORMALIZED="$(printf '%s' "${ENABLE_AI_RAW}" | tr '[:upper:]' '[:lower:]')"

mkdir -p "${MODEL_DIR}"

if [ "${ENABLE_AI_NORMALIZED}" = "1" ] || [ "${ENABLE_AI_NORMALIZED}" = "true" ] || [ "${ENABLE_AI_NORMALIZED}" = "yes" ] || [ "${ENABLE_AI_NORMALIZED}" = "on" ]; then
  echo "AI is enabled (ENABLE_AI=${ENABLE_AI_RAW})."
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
      --ctx-size 4096 \
      --batch-size 512 \
      --parallel 1 &
  else
    echo "Model files missing — AI will not be available."
    echo "  qwen.gguf: $([ -f "${MODEL_PATH}" ] && echo 'OK' || echo 'MISSING')"
    echo "  mmproj.gguf: $([ -f "${MMPROJ_PATH}" ] && echo 'OK' || echo 'MISSING')"
  fi
else
  echo "AI is disabled (ENABLE_AI=${ENABLE_AI_RAW}); skipping model download and llama-server."
fi

echo "Starting API server..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
