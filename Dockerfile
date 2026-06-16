# PartnerPulse nightly pipeline — Cloud Run Job image.
# Runs scripts/cloud_sync.py: pull transcripts → build_all → build_real_partners
# → reindex → build_overview → upload_firebase_data, with optional GCS state.
FROM python:3.12-slim

# markitdown's deps are pure-Python (pdfminer/python-docx/python-pptx); no system
# packages needed. Keep the image lean.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install deps first for layer caching. google-cloud-firestore (Firestore publish)
# and google-cloud-storage (state sync) are not in requirements.txt (they're
# cloud-only), so add them here.
COPY requirements.txt .
RUN pip install -r requirements.txt google-cloud-firestore google-cloud-storage

# App code (.dockerignore keeps out data/, Transcripts/, .env, .git, frontend).
COPY . .

ENTRYPOINT ["python", "scripts/cloud_sync.py"]
