FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential cmake python3 python3-pip wget \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp /llama.cpp
WORKDIR /llama.cpp
RUN cmake -B build && cmake --build build --config Release -j

ENV MODEL_DIR=/models
RUN mkdir -p "${MODEL_DIR}"
WORKDIR "${MODEL_DIR}"

ENV MODEL_URL=""
ENV MMPROJ_URL=""

WORKDIR /app
COPY main.py /app/main.py

ENV PORT=8000
EXPOSE 8000

ENV LLAMA_URL=http://127.0.0.1:8080/v1/chat/completions
ENV LLAMA_MODEL=qwen2.5-vl

CMD bash -lc '\
  if [ ! -f "${MODEL_DIR}/qwen.gguf" ] && [ -n "${MODEL_URL}" ]; then wget -O "${MODEL_DIR}/qwen.gguf" "${MODEL_URL}"; fi; \
  if [ ! -f "${MODEL_DIR}/mmproj.gguf" ] && [ -n "${MMPROJ_URL}" ]; then wget -O "${MODEL_DIR}/mmproj.gguf" "${MMPROJ_URL}"; fi; \
  if [ -f "${MODEL_DIR}/qwen.gguf" ] && [ -f "${MODEL_DIR}/mmproj.gguf" ]; then \
    /llama.cpp/build/bin/llama-server \
      -m "${MODEL_DIR}/qwen.gguf" \
      --mmproj "${MODEL_DIR}/mmproj.gguf" \
      --host 127.0.0.1 \
      --port 8080 \
    & \
  fi; \
  uvicorn main:app --host 0.0.0.0 --port "${PORT}" \
'
