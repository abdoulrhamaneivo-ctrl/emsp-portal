# Contexte de build : racine `emsp-portal/`
#   docker build -f backend/Dockerfile -t emsp-portal .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DOCUMENT_STORAGE_ROOT=/app/backend/storage

WORKDIR /app

# Dépendances d'abord (cache Docker)
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

# Code backend + frontend statique (servi en `/` par main.py)
COPY backend ./backend
COPY frontend ./frontend
COPY Photos ./Photos

RUN mkdir -p /app/backend/storage \
    && useradd -m -u 10001 agent_emsp \
    && chown -R agent_emsp:agent_emsp /app

VOLUME ["/app/backend/storage"]

EXPOSE 10000

ENTRYPOINT ["python", "/app/backend/docker_entrypoint.py"]
