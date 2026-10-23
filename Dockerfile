# syntax=docker/dockerfile:1

# --------------------------------------------------------------------------- #
# Frontend build
# --------------------------------------------------------------------------- #
FROM node:22-alpine AS frontend-build

WORKDIR /build/frontend

# Install dependencies from the lockfile first so this layer is cached.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# --------------------------------------------------------------------------- #
# Runtime
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

ARG PUID=1000
ARG PGID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NEWSARR_DATA_DIR=/data \
    NEWSARR_FRONTEND_DIR=/app/frontend/dist \
    NEWSARR_HOST=0.0.0.0 \
    NEWSARR_PORT=7878

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

RUN groupadd --gid "${PGID}" newsarr \
    && useradd --uid "${PUID}" --gid "${PGID}" --create-home newsarr \
    && mkdir -p /data \
    && chown -R newsarr:newsarr /app /data

USER newsarr
VOLUME ["/data"]
EXPOSE 7878

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('NEWSARR_PORT', '7878') + '/api/v1/health', timeout=4)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host \"${NEWSARR_HOST:-0.0.0.0}\" --port \"${NEWSARR_PORT:-7878}\""]
