FROM python:3.11-slim

ARG DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
  printf '%s\n' \
    'Acquire::Retries "5";' \
    'Acquire::http::Timeout "30";' \
    'Acquire::https::Timeout "30";' \
    > /etc/apt/apt.conf.d/80-retries; \
  apt-get update -y && \
  apt-get install -y --no-install-recommends ca-certificates && \
  rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/
RUN chmod +x /app/start.sh

ENV PORT=8000
EXPOSE 8000

ENV GROQ_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct

CMD ["/app/start.sh"]
