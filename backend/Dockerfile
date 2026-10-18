# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Keep the bge-m3 Hugging Face cache inside the image (pre-downloaded below).
    HF_HOME=/opt/hf \
    # Chroma persist dir; mount a volume here to survive redeploys.
    RAG_CHROMA_DIR=/app/data/chroma \
    # Railway injects PORT; 43124 matches docker-compose for local builds.
    PORT=43124

WORKDIR /app

COPY requirements.txt .
# requirements.txt pins torch from the PyTorch CPU index — no CUDA in the image.
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download BAAI/bge-m3 (~2 GB, model + tokenizer) so first boot does not
# fetch it over the network. Runtime RAM: budget ~2 GB for the model.
RUN python -c "from sentence_transformers import SentenceTransformer; from transformers import AutoTokenizer; SentenceTransformer('BAAI/bge-m3', device='cpu'); AutoTokenizer.from_pretrained('BAAI/bge-m3')"

COPY app ./app
COPY tests ./tests

# OPTIONAL — bake the regulation PDFs into the image so first boot can build
# the vector library without a mounted volume:
#   1. copy the PDFs into backend/data/regulations/ (git-ignored; sources in
#      data/SOURCES.md), 2. uncomment the two lines below, 3. rebuild.
# COPY data/regulations /app/data/regulations
# ENV REGULATIONS_DIR=/app/data/regulations
# To ingest during the build instead of on first boot, also uncomment:
# RUN python -m app.rag.bootstrap

EXPOSE 43124
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
