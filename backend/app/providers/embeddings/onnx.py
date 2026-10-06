"""Local embeddings with ONNX Runtime: the same sentence-transformers model, without PyTorch.

PyTorch alone needs ~400 MB of RAM. ONNX Runtime and the Hugging Face tokenizer
(both already required by ChromaDB) run all-MiniLM-L6-v2 in a fraction of that,
which lets the API fit on small (512 MB) hosts. Vectors match the
sentence-transformers pipeline: mean pooling over tokens, then L2 normalisation.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from app.providers.embeddings.base import EmbeddingProvider

if TYPE_CHECKING:
    import onnxruntime
    from tokenizers import Tokenizer

logger = logging.getLogger(__name__)

DEFAULT_MAX_SEQ_LENGTH = 256


class OnnxEmbeddings(EmbeddingProvider):
    """Runs the ONNX export shipped in a sentence-transformers model repo, loaded lazily."""

    def __init__(self, model_name: str, batch_size: int = 32, threads: int = 0) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._threads = threads
        self._session: onnxruntime.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> tuple[onnxruntime.InferenceSession, Tokenizer]:
        if self._session is None or self._tokenizer is None:
            with self._lock:
                if self._session is None or self._tokenizer is None:
                    import onnxruntime
                    from huggingface_hub import snapshot_download
                    from tokenizers import Tokenizer

                    logger.info("Loading embedding model", extra={"model": self._model_name})
                    root = Path(
                        snapshot_download(
                            self._model_name,
                            allow_patterns=[
                                "onnx/model.onnx",
                                "tokenizer.json",
                                "sentence_bert_config.json",
                            ],
                        )
                    )
                    max_length = DEFAULT_MAX_SEQ_LENGTH
                    config_file = root / "sentence_bert_config.json"
                    if config_file.exists():
                        config = json.loads(config_file.read_text(encoding="utf-8"))
                        max_length = config.get("max_seq_length", max_length)

                    tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
                    tokenizer.enable_truncation(max_length=max_length)
                    tokenizer.enable_padding()

                    options = onnxruntime.SessionOptions()
                    # Free activation buffers after each batch instead of keeping a
                    # growing arena; this caps peak RAM at a small cost in speed.
                    options.enable_cpu_mem_arena = False
                    if self._threads > 0:
                        options.intra_op_num_threads = self._threads
                        options.inter_op_num_threads = 1
                    self._session = onnxruntime.InferenceSession(
                        str(root / "onnx" / "model.onnx"),
                        sess_options=options,
                        providers=["CPUExecutionProvider"],
                    )
                    self._tokenizer = tokenizer
        return self._session, self._tokenizer

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import numpy as np

        session, tokenizer = self._load()
        input_names = {i.name for i in session.get_inputs()}
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            encodings = tokenizer.encode_batch(texts[start : start + self._batch_size])
            mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            feeds = {
                "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
                "attention_mask": mask,
                "token_type_ids": np.array([e.type_ids for e in encodings], dtype=np.int64),
            }
            token_embeddings = session.run(
                None, {k: v for k, v in feeds.items() if k in input_names}
            )[0]
            weights = mask[:, :, None].astype(np.float32)
            pooled = (token_embeddings * weights).sum(axis=1) / np.clip(
                weights.sum(axis=1), 1e-9, None
            )
            pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
            vectors.extend(pooled.tolist())
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text])[0]
