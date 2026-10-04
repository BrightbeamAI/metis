# The Metis server image: `metis server run` on port 8000, as a non-root user.
# Build:  docker build -t metis-server .
# Run:    docker run -p 8000:8000 -e METIS_API_KEYS_FILE=/config/api-keys.yaml metis-server

FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README_PYPI.md LICENSE ./
COPY metis ./metis
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[server,postgres]"

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    METIS_DATABASE_URL=sqlite:////data/metis.db \
    METIS_REPO=/opt/metis
RUN useradd --create-home --uid 10001 metis \
    && mkdir -p /data /config \
    && chown metis:metis /data /config
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
# The category-specific whisper wording and the local-model prompt templates.
COPY prompts /opt/metis/prompts
USER 10001
WORKDIR /home/metis
VOLUME ["/data", "/config"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
ENTRYPOINT ["metis", "server"]
CMD ["run", "--host", "0.0.0.0", "--port", "8000"]
