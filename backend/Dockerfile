FROM python:3.12-slim

WORKDIR /app

# System deps for curl_cffi
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libcurl4-openssl-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir playwright && \
    echo "Skipping browser download — only Fetcher/curl_cffi is used"

COPY . .

# Container runtime port (default 8080)
ENV PORT=8080
ENV PLAYWRIGHT_BROWSERS_PATH=0

EXPOSE ${PORT}

CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT}
