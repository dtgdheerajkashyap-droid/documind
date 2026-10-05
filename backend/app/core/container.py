"""Composition root: wires settings, database, providers and services together.

Tests build their own container with fake providers and pass it to `create_app`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.rate_limit import SlidingWindowRateLimiter
from app.db.session import create_db_engine, create_session_factory
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.factory import build_embeddings, build_llm, build_vector_store
from app.providers.llm.base import LLMProvider
from app.providers.vectorstore.base import VectorStore
from app.services.chat_service import ChatService
from app.services.ingestion import IngestionService
from app.services.retrieval import Retriever


@dataclass
class AppContainer:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    embedder: EmbeddingProvider
    vector_store: VectorStore
    llm: LLMProvider
    chat_rate_limiter: SlidingWindowRateLimiter = field(init=False)

    def __post_init__(self) -> None:
        self.chat_rate_limiter = SlidingWindowRateLimiter(self.settings.chat_rate_limit_per_minute)

    @property
    def retriever(self) -> Retriever:
        return Retriever(self.embedder, self.vector_store)

    @property
    def ingestion(self) -> IngestionService:
        return IngestionService(
            self.settings, self.session_factory, self.embedder, self.vector_store
        )

    @property
    def chat_service(self) -> ChatService:
        return ChatService(self.settings, self.session_factory, self.retriever, self.llm)


def build_container(settings: Settings) -> AppContainer:
    engine = create_db_engine(settings.database_url)
    return AppContainer(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        embedder=build_embeddings(settings),
        vector_store=build_vector_store(settings),
        llm=build_llm(settings),
    )
