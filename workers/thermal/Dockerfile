FROM python:3.12-slim

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
    "numpy>=2.0,<3" \
    "Pillow>=11,<14" \
    "tifffile>=2025.5,<2027" \
    redis==7.4.1

COPY workers/common /worker/common
COPY workers/thermal/thermal_core /worker/thermal_core
COPY workers/thermal/worker.py /worker/worker.py

ENTRYPOINT ["python", "/worker/worker.py"]
