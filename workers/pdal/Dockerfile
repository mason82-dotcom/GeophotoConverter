FROM condaforge/miniforge3:26.7.2-0

ENV GEOPHOTO_DATA_ROOT=/data \
    GEOPHOTO_PDAL_TIMEOUT_SECONDS=120 \
    GEOPHOTO_PDAL_PORT=8090 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROJ_NETWORK=OFF

RUN conda create -y -n geophoto-pdal -c conda-forge \
        "python=3.13" \
        "pdal=2.10.2" \
    && conda clean --all --yes \
    && /opt/conda/envs/geophoto-pdal/bin/pdal --version 2>&1 | grep -q "2.10.2"

ENV PATH="/opt/conda/envs/geophoto-pdal/bin:${PATH}"

COPY workers/pdal/service.py /service/service.py

EXPOSE 8090
ENTRYPOINT ["/opt/conda/envs/geophoto-pdal/bin/python", "/service/service.py"]
