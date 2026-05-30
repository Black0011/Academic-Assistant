"""Application-wide configuration loaded from environment variables.

All AAF modules that need config read it from `get_settings()` — never from
`os.environ` directly. Settings are validated at app startup and cached.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseSettings):
    """One LLM provider's configuration.

    Populated from environment variables per-provider, e.g.:
        OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_DEFAULT_MODEL
    """

    api_key: str = ""
    base_url: str = ""
    default_model: str = ""
    timeout_s: int = 120
    verify_ssl: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["development", "production", "test"] = Field("development", alias="aaf_env")
    workdir: Path = Field(Path("./data"), alias="aaf_workdir")
    log_level: str = Field("INFO", alias="aaf_log_level")
    secret_key: str = Field("change-me", alias="aaf_secret_key")

    # When `auth_disabled` is true (default), every request is treated as
    # an anonymous local user — this keeps zero-config local dev painless.
    # Flip it to false in production AND set a strong `secret_key`.
    auth_disabled: bool = True
    auth_allow_signup: bool = False
    jwt_expire_seconds: int = 86400
    users_dir: Path = Path("./data/users")

    database_url: str = "sqlite+aiosqlite:///./data/aaf.db"
    redis_url: str = "redis://localhost:6379/0"
    chroma_persist_dir: Path = Path("./data/chroma")

    # Memory backends. "auto" picks a sensible backend per store based on
    # whether credentials / URLs are configured; explicit values ("memory",
    # "yaml", "chroma", "sql", "redis") override the heuristic.
    memory_vector_backend: Literal["auto", "memory", "chroma"] = "auto"
    memory_knowledge_backend: Literal["auto", "memory", "yaml"] = "auto"
    memory_heuristic_backend: Literal["auto", "memory", "yaml"] = "auto"
    memory_episodic_backend: Literal["auto", "memory", "sql"] = "auto"
    memory_session_backend: Literal["auto", "memory", "redis"] = "auto"
    # M7.3 — DocumentStore for free-form RAG over uploaded blobs.
    memory_documents_backend: Literal["auto", "memory", "yaml"] = "auto"
    memory_knowledge_dir: Path = Path("./data/knowledge")
    memory_skills_dir: Path = Path("./data/skills")
    memory_documents_dir: Path = Path("./data/documents")
    memory_collection: str = "aaf_memory"

    # M8.1 — gated proposals subsystem.
    proposals_backend: Literal["auto", "memory", "yaml"] = Field(
        "auto", alias="aaf_proposals_backend"
    )
    proposals_dir: Path = Field(Path("./data/proposals"), alias="aaf_proposals_dir")

    # M8.2 — Planner DAG (compile / validate / execute).
    planner_default_max_nodes: int = Field(30, alias="aaf_planner_default_max_nodes")
    planner_default_retry: int = Field(1, alias="aaf_planner_default_retry")
    planner_max_parallel: int = Field(4, alias="aaf_planner_max_parallel")

    default_llm_provider: str = "openai"
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"

    # Embedding backend selection. ``provider`` (default) reuses the chat
    # LLM's ``embed()``; ``local`` swaps in a sentence-transformers model
    # so the vector store + skill matcher can run fully offline. ``local``
    # requires the optional ``offline`` extra (`uv sync --extra offline`).
    # See backend/core/llm/local_embedder.py.
    embedding_backend: Literal["provider", "local"] = Field(
        "provider", alias="aaf_embedding_backend"
    )
    local_embedding_model: str = Field("BAAI/bge-small-en-v1.5", alias="aaf_local_embedding_model")
    local_embedding_device: str | None = Field(None, alias="aaf_local_embedding_device")
    local_embedding_cache_folder: Path | None = Field(
        None, alias="aaf_local_embedding_cache_folder"
    )

    # Optional per-task LLM routing. When the file exists, AAF builds a
    # `RoutingLLMProvider` that lets workflows opt into a different
    # provider/model via `ctx.llm.for_route("<name>")`. Absent file =
    # zero-config single-provider behaviour (backward-compatible).
    model_routing_config: Path = Field(
        Path("./config/model_routing.yaml"), alias="aaf_model_routing_config"
    )

    # Optional context auto-compaction. Wraps the LLM provider in
    # `CompactingLLMProvider` (see backend/core/llm/compactor.py): when
    # incoming messages would occupy more than `autocompact_threshold`
    # of the model's context window, AAF auto-summarises the middle of
    # the history (via the `autocompact_summariser_route` sub-provider
    # when routing is wired). Off by default — opt-in.
    autocompact_enabled: bool = Field(False, alias="aaf_autocompact_enabled")
    autocompact_threshold: float = Field(0.7, alias="aaf_autocompact_threshold")
    autocompact_keep_recent_n: int = Field(6, alias="aaf_autocompact_keep_recent_n")
    autocompact_summariser_route: str = Field("fast", alias="aaf_autocompact_summariser_route")

    # Self-evolution: when enabled, the runner asks `EvolverAgent` to
    # draft a heuristic Proposal after every successful workflow run.
    # Drafts go to the gated ProposalStore (status = `draft`) and only
    # take effect after human review via `/api/v1/proposals/*`. Off by
    # default — opt-in to avoid surprising users with a growing queue
    # of un-reviewed proposals.
    evolver_enabled: bool = Field(False, alias="aaf_evolver_enabled")

    # MCP servers: when enabled and `mcp_config` points at an existing
    # YAML, AAF builds an MCPClient per server, lists their tools, and
    # registers each one into the global ToolRegistry under the
    # namespaced name `mcp__<server>__<tool>`. Off by default — opt-in
    # because launching N MCP child processes on a laptop has a real
    # boot-time cost. See backend/tools/mcp_*.py for the implementation
    # and config/mcp_servers.example.yaml for the schema.
    mcp_enabled: bool = Field(False, alias="aaf_mcp_enabled")
    mcp_config: Path = Field(Path("./config/mcp_servers.yaml"), alias="aaf_mcp_config")

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_default_model: str = "gpt-4o-mini"
    openai_verify_ssl: bool = True

    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_default_model: str = "claude-3-5-sonnet-latest"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_default_model: str = "deepseek-chat"

    ollama_base_url: str = ""

    max_parallel_tasks: int = Field(4, alias="aaf_max_parallel_tasks")
    default_budget_usd: float = Field(2.0, alias="aaf_default_budget_usd")
    skill_exec_timeout_s: int = Field(120, alias="aaf_skill_exec_timeout_s")
    skill_dry_run_timeout_s: int = Field(5, alias="aaf_skill_dry_run_timeout_s")
    checkpoint_enabled: bool = Field(False, alias="aaf_checkpoint_enabled")

    # L1 skills: directory of `<name>/SKILL.md` folders. Default
    # ``./skills`` lives next to the project root in dev so the existing
    # bundled skills are picked up without further config.
    skills_root: Path = Field(Path("./skills"), alias="aaf_skills_root")
    skill_workdir_root: Path = Field(Path("./data/skill_runs"), alias="aaf_skill_workdir_root")

    # Tool registry defaults — honoured by ToolRegistry.call(). A run can
    # still override per-call for sandbox / paid-API gating.
    allow_network: bool = Field(True, alias="aaf_allow_network")
    allow_paid_apis: bool = Field(True, alias="aaf_allow_paid_apis")

    # Long-running task infra. "auto" picks `arq` when Redis is configured
    # and the ARQ library is importable, else `inmemory`.
    task_queue_backend: Literal["auto", "inmemory", "arq"] = Field(
        "auto", alias="aaf_task_queue_backend"
    )
    task_store_backend: Literal["auto", "inmemory", "sql"] = Field(
        "auto", alias="aaf_task_store_backend"
    )

    # P7 — Manuscript bundles (project-shaped manuscripts: overleaf/ +
    # plan/ + experiments/ + …). Copy mode lives under ``manuscript_root``;
    # link mode points at a user-managed directory. Caps protect the
    # laptop disk and bound the worst-case write per request.
    manuscript_root: Path = Field(Path("./data/manuscripts"), alias="aaf_manuscript_root")
    manuscript_max_file_mb: int = Field(50, alias="aaf_manuscript_max_file_mb")
    manuscript_max_bundle_mb: int = Field(500, alias="aaf_manuscript_max_bundle_mb")

    @model_validator(mode="after")
    def _ensure_workdir(self) -> Settings:
        self.workdir = self.workdir.resolve()
        return self

    def provider(self, name: str) -> ProviderConfig:
        """Return a ProviderConfig for a registered provider name.

        Providers are discovered by convention: `<name>_api_key`,
        `<name>_base_url`, `<name>_default_model` attrs on Settings.
        """
        cfg: dict[str, Any] = {
            "api_key": getattr(self, f"{name}_api_key", ""),
            "base_url": getattr(self, f"{name}_base_url", ""),
            "default_model": getattr(self, f"{name}_default_model", ""),
        }
        verify = getattr(self, f"{name}_verify_ssl", None)
        if verify is not None:
            cfg["verify_ssl"] = verify
        return ProviderConfig(**cfg)

    # ---- derived configs for MemoryFactory / LLMRegistry ----------------

    def has_llm_credentials(self, name: str) -> bool:
        """True when the named provider has enough config to make real calls."""
        if name == "mock":
            return True
        key = getattr(self, f"{name}_api_key", "") or ""
        base = getattr(self, f"{name}_base_url", "") or ""
        # Ollama doesn't need a key; a base URL alone is enough.
        if name == "ollama":
            return bool(base)
        return bool(key)

    def memory_config(self) -> dict[str, dict]:
        """Build the config dict consumed by `MemoryFactory`.

        ``*_backend = "auto"`` resolves to a best-guess per store:
        * vector: "chroma" iff persist dir set *and* chromadb importable,
          else "memory"
        * knowledge / heuristic: "yaml" (durable) — always safe locally
        * episodic: "sql" (sqlite works with zero config)
        * session: "redis" iff `redis_url` set, else "memory"
        """
        vec = _resolve_vector_backend(self.memory_vector_backend, self.chroma_persist_dir)
        know = self.memory_knowledge_backend if self.memory_knowledge_backend != "auto" else "yaml"
        heur = self.memory_heuristic_backend if self.memory_heuristic_backend != "auto" else "yaml"
        epi = self.memory_episodic_backend if self.memory_episodic_backend != "auto" else "sql"
        sess = self.memory_session_backend
        if sess == "auto":
            sess = "redis" if self.redis_url else "memory"
        docs = self.memory_documents_backend
        if docs == "auto":
            docs = "yaml"

        cfg: dict[str, dict] = {
            "vector": {"backend": vec},
            "knowledge": {"backend": know},
            "heuristic": {"backend": heur},
            "episodic": {"backend": epi},
            "session": {"backend": sess},
            "documents": {"backend": docs},
        }
        if vec == "chroma":
            cfg["vector"].update(
                persist_dir=str(self.chroma_persist_dir),
                collection=self.memory_collection,
                embedding_model=self.embedding_model,
            )
        if know == "yaml":
            cfg["knowledge"]["root"] = str(self.memory_knowledge_dir)
        if heur == "yaml":
            cfg["heuristic"]["root"] = str(self.memory_skills_dir)
        if epi == "sql":
            cfg["episodic"]["url"] = self.database_url
        if sess == "redis":
            cfg["session"]["url"] = self.redis_url
            cfg["session"]["namespace"] = "aaf"
        if docs == "yaml":
            cfg["documents"]["root"] = str(self.memory_documents_dir)
        return cfg


def _resolve_vector_backend(choice: str, persist_dir: Path) -> str:
    if choice != "auto":
        return choice
    try:
        import chromadb  # noqa: F401
    except ImportError:
        return "memory"
    # We have chromadb available — honour it when a persist dir is set.
    return "chroma" if persist_dir else "memory"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Settings fields all have defaults + aliases; mypy cannot see aliases.
    return Settings()  # type: ignore[call-arg]


def reload_settings() -> Settings:
    """Reset the cache and re-read env (useful in tests)."""
    get_settings.cache_clear()
    return get_settings()
