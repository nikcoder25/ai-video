FROM python:3.11-slim

# ffmpeg does the work; fontconfig + a real font are what libass needs to burn
# captions. Without fonts-dejavu-core the ass filter silently renders nothing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        fontconfig \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Drop a Poppins .ttf into backend/fonts/ to match the house caption style;
# captions.pick_font falls back to DejaVu Sans when it is absent.
COPY fonts/ /usr/share/fonts/truetype/clipviral/
RUN fc-cache -f

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORK_DIR=/data/work \
    STORAGE_DIR=/data/clips \
    DATABASE_URL=sqlite:////data/clipviral.db

RUN mkdir -p /data/work /data/clips

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Single worker on purpose: renders are CPU-bound and serialised by a semaphore
# inside the process. More workers would multiply memory without adding throughput.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
