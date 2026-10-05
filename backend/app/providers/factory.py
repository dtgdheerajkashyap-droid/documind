"""Builds concrete providers from settings. The only place that knows about implementations."""

from __future__ import annotations

from app.core.config import Settings
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.providers.vectorstore.base import VectorStore


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "ollama":
        from app.providers.llm.ollama import OllamaProvider

        return OllamaProvider(
            settings.ollama_base_url,
            settings.ollama_model,
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    from app.providers.llm.gemini import GeminiProvider

    return GeminiProvider(
        settings.gemini_api_key,
        settings.gemini_model,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        thinking_budget=settings.gemini_thinking_budget,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def build_embeddings(settings: Settings) -> EmbeddingProvider:
    from app.providers.embeddings.sentence_transformer import SentenceTransformerEmbeddings

    return SentenceTransformerEmbeddings(
        settings.embedding_model,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
    )


def build_vector_store(settings: Settings) -> VectorStore:
    from app.providers.vectorstore.chroma import ChromaVectorStore

    return ChromaVectorStore(settings.chroma_persist_dir, settings.chroma_collection)
