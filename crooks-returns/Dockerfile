# CROOKS Returns: one process, one SQLite file on a mounted volume at /data.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY returns ./returns
RUN pip install --no-cache-dir .
ENV RETURNS_DB_PATH=/data/returns.sqlite3 \
    RETURNS_ENV_FILE= \
    PORT=8100
RUN mkdir -p /data
EXPOSE 8100
# --proxy-headers: the host's load balancer terminates HTTPS in front of this.
CMD ["sh", "-c", "uvicorn returns.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
