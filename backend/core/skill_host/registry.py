"""Public façade: SkillHost = Loader + Matcher + Injector + Executor.

All runtime code (agents, workflows) talks to this object; the four
underlying modules are internals.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from backend.core.errors import SkillNotFound

from .executor import SkillExecutor
from .injector import SkillInjector
from .invocations import (
    InMemorySkillInvocationStore,
    InvocationStats,
    SkillInvocation,
    SkillInvocationStore,
)
from .loader import SkillLoader, SkillRegistry
from .matcher import SkillMatcher
from .pull import (
    build_pull_system_additions,
    build_skill_tools,
    render_skill_body,
    render_script_tools,
)
from .types import ExecResult, HeuristicSkill, InjectionBundle, SkillMeta

from backend.core.llm.base import ToolSpec

if TYPE_CHECKING:
    from datetime import datetime

    from backend.core.llm.base import LLMProvider

log = structlog.get_logger(__name__)


class SkillHost:
    """What workflows import and use.

    Construct once at application startup (FastAPI lifespan) and share via
    DI. All public methods are async-safe.
    """

    def __init__(
        self,
        *,
        loader: SkillLoader,
        matcher: SkillMatcher,
        injector: SkillInjector,
        executor: SkillExecutor,
        invocations: SkillInvocationStore | None = None,
    ) -> None:
        self._loader = loader
        self._matcher = matcher
        self._injector = injector
        self._executor = executor
        self._invocations = invocations or InMemorySkillInvocationStore()
        self._executor.set_invocation_store(self._invocations)

    # ---- factory -----------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        skills_root: Path,
        workdir_root: Path,
        embedder: LLMProvider | None = None,
        embedding_model: str | None = None,
        token_budget: int | None = None,
        default_timeout_s: int | None = None,
        invocations: SkillInvocationStore | None = None,
    ) -> SkillHost:
        loader = SkillLoader(skills_root)
        matcher = SkillMatcher(loader.registry, embedder=embedder, embedding_model=embedding_model)
        injector = (
            SkillInjector(token_budget=token_budget)
            if token_budget is not None
            else SkillInjector()
        )
        executor = SkillExecutor(
            workdir_root=workdir_root,
            default_timeout_s=default_timeout_s or 120,
        )
        return cls(
            loader=loader,
            matcher=matcher,
            injector=injector,
            executor=executor,
            invocations=invocations,
        )

    # ---- public API --------------------------------------------------

    async def load(self) -> None:
        """Initial scan. Must be awaited before `select_and_inject`."""
        await self._loader.load_all()

    async def reload(self, name: str | None = None) -> None:
        await self._loader.reload(name)

    def list_skills(self) -> list[SkillMeta]:
        return self._loader.registry.snapshot()

    def get_skill(self, name: str) -> SkillMeta | None:
        return self._loader.registry.get(name)

    def set_embedder(self, embedder: LLMProvider | None) -> None:
        self._matcher.set_embedder(embedder)

    @property
    def skills_root(self) -> Path:
        return self._loader.skills_root

    @property
    def generation(self) -> int:
        return self._loader.registry.generation

    @property
    def executor(self) -> SkillExecutor:
        return self._executor

    @property
    def invocations(self) -> SkillInvocationStore:
        return self._invocations

    # ---- pull-mode (Claude Code style) -------------------------------

    def build_tools(self) -> list[ToolSpec]:
        """Return ALL skills as ToolSpecs for pull-mode invocation.

        Each tool is ``use_skill__<name>``. The LLM decides which skill
        to activate based on the tool description and triggers. No skill
        body is pre-injected into the system prompt.
        """
        skills = self._loader.registry.snapshot()
        return build_skill_tools(skills)

    def pull_system_additions(self, max_skills: int = 24) -> str:
        """Minimal system prompt note listing skill tools."""
        skills = self._loader.registry.snapshot()
        return build_pull_system_additions(len(skills))

    # ---- DAG queries -------------------------------------------------

    def downstream_of(self, name: str) -> list[str]:
        """Skills that this skill declares as downstream dependencies."""
        skill = self._loader.registry.get(name)
        if skill is None:
            return []
        return list(skill.downstream_skills)

    def upstream_of(self, name: str) -> list[str]:
        """Skills that declare *this* skill as a downstream dependency."""
        result: list[str] = []
        for s in self._loader.registry.snapshot():
            if name in s.downstream_skills:
                result.append(s.name)
        return result

    def dag_chain(self, name: str) -> list[dict]:
        """Return the full DAG chain reachable from a skill (BFS)."""
        visited: set[str] = set()
        chain: list[dict] = []
        queue = [name]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            skill = self._loader.registry.get(current)
            if skill is None:
                continue
            chain.append({
                "name": skill.name,
                "description": skill.description,
                "consumes": skill.consumes,
                "produces": skill.produces,
                "downstream": skill.downstream_skills,
            })
            for ds in skill.downstream_skills:
                if ds not in visited:
                    queue.append(ds)
        return chain

    # ---- skill activation (pull mode) ---------------------------------

    def activate_skill(self, name: str) -> dict:
        """Load a skill's full body and sub-tools on demand.

        Called when the LLM invokes ``use_skill__<name>``. Returns:
          - body: rendered skill body (Markdown, includes DAG info)
          - tools: ToolSpecs for the skill's bundled scripts
          - downstream_skills: names of skills to call next in the DAG chain
          - consumes / produces / preconditions: DAG metadata
        """
        skill = self._loader.registry.get(name)
        if skill is None:
            return {"body": f"Skill '{name}' not found.", "tools": [],
                    "downstream_skills": [], "consumes": [], "produces": [], "preconditions": []}
        body = render_skill_body(skill)
        tools = render_script_tools(skill)
        return {
            "body": body,
            "tools": tools,
            "downstream_skills": skill.downstream_skills,
            "consumes": skill.consumes,
            "produces": skill.produces,
            "preconditions": skill.preconditions,
        }

    # ---- legacy push-mode (keep for backward compat) -----------------

    async def list_invocations(
        self,
        skill: str,
        *,
        limit: int = 50,
        since: datetime | None = None,
    ) -> list[SkillInvocation]:
        return await self._invocations.list_for(skill, limit=limit, since=since)

    async def invocation_stats(self, skill: str, *, window_days: int = 30) -> InvocationStats:
        return await self._invocations.stats(skill, window_days=window_days)

    async def select_and_inject(
        self,
        query: str,
        *,
        context: str = "",
        top_k: int = 3,
        min_score: float = 0.3,
        domain: str | None = None,
        heuristics: list[HeuristicSkill] | None = None,
    ) -> InjectionBundle:
        matches = await self._matcher.match(
            query,
            context=context,
            top_k=top_k,
            min_score=min_score,
            domain=domain,
        )
        return self._injector.inject(matches, heuristics=heuristics)

    async def call_tool(
        self,
        tool_name: str,
        args: dict,
        *,
        task_id: str,
        timeout_s: int | None = None,
        bundle: InjectionBundle | None = None,
    ) -> ExecResult:
        script_path = self._resolve_tool(tool_name, bundle)
        if script_path is None:
            raise SkillNotFound(f"unknown tool: {tool_name}", tool_name=tool_name)
        uses_llm = self._tool_uses_llm(tool_name)
        return await self._executor.run(
            script_path=script_path,
            args=args,
            tool_name=tool_name,
            task_id=task_id,
            timeout_s=timeout_s,
            uses_llm=uses_llm,
        )

    # ---- helpers -----------------------------------------------------

    def _resolve_tool(self, tool_name: str, bundle: InjectionBundle | None) -> Path | None:
        if bundle is not None:
            path = bundle.script_index.get(tool_name)
            if path is not None:
                return path
        # Fallback: derive from tool name convention skill__script
        if "__" not in tool_name:
            return None
        skill_name, script_stem = tool_name.split("__", 1)
        skill = self._loader.registry.get(skill_name)
        if skill is None:
            return None
        for sc in skill.scripts:
            if sc.name == script_stem:
                return sc.path
        return None

    def _tool_uses_llm(self, tool_name: str) -> bool:
        if "__" not in tool_name:
            return False
        skill_name, script_stem = tool_name.split("__", 1)
        skill = self._loader.registry.get(skill_name)
        if skill is None:
            return False
        for sc in skill.scripts:
            if sc.name == script_stem:
                return sc.uses_llm
        return False


__all__ = ["SkillHost", "SkillRegistry"]
