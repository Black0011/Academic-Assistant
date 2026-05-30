"""L2 Behaviour Rules: load from `rules/*.md`, inject, enforce.

Two enforcement modes (PLAN §7):
  * **prompt** — the rule's markdown body is stitched into the system
    prompt for the applicable agent(s).
  * **hook**   — `enforcement: hook` plus a dotted `hook:` import path that
    resolves to an async ``Hook`` callable; hooks run inside
    :meth:`RuleEngine.pre_action` and may mutate the action or return a
    :class:`Block` sentinel to abort.

Backward-compatible with the existing Cursor-style rules we shipped
(`alwaysApply: true` / `description:` only) — those are treated as
prompt-rules with ``scope = ["all"]``.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, TypeAlias

import frontmatter
import structlog
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger(__name__)

Enforcement = Literal["prompt", "hook"]


# ---------------------------------------------------------------------------
# Action / Block
# ---------------------------------------------------------------------------


class Action(BaseModel):
    """A proposed side-effecting operation that rules may inspect/mutate.

    Kept intentionally loose — concrete action shapes live in the caller
    (e.g. WriteAction, ToolCallAction). Only `type` is required so routing
    hooks can filter cheaply.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Block(BaseModel):
    """Sentinel returned from a hook when an action must be aborted."""

    model_config = ConfigDict(extra="forbid")

    reason: str
    rule: str = ""


Hook: TypeAlias = Callable[[Action, Any], Awaitable["Action | Block"]]


# ---------------------------------------------------------------------------
# Rule model
# ---------------------------------------------------------------------------


