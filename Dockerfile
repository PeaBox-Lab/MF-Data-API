FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MFDATA_DATA_DIR=/data \
    MFDATA_AUTO_SYNC=1 \
    MFDATA_BOOTSTRAP_DAYS=365

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY pipeline ./pipeline
COPY web ./web
COPY scripts ./scripts
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /data

VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["entrypoint.sh"]
