# CLIVE Preorders: one process, one SQLite file on a mounted volume at /data.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY preorders ./preorders
RUN pip install --no-cache-dir .
ENV PREORDERS_DB_PATH=/data/preorders.sqlite3 \
    PREORDERS_ENV_FILE= \
    PORT=8130
RUN mkdir -p /data
EXPOSE 8130
# --proxy-headers: Caddy terminates HTTPS in front of this.
CMD ["sh", "-c", "uvicorn preorders.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
