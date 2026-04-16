FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

# APT on CI can be flaky (mirror sync / transient network). Add retries + timeouts
# and retry the whole update+install sequence a few times.
RUN set -eux; \
  printf '%s\n' \
    'Acquire::Retries "5";' \
    'Acquire::http::Timeout "30";' \
    'Acquire::https::Timeout "30";' \
    'Acquire::ftp::Timeout "30";' \
    > /etc/apt/apt.conf.d/80-retries; \
  for i in 1 2 3 4 5; do \
    rm -rf /var/lib/apt/lists/*; \
    apt-get update -y && \
    apt-get install -y --no-install-recommends \
      ca-certificates git build-essential cmake python3 python3-pip wget \
    && break; \
    echo "apt-get failed (attempt ${i}/5) — retrying..." >&2; \
    sleep 5; \
  done; \
  rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp /llama.cpp
WORKDIR /llama.cpp
RUN cmake -B build && cmake --build build --config Release -j

ENV MODEL_DIR=/models
RUN mkdir -p "${MODEL_DIR}"
WORKDIR "${MODEL_DIR}"

WORKDIR /app
COPY . /app/
RUN chmod +x /app/start.sh


ENV PORT=8000
EXPOSE 8000

ENV LLAMA_URL=http://127.0.0.1:8081/v1/chat/completions
ENV LLAMA_MODEL=llava-onevision-7b
ENV MODEL_FILE=llava-onevision-7b.gguf
ENV LEGACY_MODEL_FILE=qwen.gguf
ENV MMPROJ_FILE=mmproj.gguf

ENV MODEL_URL=""
ENV MMPROJ_URL=""

CMD ["/app/start.sh"]
