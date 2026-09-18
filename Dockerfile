# Multi-stage build: slim runtime image, non-root user, health check.
# Base image is pinned to a patch release (no floating minor tag). Re-pin to a
# digest at release time (`docker buildx imagetools inspect`) for immutability.
FROM python:3.12.7-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12.7-slim AS runtime
# No credentialed MERIDIAN_DATABASE_URL default here: secrets must arrive via
# the environment (compose / k8s Secret), never baked into an image layer.
ENV PYTHONUNBUFFERED=1 \
    MERIDIAN_ENVIRONMENT=production \
    MERIDIAN_DATA_DIR=/app/data
WORKDIR /app
COPY --from=builder /install /usr/local
COPY data/ data/
COPY web/ web/
RUN useradd --create-home --uid 10001 meridian \
    && mkdir -p /app/data \
    && chown -R meridian:meridian /app
USER meridian
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "meridian.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
