FROM opendronemap/odm:3.6.2

USER root
RUN python3 -m pip install --no-cache-dir redis==6.4.0

COPY workers/common /worker/common
COPY workers/odm/worker.py /worker/worker.py

WORKDIR /worker
ENTRYPOINT ["python3", "/worker/worker.py"]
