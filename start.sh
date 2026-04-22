#!/usr/bin/env bash
set -e

PORT="${PORT:-8000}"
ENABLE_AI_RAW="${ENABLE_AI:-false}"
ENABLE_AI_NORMALIZED="$(printf '%s' "${ENABLE_AI_RAW}" | tr '[:upper:]' '[:lower:]')"

if [ "${ENABLE_AI_NORMALIZED}" = "1" ] || [ "${ENABLE_AI_NORMALIZED}" = "true" ] || [ "${ENABLE_AI_NORMALIZED}" = "yes" ] || [ "${ENABLE_AI_NORMALIZED}" = "on" ]; then
  if [ -z "${GROQ_API_KEY:-}" ]; then
    echo "WARN: ENABLE_AI is on but GROQ_API_KEY is empty — vision/recipes will return 503."
  else
    echo "AI enabled, using Groq vision model: ${GROQ_VISION_MODEL:-(default)}"
  fi
else
  echo "AI is disabled (ENABLE_AI=${ENABLE_AI_RAW})."
fi

echo "Starting API server on port ${PORT}..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
