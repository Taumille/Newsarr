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
    NEWSARR_DATA_DIR=/etc/newsarr \
    NEWSARR_FRONTEND_DIR=/app/frontend/dist \
    NEWSARR_HOST=0.0.0.0 \
    NEWSARR_PORT=7878

WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

# gosu lets the entrypoint repair data-directory ownership as root and then
# drop to the unprivileged `newsarr` user before starting the app.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${PGID}" newsarr \
    && useradd --uid "${PUID}" --gid "${PGID}" --create-home newsarr \
    && mkdir -p /etc/newsarr \
    && chown -R newsarr:newsarr /app /etc/newsarr

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/newsarr-entrypoint

VOLUME ["/etc/newsarr"]
EXPOSE 7878

ENTRYPOINT ["newsarr-entrypoint"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('NEWSARR_PORT', '7878') + '/api/v1/health', timeout=4)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host \"${NEWSARR_HOST:-0.0.0.0}\" --port \"${NEWSARR_PORT:-7878}\""]
