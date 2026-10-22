FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libmariadb-dev pkg-config && rm -rf /var/lib/apt/lists/*
COPY requirements*.txt requirements.lock ./
RUN pip wheel --wheel-dir /wheels -r requirements.lock

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_CONFIG=production
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libmariadb3 && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home app
COPY --from=builder /wheels /wheels
COPY requirements*.txt requirements.lock ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.lock && rm -rf /wheels
COPY --chown=app:app . .
RUN chmod 755 /app/entrypoint.sh
RUN python -c "from app.utils.connector_security import verify_native_connector; print('Patched MariaDB Connector/C:', verify_native_connector())"
USER app
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health/ready', timeout=3)"
ENTRYPOINT ["/app/entrypoint.sh"]
