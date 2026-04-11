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

# Replace certifi's bundled CA with the Debian system bundle. Modern
# Cloudflare-fronted sites (incl. example.com) chain through SSL.com /
# Comodo / Sectigo roots that the upstream certifi bundle no longer
# carries, so requests.get() fails with CERTIFICATE_VERIFY_FAILED unless
# we let it use the same trust anchors as the OS.
RUN cp /etc/ssl/certs/ca-certificates.crt \
    /usr/local/lib/python3.11/site-packages/certifi/cacert.pem

RUN python -m playwright install --with-deps chromium
RUN python -m spacy download en_core_web_sm

COPY . /app

# Register the package metadata so importlib.metadata.version("geo-checker")
# can read the pyproject.toml version at runtime. Without this, the editable
# install step is missing and /api/v1/health would report "0.0.0-unknown".
RUN pip install --no-cache-dir --no-deps -e .

# Single worker: job queue is in-memory (process-local), multiple workers cause
# job lookups to fail when request hits a different process. Use 1 worker until
# job persistence (Redis/SQLite) is implemented.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
