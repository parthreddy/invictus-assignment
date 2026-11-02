FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + data + bootstrap scripts.
COPY app ./app
COPY data ./data
COPY scripts ./scripts

# Command is set per-service in docker-compose (api / worker / migrate).
