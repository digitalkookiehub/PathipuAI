# PathippuAI: one image with the API, the built React app, Tesseract (Tamil) and the bundled fonts.
#
#   docker build -t pathippuai .                              # fast Tesseract reading only
#   docker build --build-arg INSTALL_CAREFUL=true -t pathippuai .   # also the slower, more accurate "careful" method

# --- 1. build the React app ---------------------------------------------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. the application -------------------------------------------------------------------------------------------
FROM python:3.11-slim AS app
ARG INSTALL_CAREFUL=false

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/pathippu \
    DATA_DIR=/data \
    DATABASE_PATH=/data/pathippuai.db \
    TESSDATA_DIR=/opt/tessdata \
    TESSERACT_CMD=tesseract \
    TRUST_PROXY=true \
    COOKIE_SECURE=true

# Tesseract plus the "best" Tamil and English language data (more accurate than the packaged "fast" data).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/tessdata \
    && curl -fsSL -o /opt/tessdata/tam.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/tam.traineddata \
    && curl -fsSL -o /opt/tessdata/eng.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata

WORKDIR /app
COPY requirements.txt requirements-ocr-tamil.txt ./
RUN pip install -r requirements.txt
# The careful method pulls in torch; the CPU-only build is much smaller than the default one.
RUN if [ "$INSTALL_CAREFUL" = "true" ]; then \
        pip install torch --index-url https://download.pytorch.org/whl/cpu \
        && pip install -r requirements-ocr-tamil.txt; \
    fi

COPY app ./app
COPY scripts ./scripts
COPY --from=frontend /build/dist ./frontend/dist

# Run as an ordinary user. /data holds the database and every book; /home/pathippu holds downloaded model files.
RUN useradd --system --uid 10001 --create-home --home-dir /home/pathippu pathippu \
    && mkdir -p /data \
    && chown -R pathippu:pathippu /data /home/pathippu
USER pathippu
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health/ready || exit 1

# One process on purpose: background jobs and the login throttle live in memory.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
