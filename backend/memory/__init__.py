"""Memory subsystem — five stores + MemoryBundle façade.

Production rule: agents / workflows only depend on the protocols and
``MemoryBundle``. Pick a concrete backend at wiring time (FastAPI
lifespan). Tests use :meth:`MemoryBundle.in_memory` for zero deps.
"""

from .base import (
    DocumentStore,
    EpisodicStore,
    HeuristicStore,
    KnowledgeStore,
    MemoryBundle,
    SessionStore,
    VectorStore,
    cosine,
    gen_id,
    keyword_score,
    stable_id,
)
from .chunker import Chunk, chunk_markdown
from .document_store import (
    InMemoryDocumentStore,
    YamlDocumentStore,
    heuristic_summary,
    make_chunk_id,
)
from .episodic_sql import SqlEpisodicStore
from .episodic_store import InMemoryEpisodicStore
from .factory import MemoryFactory, build_memory_bundle
from .heuristic_store import InMemoryHeuristicStore, YamlHeuristicStore
from .knowledge_store import InMemoryKnowledgeStore, YamlKnowledgeStore
from .models import (
    DocChunk,
    DocChunkHit,
    DocumentSourceKind,
    Heuristic,
    HeuristicDomain,
    HeuristicVerdict,
    KnowledgeDocument,
    LinkType,
    MemorySnapshot,
    PaperCard,
    Reflection,
    ReflectionType,
    SessionContext,
    SessionMessage,
    StrategyBlock,
    SynthesisNote,
    TypedLink,
    VectorHit,
)
from .paper_memory import EvolutionResult, PaperMemoryEvolver
from .session_redis import RedisSessionStore
from .session_store import InMemorySessionStore
from .vector_chroma import ChromaVectorStore
from .vector_store import InMemoryVectorStore

__all__ = [
    "ChromaVectorStore",
    "Chunk",
    "DocChunk",
    "DocChunkHit",
    "DocumentSourceKind",
    "DocumentStore",
    "EpisodicStore",
    "EvolutionResult",
    "Heuristic",
    "HeuristicDomain",
    "HeuristicStore",
    "HeuristicVerdict",
    "InMemoryDocumentStore",
    "InMemoryEpisodicStore",
    "InMemoryHeuristicStore",
    "InMemoryKnowledgeStore",
    "InMemorySessionStore",
    "InMemoryVectorStore",
    "KnowledgeDocument",
    "KnowledgeStore",
    "LinkType",
    "MemoryBundle",
    "MemoryFactory",
    "MemorySnapshot",
    "PaperCard",
    "PaperMemoryEvolver",
    "RedisSessionStore",
    "Reflection",
    "ReflectionType",
    "SessionContext",
    "SessionMessage",
    "SessionStore",
    "SqlEpisodicStore",
    "StrategyBlock",
    "SynthesisNote",
    "TypedLink",
    "VectorHit",
    "VectorStore",
    "YamlDocumentStore",
    "YamlHeuristicStore",
    "YamlKnowledgeStore",
    "build_memory_bundle",
    "chunk_markdown",
    "cosine",
    "gen_id",
    "heuristic_summary",
    "keyword_score",
    "make_chunk_id",
    "stable_id",
]
