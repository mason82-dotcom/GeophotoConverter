FROM pdal/pdal:2.10.2

WORKDIR /opt/geophoto-pdal
COPY services/pdal_qa/server.py /opt/geophoto-pdal/server.py

ENV PDAL_DATA_ROOT=/data \
    PDAL_QA_PORT=8080 \
    PDAL_QA_TIMEOUT_SECONDS=120

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()"]

CMD ["python", "/opt/geophoto-pdal/server.py"]