class Rule(BaseModel):
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    name: str
    description: str = ""
    scope: list[str] = Field(default_factory=lambda: ["all"])
    priority: int = 0
    enforcement: Enforcement = "prompt"
    hook: str | None = None  # dotted import path, required when enforcement == "hook"
    body: str = ""
    path: Path | None = None

    def applies_to(self, agent: str) -> bool:
        return "all" in self.scope or agent in self.scope


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class RuleEngine:
    """Runtime registry of rules plus hook resolution/dispatch."""

    def __init__(self) -> None:
        self._rules: list[Rule] = []
        self._hooks: dict[str, Hook] = {}  # rule_name -> resolved callable

    # ---- loading -----------------------------------------------------

    def load(self, root: Path) -> list[Rule]:
        """Load all rules under ``root``. Replaces the current rule set.

        Accepts ``.md`` and ``.mdc`` files. Malformed files are logged and
        skipped rather than raised — broken rules shouldn't break startup.
        """
        root = Path(root)
        rules: list[Rule] = []
        if not root.exists():
            log.warning("rule.engine.missing_root", root=str(root))
            self._rules = rules
            self._hooks.clear()
            return rules

        for path in sorted(root.rglob("*.md")):
            parsed = self._parse(path)
            if parsed is not None:
                rules.append(parsed)
        for path in sorted(root.rglob("*.mdc")):
            parsed = self._parse(path)
            if parsed is not None:
                rules.append(parsed)

        self._rules = sorted(rules, key=lambda r: r.priority, reverse=True)
        self._resolve_hooks()
        log.info("rule.engine.loaded", count=len(self._rules), root=str(root))
        return list(self._rules)

    def _parse(self, path: Path) -> Rule | None:
        try:
            post = frontmatter.load(str(path))
        except Exception as exc:
            log.warning("rule.engine.bad_frontmatter", path=str(path), err=str(exc))
            return None

        meta: dict[str, Any] = dict(post.metadata or {})
        body = (post.content or "").strip()

        name = str(meta.get("name") or path.stem).strip()
        scope = _normalise_scope(meta)
        enforcement: Enforcement = "hook" if meta.get("enforcement") == "hook" else "prompt"

        if enforcement == "hook" and not meta.get("hook"):
            log.warning("rule.engine.hook_missing_path", name=name, path=str(path))
            return None

        try:
            return Rule(
                name=name,
                description=str(meta.get("description", "")).strip(),
                scope=scope,
                priority=int(meta.get("priority", 0)),
                enforcement=enforcement,
                hook=str(meta["hook"]) if meta.get("hook") else None,
                body=body,
                path=path.resolve(),
            )
        except Exception as exc:
            log.warning("rule.engine.bad_rule", name=name, err=str(exc))
            return None

    def _resolve_hooks(self) -> None:
        """Import every declared hook once; broken imports drop the rule."""
        self._hooks.clear()
        for rule in list(self._rules):
            if rule.enforcement != "hook":
                continue
            # Allow programmatic registration to win over import.
            if rule.name in self._hooks:
                continue
            hook = self._import_hook(rule.hook or "")
            if hook is None:
                log.warning("rule.engine.hook_import_failed", name=rule.name, path=rule.hook)
                self._rules = [r for r in self._rules if r.name != rule.name]
                continue
            self._hooks[rule.name] = hook

    @staticmethod
    def _import_hook(dotted: str) -> Hook | None:
        if not dotted or "." not in dotted:
            return None
        module_name, attr = dotted.rsplit(".", 1)
        try:
            module = importlib.import_module(module_name)
            hook = getattr(module, attr)
        except (ImportError, AttributeError):
            return None
        if not callable(hook):
            return None
        return hook

    # ---- public API --------------------------------------------------

    def rules(self) -> list[Rule]:
        return list(self._rules)

    def register_hook(self, rule_name: str, fn: Hook) -> None:
        """Override (or inject) a hook at runtime. Mainly for tests."""
        self._hooks[rule_name] = fn

    def system_prompt(self, agent: str = "all") -> str:
        """Return the stitched prompt segment for the given agent role."""
        applicable = [r for r in self._rules if r.enforcement == "prompt" and r.applies_to(agent)]
        if not applicable:
            return ""
        lines: list[str] = ["# Rules"]
        lines.append(
            "The rules below are non-negotiable. Comply with all of them unless explicitly overridden."
        )
        for r in applicable:
            lines.append("")
            lines.append(f"## 📏 Rule · `{r.name}`")
            if r.description:
                lines.append(f"_{r.description}_")
            if r.body:
                lines.append("")
                lines.append(r.body)
        return "\n".join(lines).strip()

    async def pre_action(
        self,
        agent: str,
        action: Action,
        ctx: Any = None,
    ) -> Action | Block:
        """Run every applicable hook-rule in priority order.

        The first hook that returns a :class:`Block` short-circuits; other
        hooks may mutate and return a new :class:`Action`.
        """
        current: Action = action
        for rule in self._rules:
            if rule.enforcement != "hook" or not rule.applies_to(agent):
                continue
            hook = self._hooks.get(rule.name)
            if hook is None:
                continue
            result = await hook(current, ctx)
            if isinstance(result, Block):
                if not result.rule:
                    result = result.model_copy(update={"rule": rule.name})
                log.info("rule.engine.blocked", rule=rule.name, reason=result.reason)
                return result
            if isinstance(result, Action):
                current = result
            else:
                log.warning(
                    "rule.engine.bad_hook_return",
                    rule=rule.name,
                    got=type(result).__name__,
                )
        return current


# ---- helpers --------------------------------------------------------------


def _normalise_scope(meta: dict[str, Any]) -> list[str]:
    raw = meta.get("scope")
    if raw is None:
        # Cursor-compat: alwaysApply → applies to everyone.
        if meta.get("alwaysApply") is True:
            return ["all"]
        return ["all"]
    if isinstance(raw, str):
        if raw.lower() == "all":
            return ["all"]
        return [s.strip() for s in raw.split(",") if s.strip()]
    if isinstance(raw, list):
        return [str(s).strip() for s in raw if str(s).strip()]
    return ["all"]


__all__ = ["Action", "Block", "Hook", "Rule", "RuleEngine"]
