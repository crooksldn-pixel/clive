# CLIVE Shipping: one process, one SQLite file on a mounted volume at /data.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY shipping ./shipping
RUN pip install --no-cache-dir .
ENV SHIPPING_DB_PATH=/data/shipping.sqlite3 \
    SHIPPING_ENV_FILE= \
    PORT=8120
RUN mkdir -p /data
EXPOSE 8120
# --proxy-headers: Caddy terminates HTTPS in front of this.
CMD ["sh", "-c", "uvicorn shipping.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
