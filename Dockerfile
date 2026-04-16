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
