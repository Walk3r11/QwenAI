#!/usr/bin/env bash

MODEL_DIR="${MODEL_DIR:-/models}"
# Default to LLaVA OneVision (7b). Keep a legacy fallback for older deployments.
MODEL_FILE="${MODEL_FILE:-llava-onevision-7b.gguf}"
LEGACY_MODEL_FILE="${LEGACY_MODEL_FILE:-qwen.gguf}"
MMPROJ_FILE="${MMPROJ_FILE:-mmproj.gguf}"

MODEL_PATH_NEW="${MODEL_DIR}/${MODEL_FILE}"
MODEL_PATH_LEGACY="${MODEL_DIR}/${LEGACY_MODEL_FILE}"
MMPROJ_PATH="${MODEL_DIR}/${MMPROJ_FILE}"
PORT="${PORT:-8000}"
ENABLE_AI_RAW="${ENABLE_AI:-false}" # toggle
ENABLE_AI_NORMALIZED="$(printf '%s' "${ENABLE_AI_RAW}" | tr '[:upper:]' '[:lower:]')"

mkdir -p "${MODEL_DIR}"

if [ "${ENABLE_AI_NORMALIZED}" = "1" ] || [ "${ENABLE_AI_NORMALIZED}" = "true" ] || [ "${ENABLE_AI_NORMALIZED}" = "yes" ] || [ "${ENABLE_AI_NORMALIZED}" = "on" ]; then
  echo "AI is enabled (ENABLE_AI=${ENABLE_AI_RAW})."
  if [ ! -f "${MODEL_PATH_NEW}" ] && [ -n "${MODEL_URL:-}" ]; then
    echo "Downloading ${MODEL_FILE}..."
    if wget -q -O "${MODEL_PATH_NEW}.tmp" "${MODEL_URL}"; then
      mv "${MODEL_PATH_NEW}.tmp" "${MODEL_PATH_NEW}"
      echo "Downloaded ${MODEL_FILE}."
    else
      echo "FAILED to download ${MODEL_FILE}"
      rm -f "${MODEL_PATH_NEW}.tmp"
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

  MODEL_PATH_EFF="${MODEL_PATH_NEW}"
  if [ ! -f "${MODEL_PATH_EFF}" ] && [ -f "${MODEL_PATH_LEGACY}" ]; then
    echo "Using legacy model file: ${LEGACY_MODEL_FILE}"
    MODEL_PATH_EFF="${MODEL_PATH_LEGACY}"
  fi

  if [ -f "${MODEL_PATH_EFF}" ] && [ -f "${MMPROJ_PATH}" ]; then
    echo "Starting llama-server..."
    /llama.cpp/build/bin/llama-server \
      -m "${MODEL_PATH_EFF}" \
      --mmproj "${MMPROJ_PATH}" \
      --host 127.0.0.1 \
      --port 8081 \
      --ctx-size 4096 \
      --batch-size 512 \
      --parallel 1 &
  else
    echo "Model files missing — AI will not be available."
    echo "  ${MODEL_FILE}: $([ -f "${MODEL_PATH_NEW}" ] && echo 'OK' || echo 'MISSING')"
    echo "  ${LEGACY_MODEL_FILE}: $([ -f "${MODEL_PATH_LEGACY}" ] && echo 'OK' || echo 'MISSING')"
    echo "  ${MMPROJ_FILE}: $([ -f "${MMPROJ_PATH}" ] && echo 'OK' || echo 'MISSING')"
  fi
else
  echo "AI is disabled (ENABLE_AI=${ENABLE_AI_RAW}); skipping model download and llama-server."
fi

echo "Starting API server..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
