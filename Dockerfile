# Slim base plus Chromium only. The official Playwright image would work but
# ships Firefox and WebKit too, which triples the size for no benefit here.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    DATA_DIR=/data \
    WEB_PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/* /root/.cache

COPY cdnprobe/ ./cdnprobe/

# Measurements and the cached browser session live on a volume so history
# survives a rebuild - multi-day statistics are the entire point.
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/state',timeout=4)"

ENTRYPOINT ["python", "-m", "cdnprobe"]
CMD ["serve"]
