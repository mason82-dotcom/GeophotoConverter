FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GEOPHOTO_DATA_ROOT=/data \
    GEOPHOTO_REDIS_URL=redis://redis:6379/0 \
    DJI_TSDK_DIR=/opt/dji-tsdk

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgomp1 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /worker
RUN python -m pip install --no-cache-dir \
    numpy==2.5.3 \
    Pillow==12.3.0 \
    tifffile==2026.9.20 \
    redis==7.4.1

COPY workers/common /worker/common
COPY workers/thermal/thermal_core /worker/thermal_core
COPY workers/thermal/worker.py /worker/worker.py

ENTRYPOINT ["python", "/worker/worker.py"]
