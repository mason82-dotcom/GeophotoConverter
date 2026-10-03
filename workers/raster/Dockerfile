FROM python:3.12.14-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GEOPHOTO_DATA_ROOT=/data \
    HOME=/tmp

RUN pip install --no-cache-dir \
    numpy==2.5.3 \
    rasterio==1.5.1 \
    redis==7.4.1

COPY backend/app/__init__.py backend/app/photogrammetry_multispectral.py /worker/app/
COPY workers/common /worker/common
COPY workers/raster/worker.py /worker/worker.py

WORKDIR /worker
ENTRYPOINT ["python", "/worker/worker.py"]

FROM base AS cpu

FROM base AS cuda
RUN pip install --no-cache-dir cupy-cuda12x==14.2.0
