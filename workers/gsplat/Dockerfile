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

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir \
        torch==2.9.1 \
        torchvision==0.24.1 \
        --index-url https://download.pytorch.org/whl/cu128

RUN git clone https://github.com/nerfstudio-project/gsplat.git /opt/gsplat \
    && cd /opt/gsplat \
    && git checkout "${GSPLAT_COMMIT}" \
    && test "$(git rev-parse HEAD)" = "${GSPLAT_COMMIT}"

RUN pip install --no-cache-dir \
        "pycolmap>=3.10.0" \
        "viser" \
        "git+https://github.com/nerfstudio-project/nerfview@4538024fe0d15fd1a0e4d760f3695fc44ca72787" \
        "imageio[ffmpeg]" \
        "numpy>=2.0,<3.0" \
        scipy \
        scikit-learn \
        tqdm \
        torchmetrics==1.8.2 \
        opencv-python-headless \
        "tyro>=0.8.8,!=1.0.9,!=1.0.10" \
        Pillow \
        piexif \
        tensorboard \
        tensorly \
        pyyaml \
        matplotlib \
        splines \
        redis==7.4.1

RUN cd /opt/gsplat \
    && BUILD_NO_CUDA=1 BUILD_EXPERIMENTAL=0 pip install --no-cache-dir -e .

COPY workers/common /worker/common
COPY workers/gsplat/worker.py /worker/worker.py
COPY workers/gsplat/train.py /worker/train.py

WORKDIR /worker
ENTRYPOINT ["python3", "/worker/worker.py"]
