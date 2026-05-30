"""Hook callables referenced by fixture rules (dotted-import path
resolution test). Async — matches the production Hook signature.
"""

from __future__ import annotations

from typing import Any

from backend.core.rule_engine import Action, Block


async def pass_through(action: Action, ctx: Any) -> Action:
    """No-op hook that returns the action unchanged."""
    return action


async def block_dangerous(action: Action, ctx: Any) -> Action | Block:
    """Block any action whose payload has ``dangerous=True``."""
    if action.payload.get("dangerous") is True:
        return Block(reason="payload marked dangerous")
    return action


async def annotate_write(action: Action, ctx: Any) -> Action:
    """Append an ``annotated=True`` flag — used to test mutation chaining."""
    if action.type != "write_file":
        return action
    new_payload = dict(action.payload)
    new_payload["annotated"] = True
    return action.model_copy(update={"payload": new_payload})
