FROM python:3.12-slim-bookworm@sha256:5d9e6adc9abd558bc0ce05f9ab16cef71328916fc9728f6b81e337af86a737e2

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MAX_ADDRESS_SPACE_MB=768

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system app && adduser --system --ingroup app app
RUN mkdir -p /app/data && chown -R app:app /app

COPY --chown=app:app src ./src
COPY --chown=app:app frontend/index.html frontend/sample.html frontend/styles.css frontend/app.js frontend/workspace.css frontend/workspace.js ./frontend/
COPY --chown=app:app frontend/examples ./frontend/examples/

EXPOSE 8000

USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready', timeout=3)"]

CMD ["python", "-m", "src.server"]
