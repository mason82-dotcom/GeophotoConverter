FROM opendronemap/odm:3.6.2

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends libraw-bin libimage-exiftool-perl \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --no-cache-dir redis==7.4.1

COPY workers/common /worker/common
COPY workers/odm/worker.py /worker/worker.py

WORKDIR /worker
ENTRYPOINT ["python3", "/worker/worker.py"]
