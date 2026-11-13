FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDIA_ROOT=/data/media \
    PRIVATE_MEDIA_ROOT=/data/private \
    STATIC_ROOT=/data/static

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user. The data directories are created here so named volumes inherit their owner.
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir -p /data/media /data/private /data/static \
    && chown -R app:app /data
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
