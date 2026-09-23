ARG NVIDIA_CUDA_VERSION=12.8.1
ARG UBUNTU_VERSION=24.04
ARG COLMAP_VERSION=4.2.0
ARG COLMAP_COMMIT=be5e29168d4aff238409d60424812df66aac919f
ARG CUDA_ARCHITECTURES=all-major

FROM nvidia/cuda:${NVIDIA_CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION} AS colmap-builder

ARG COLMAP_VERSION
ARG COLMAP_COMMIT
ARG CUDA_ARCHITECTURES
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ccache \
        cmake \
        git \
        libboost-graph-dev \
        libboost-program-options-dev \
        libboost-system-dev \
        libcgal-dev \
        libceres-dev \
        libcurl4-openssl-dev \
        libeigen3-dev \
        libglew-dev \
        libgmock-dev \
        libgoogle-glog-dev \
        libgtest-dev \
        libmetis-dev \
        libmkl-full-dev \
        libopenimageio-dev \
        libqt6opengl6-dev \
        libqt6openglwidgets6 \
        libsqlite3-dev \
        libssl-dev \
        ninja-build \
        openimageio-tools \
        qt6-base-dev \
        qt6-svg-dev \
    && rm -rf /var/lib/apt/lists/*

# OpenImageIO's Ubuntu CMake config expects this include directory even though
# COLMAP does not use OpenCV through OpenImageIO.
RUN mkdir -p /usr/include/opencv4

RUN git clone --branch "${COLMAP_VERSION}" --depth 1 \
        https://github.com/colmap/colmap.git /src/colmap \
    && test "$(git -C /src/colmap rev-parse HEAD)" = "${COLMAP_COMMIT}"

RUN cmake -S /src/colmap -B /src/colmap/build -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES}" \
        -DCMAKE_INSTALL_PREFIX=/opt/colmap \
        -DBLA_VENDOR=Intel10_64lp \
    && cmake --build /src/colmap/build --target install --parallel 2

FROM nvidia/cuda:${NVIDIA_CUDA_VERSION}-cudnn-devel-ubuntu${UBUNTU_VERSION}

ARG GSPLAT_COMMIT=512d366b67073d77ca099ede742683c165dfc23b
ARG COLMAP_VERSION
ARG COLMAP_COMMIT

ENV DEBIAN_FRONTEND=noninteractive \
    GEOPHOTO_DATA_ROOT=/data \
    GEOPHOTO_REDIS_URL=redis://redis:6379/0 \
    GEOPHOTO_COLMAP_CUDA=1 \
    GEOPHOTO_COLMAP_VERSION=${COLMAP_VERSION} \
    GEOPHOTO_COLMAP_COMMIT=${COLMAP_COMMIT} \
    TORCH_EXTENSIONS_DIR=/root/.cache/torch_extensions \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        ffmpeg \
        git \
        libboost-program-options1.83.0 \
        libc6 \
        libceres4t64 \
        libcurl4 \
        libgcc-s1 \
        libgl1 \
        libglew2.2 \
        libglib2.0-0 \
        libgoogle-glog0v6t64 \
        libimage-exiftool-perl \
        libmetis5 \
        libmkl-core \
        libmkl-intel-lp64 \
        libmkl-intel-thread \
        libmkl-locale \
        libomp5 \
        libopenimageio2.4t64 \
        libopengl0 \
        libqt6core6 \
        libqt6gui6 \
        libqt6openglwidgets6 \
        libqt6svg6 \
        libqt6widgets6 \
        libraw-bin \
        libssl3t64 \
        ninja-build \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=colmap-builder /opt/colmap/ /usr/local/

RUN test "$(colmap -h | sed -n '1p' | grep -o 'COLMAP [0-9][^ ]*' | awk '{print $2}')" = "${COLMAP_VERSION}"

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
        pycolmap==4.2.0 \
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
        redis==6.4.0

RUN cd /opt/gsplat \
    && BUILD_NO_CUDA=1 BUILD_EXPERIMENTAL=0 pip install --no-cache-dir -e .

COPY workers/common /worker/common
COPY workers/gsplat/worker.py /worker/worker.py
COPY workers/gsplat/train.py /worker/train.py

WORKDIR /worker
ENTRYPOINT ["python3", "/worker/worker.py"]
