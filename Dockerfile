FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN python -m playwright install --with-deps chromium
RUN python -m spacy download en_core_web_sm

COPY . /app

# Single worker: job queue is in-memory (process-local), multiple workers cause
# job lookups to fail when request hits a different process. Use 1 worker until
# job persistence (Redis/SQLite) is implemented.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
