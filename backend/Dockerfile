FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDIA_ROOT=/data/media \
    PRIVATE_MEDIA_ROOT=/data/private \
    STATIC_ROOT=/data/static

# Take Debian security fixes published after the base image was built.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# pip is needed only to install. It is removed afterwards so that the libraries bundled inside it
# are not part of the running image.
RUN pip install -r requirements.txt \
    && pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip/_bundled

COPY . .

# Run as an unprivileged user. The data directories are created here so named volumes inherit their owner.
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir -p /data/media /data/private /data/static \
    && chown -R app:app /data
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
