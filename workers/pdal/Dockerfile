FROM pdal/pdal:2.10.2

ENV GEOPHOTO_DATA_ROOT=/data \
    GEOPHOTO_PDAL_TIMEOUT_SECONDS=120 \
    GEOPHOTO_PDAL_PORT=8090 \
    PYTHONUNBUFFERED=1

COPY workers/pdal/service.py /service/service.py

RUN pdal --version 2>&1 | grep -q "2.10.2"

EXPOSE 8090
ENTRYPOINT ["/opt/conda/envs/pdal/bin/python", "/service/service.py"]
