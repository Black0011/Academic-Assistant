"""Unit tests for `WorkflowRegistry`."""

from __future__ import annotations

import pytest

from backend.core.errors import ConfigError, NotFoundError
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput
from backend.workflows.registry import WorkflowRegistry, build_default_registry


class _FakeA(BaseWorkflow):
    name = "fake_a"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        return WorkflowOutput(task_id=ctx.task_id, verdict="ok")


class _FakeB(BaseWorkflow):
    name = "fake_b"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        return WorkflowOutput(task_id=ctx.task_id, verdict="ok")


class _Anon(BaseWorkflow):
    # Deliberately blank name — registry must refuse.
    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        return WorkflowOutput(task_id=ctx.task_id, verdict="ok")


def test_register_and_lookup():
    reg = WorkflowRegistry()
    reg.register(_FakeA)
    assert reg.has("fake_a")
    assert reg.get("fake_a") is _FakeA
    inst = reg.instantiate("fake_a")
    assert isinstance(inst, _FakeA)


def test_register_unnamed_raises():
    reg = WorkflowRegistry()
    with pytest.raises(ConfigError):
        reg.register(_Anon)


def test_register_duplicate_requires_overwrite():
    reg = WorkflowRegistry()
    reg.register(_FakeA)

    class _Clash(BaseWorkflow):
        name = "fake_a"

        async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
            return WorkflowOutput(task_id=ctx.task_id, verdict="ok")

    with pytest.raises(ConfigError):
        reg.register(_Clash)
    reg.register(_Clash, overwrite=True)
    assert reg.get("fake_a") is _Clash


def test_register_same_class_is_idempotent():
    reg = WorkflowRegistry()
    reg.register(_FakeA)
    reg.register(_FakeA)  # no raise
    assert reg.names() == ["fake_a"]


def test_get_unknown_raises_not_found():
    reg = WorkflowRegistry()
    with pytest.raises(NotFoundError):
        reg.get("missing")


def test_describe_returns_metadata():
    reg = WorkflowRegistry()
    reg.register(_FakeA)
    reg.register(_FakeB)
    entries = reg.describe()
    names = [e["name"] for e in entries]
    assert names == ["fake_a", "fake_b"]
    assert all(e["version"] == "1.0.0" for e in entries)
    assert all("module" in e and "class" in e for e in entries)


def test_unregister():
    reg = WorkflowRegistry()
    reg.register(_FakeA)
    reg.unregister("fake_a")
    assert not reg.has("fake_a")
    reg.unregister("nope")  # idempotent


def test_default_registry_discovers_all_workflows():
    reg = build_default_registry()
    names = set(reg.names())
    # These four workflows ship with the framework.
    assert {"demo", "research", "write", "revision", "consult"}.issubset(names)


def test_discover_is_idempotent():
    reg = WorkflowRegistry()
    added_first = reg.discover()
    added_second = reg.discover()
    assert added_first >= 4
    assert added_second == 0
