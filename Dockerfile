# Isnad database service — runtime image
# Python version is pinned explicitly so it does not change on Railway rebuilds.
FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Fallback OCR engine (scans are read by a vision model on OpenRouter; Tesseract takes over
# when it can't be reached), and an Arabic font for PDF reports (Noto Naskh Arabic)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Arabic OCR model from tessdata_best: noticeably more accurate on printed Arabic books than
# Debian's "fast" model (about 2x slower per page). TESSDATA_PREFIX points Tesseract at it.
ENV TESSDATA_PREFIX=/usr/local/share/tessdata
RUN mkdir -p "$TESSDATA_PREFIX" \
    && python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/tesseract-ocr/tessdata_best/raw/main/ara.traineddata', '$TESSDATA_PREFIX/ara.traineddata')" \
    && python -c "import os; assert os.path.getsize('$TESSDATA_PREFIX/ara.traineddata') > 1_000_000, 'Arabic OCR model download failed'"

# Dependencies get their own layer so the cache is reused unless requirements.txt changes.
# No PyTorch / local model: embeddings come from the OpenRouter API.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# The service runs as root on purpose: Railway mounts Volumes owned by root, and the service
# must write to /app/chroma_db. (The website, which has no Volume, runs as a normal user.)
# Deployment note: mount a Volume at /app/chroma_db on Railway. It holds the vector
# database, the app database (accounts, stats) and the uploaded originals —
# without it all of them are lost on every redeploy.
EXPOSE 8000

# --proxy-headers: trust Railway's proxy so the login rate limit sees the real client IP
# and login cookies are marked Secure over HTTPS.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
