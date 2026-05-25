"""Skill Host — runtime counterpart to Cursor/Claude Code's skill loader.

Public API:
    SkillHost           -- the façade to import from agents/workflows
    SkillMeta, ScriptMeta, InjectionBundle, ExecResult, HeuristicSkill
    SkillInvocation, InvocationStats, SkillInvocationStore (history surface)

Internals (prefer to avoid importing directly):
    SkillLoader, SkillRegistry, SkillMatcher, MatchResult,
    SkillInjector, SkillExecutor
"""

from .executor import SkillExecutor
from .injector import SkillInjector
from .invocations import (
    InMemorySkillInvocationStore,
    InvocationStats,
    InvocationStatus,
    SkillInvocation,
    SkillInvocationStore,
)
from .loader import SkillLoader, SkillRegistry
from .matcher import MatchResult, SkillMatcher
from .registry import SkillHost
from .types import (
    ExecResult,
    HeuristicSkill,
    InjectionBundle,
    ScriptMeta,
    SkillMeta,
)

__all__ = [
    "ExecResult",
    "HeuristicSkill",
    "InMemorySkillInvocationStore",
    "InjectionBundle",
    "InvocationStats",
    "InvocationStatus",
    "MatchResult",
    "ScriptMeta",
    "SkillExecutor",
    "SkillHost",
    "SkillInjector",
    "SkillInvocation",
    "SkillInvocationStore",
    "SkillLoader",
    "SkillMatcher",
    "SkillMeta",
    "SkillRegistry",
]
