FROM python:3.11-slim

WORKDIR /app

# Refresh CA certificates so httpx/requests can verify modern TLS chains
# (e.g. Let's Encrypt ISRG Root rotations). Slim base images ship with
# stale CA bundles that cause CERTIFICATE_VERIFY_FAILED on common HTTPS
# targets such as example.com.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && apt-get upgrade -y ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir --upgrade certifi
RUN python -m playwright install --with-deps chromium
RUN python -m spacy download en_core_web_sm

COPY . /app

# Single worker: job queue is in-memory (process-local), multiple workers cause
# job lookups to fail when request hits a different process. Use 1 worker until
# job persistence (Redis/SQLite) is implemented.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
