# syntax=docker/dockerfile:1
# Сборка из корня репозитория: docker build -f deploy/Dockerfile -t design-studio .

# --- Этап 1: фронтенд (Node 20) ---
FROM node:20-slim AS frontend
WORKDIR /src
# До T03 каталога frontend/ нет: тогда собираем пустой dist, чтобы образ всё равно собирался.
RUN --mount=type=bind,source=.,target=/ctx \
    if [ -f /ctx/frontend/package.json ]; then cp -r /ctx/frontend /src/frontend; fi
RUN if [ -f frontend/package.json ]; then \
        cd frontend \
        && if [ -f package-lock.json ]; then npm ci; else npm install; fi \
        && npm run build; \
    else mkdir -p frontend/dist; fi

# --- Этап 2: бэкенд (Python 3.12 slim) ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    MODELS_FILE=/app/models.json \
    FRONTEND_DIST=/app/frontend/dist

WORKDIR /app/backend
# Сначала только зависимости из pyproject.toml: слой переиспользуется, пока они не меняются.
COPY backend/pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
    && pip install -r /tmp/req.txt \
    && rm /tmp/req.txt

# Раскладка как в репозитории: /app/backend, /app/models.json, /app/frontend/dist.
COPY models.json /app/models.json
COPY backend/app ./app
COPY --from=frontend /src/frontend/dist /app/frontend/dist

# Пользователь без root; UID фиксирован, чтобы права на томе не менялись между образами.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home app \
    && mkdir -p /data && chown app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Ровно один процесс: очередь генераций, семафор MAX_PARALLEL и счётчик попыток входа
# живут в памяти процесса. С --workers 2+ лимиты делятся на процессы и перестают работать.
# --no-proxy-headers: X-Forwarded-For разбирает само приложение и только от TRUSTED_PROXIES.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
