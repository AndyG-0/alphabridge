FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
# OCR for scanned statements (optional: the LLM vision fallback works without it)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Run as an unprivileged user; /app/data is the only writable path
RUN useradd --system --uid 10001 --home /app app && mkdir -p /app/data && chown -R app /app/data
USER app
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:5000/api/health', timeout=4)" || exit 1
# One worker: the in-process scheduler must not be duplicated. Scale with threads.
CMD ["sh", "-c", "alembic upgrade head && gunicorn -w 1 --threads 8 --no-control-socket -b 0.0.0.0:5000 wsgi:app"]
