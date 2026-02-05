FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN python -m playwright install --with-deps chromium
RUN python -m spacy download en_core_web_sm

COPY . /app

# 2 workers for 1 CPU (I/O bound task can benefit from slight over-provisioning)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
