FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # The embedding model is downloaded into the image at build time (see below),
    # so containers start without a ~90 MB download.
    HF_HOME=/opt/hf-cache \
    HF_HUB_OFFLINE=1 \
    CHROMA_PERSIST_DIR=/data/chroma \
    UPLOAD_DIR=/data/uploads \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model (ONNX export + tokenizer) into the image.
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN HF_HUB_OFFLINE=0 python -c "from huggingface_hub import snapshot_download; snapshot_download('${EMBEDDING_MODEL}', allow_patterns=['onnx/model.onnx', 'tokenizer.json', 'sentence_bert_config.json'])"

COPY . .

# Run as an unprivileged user (UID 1000, which Hugging Face Spaces also expects).
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser /data /app /opt/hf-cache
USER appuser

EXPOSE 8000

# Apply migrations, then start the API.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
