"""Local embeddings with sentence-transformers (no API key required)."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from app.providers.embeddings.base import EmbeddingProvider

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class SentenceTransformerEmbeddings(EmbeddingProvider):
    """Wraps a sentence-transformers model, loaded lazily on first use.

    Lazy loading keeps API start-up fast; the model (~90 MB for all-MiniLM-L6-v2)
    is downloaded to the Hugging Face cache the first time it is needed.
    """

    def __init__(self, model_name: str, device: str = "cpu", batch_size: int = 32) -> None:
        self._model_name = model_name
        self._device = device
        self._batch_size = batch_size
        self._model: SentenceTransformer | None = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    logger.info("Loading embedding model", extra={"model": self._model_name})
                    self._model = SentenceTransformer(self._model_name, device=self._device)
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._get_model().encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text])[0]
