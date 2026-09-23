FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04

ARG GSPLAT_COMMIT=512d366b67073d77ca099ede742683c165dfc23b

ENV DEBIAN_FRONTEND=noninteractive \
    GEOPHOTO_DATA_ROOT=/data \
    GEOPHOTO_REDIS_URL=redis://redis:6379/0 \
    TORCH_EXTENSIONS_DIR=/root/.cache/torch_extensions \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        colmap \
        ffmpeg \
        git \
        libgl1 \
        libglib2.0-0 \
        libimage-exiftool-perl \
        libraw-bin \
        ninja-build \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

RUN pip install --no-cache-dir \
        pip==26.2.1 \
        setuptools==84.0.0 \
        wheel==0.48.0 \
    && pip install --no-cache-dir \
        torch==2.9.1 \
        torchvision==0.24.1 \
        --index-url https://download.pytorch.org/whl/cu128

RUN git clone https://github.com/nerfstudio-project/gsplat.git /opt/gsplat \
    && cd /opt/gsplat \
    && git checkout "${GSPLAT_COMMIT}" \
    && test "$(git rev-parse HEAD)" = "${GSPLAT_COMMIT}"

COPY workers/gsplat/requirements.txt /tmp/gsplat-requirements.txt
RUN pip install --no-cache-dir -r /tmp/gsplat-requirements.txt

RUN cd /opt/gsplat \
    && BUILD_NO_CUDA=1 BUILD_EXPERIMENTAL=0 pip install --no-cache-dir -e .

COPY workers/common /worker/common
COPY workers/gsplat/worker.py /worker/worker.py
COPY workers/gsplat/train.py /worker/train.py

WORKDIR /worker
ENTRYPOINT ["python3", "/worker/worker.py"]
