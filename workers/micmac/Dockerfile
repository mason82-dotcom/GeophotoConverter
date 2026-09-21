FROM ubuntu:24.04

ARG MICMAC_VERSION=1.2.0
ARG MICMAC_SHA256=84c1b48dd4f7b4e099a40d034d08afbebd4837ea61526ecae370304e8d5153c5

ENV DEBIAN_FRONTEND=noninteractive \
    GEOPHOTO_DATA_ROOT=/data \
    PATH=/opt/venv/bin:/opt/micmac/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        exiv2 \
        imagemagick \
        libgl1 \
        libimage-exiftool-perl \
        libraw-bin \
        libx11-6 \
        proj-bin \
        python3 \
        python3-venv \
        qtbase5-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fL \
      "https://github.com/micmacIGN/micmac/releases/download/v${MICMAC_VERSION}/micmac_linux.tgz" \
      -o /tmp/micmac_linux.tgz \
    && echo "${MICMAC_SHA256}  /tmp/micmac_linux.tgz" | sha256sum -c - \
    && mkdir -p /opt/micmac \
    && tar -xzf /tmp/micmac_linux.tgz --strip-components=1 -C /opt/micmac \
    && rm /tmp/micmac_linux.tgz \
    && test -x /opt/micmac/bin/mm3d

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir redis==6.4.0

COPY workers/common /worker/common
COPY workers/micmac/worker.py /worker/worker.py

WORKDIR /worker
ENTRYPOINT ["python3", "/worker/worker.py"]
