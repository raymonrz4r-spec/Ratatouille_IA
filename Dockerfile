# ============================================================================
# RATATOUILLE AI - DOCKERFILE (RENDER / HUGGING FACE / KOYEB - COSTO $0)
# ============================================================================
FROM python:3.11-slim

# Evitar archivos .pyc y habilitar logs en tiempo real
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    TEMP_ROOT=/tmp/ratatouille_tmp

# Instalar FFmpeg y certificados del sistema para yt-dlp
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario no-root con UID 1000
RUN useradd -m -u 1000 user

WORKDIR /app

# Instalar dependencias de Python primero para aprovechar caché de capas Docker
COPY --chown=user:user backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r ./backend/requirements.txt

# Copiar el código del backend
COPY --chown=user:user backend ./backend

# Asegurar permisos sobre carpetas temporales y estáticas
RUN mkdir -p /tmp/ratatouille_tmp /app/backend/static/images && \
    chown -R user:user /tmp/ratatouille_tmp /app/backend

USER user
EXPOSE 7860 10000 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
