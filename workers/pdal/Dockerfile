FROM condaforge/miniforge3:26.7.2-0

ENV GEOPHOTO_DATA_ROOT=/data \
    GEOPHOTO_PDAL_TIMEOUT_SECONDS=120 \
    GEOPHOTO_PDAL_PORT=8090 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROJ_NETWORK=OFF \
    PATH=/opt/conda/envs/pdal/bin:$PATH

RUN mamba create -y -n pdal -c conda-forge \
        "python=3.13" \
        "pdal=2.10.2" \
    && /opt/conda/envs/pdal/bin/pdal --version 2>&1 | grep -q "2.10.2" \
    && mamba clean --all --yes

COPY workers/pdal/service.py /service/service.py

EXPOSE 8090
ENTRYPOINT ["/opt/conda/envs/pdal/bin/python", "/service/service.py"]
