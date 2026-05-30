"""End-to-end smoke: DemoWorkflow wired with SkillHost + MockLLM + RuleEngine."""

from pathlib import Path

import pytest

from backend.core.events import EventType
from backend.core.llm import MockLLMProvider
from backend.core.rule_engine import RuleEngine
from backend.core.skill_host import SkillHost
from backend.memory import MemoryBundle, PaperCard
from backend.workflows.base import WorkflowContext
from backend.workflows.demo import DemoWorkflow

SKILL_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"
RULE_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rules"


@pytest.mark.asyncio
async def test_demo_runs_end_to_end_no_llm(tmp_path):
    """Stage graph works even without an LLM (offline mode)."""
    host = SkillHost.build(skills_root=SKILL_FIXTURES, workdir_root=tmp_path)
    await host.load()

    engine = RuleEngine()
    engine.load(RULE_FIXTURES)

    ctx = WorkflowContext(
        task_id="demo-1",
        query="please echo this",
        skill_host=host,
        rule_engine=engine,
    )
    out = await DemoWorkflow().run(ctx)
    assert out.verdict == "ok"
    # offline branch writes a synthetic answer
    assert isinstance(out.results, str)
    # Lifecycle events must all appear.
    types = {e.type for e in ctx.trace}
    for expected in (
        EventType.TASK_START,
        EventType.TASK_STAGE_START,
        EventType.TASK_STAGE_END,
        EventType.TASK_END,
        EventType.SKILL_MATCHED,
    ):
        assert expected in types


@pytest.mark.asyncio
async def test_demo_runs_with_mock_llm(tmp_path):
    host = SkillHost.build(skills_root=SKILL_FIXTURES, workdir_root=tmp_path)
    await host.load()

    engine = RuleEngine()
    engine.load(RULE_FIXTURES)

    mock = MockLLMProvider()
    mock.queue_text("scripted mock answer")
    ctx = WorkflowContext(
        task_id="demo-2",
        query="echo please",
        llm=mock,
        skill_host=host,
        rule_engine=engine,
    )
    out = await DemoWorkflow().run(ctx)
    assert out.verdict == "ok"
    assert out.results == "scripted mock answer"
    # Budget snapshot populated (even if tokens are zero from mock)
    assert "elapsed_s" in out.budget


@pytest.mark.asyncio
async def test_demo_reads_and_writes_memory(tmp_path):
    host = SkillHost.build(skills_root=SKILL_FIXTURES, workdir_root=tmp_path)
    await host.load()

    memory = MemoryBundle.in_memory()
    await memory.knowledge.write_card(
        PaperCard(paper_id="p1", title="echo studies", abstract="please echo data")
    )

    mock = MockLLMProvider()
    mock.queue_text("scripted answer")

    ctx = WorkflowContext(
        task_id="demo-mem",
        query="please echo this",
        llm=mock,
        skill_host=host,
        memory=memory,
        session_id="sess-1",
    )
    out = await DemoWorkflow().run(ctx)
    assert out.verdict == "ok"

    types = {e.type for e in ctx.trace}
    assert EventType.MEMORY_READ in types
    assert EventType.MEMORY_WRITE in types

    reflections = await memory.episodic.recent(n=5, session_id="sess-1")
    assert reflections
    assert reflections[0].source_run_id == "demo-mem"


@pytest.mark.asyncio
async def test_demo_reports_error_on_stage_failure(tmp_path):
    host = SkillHost.build(skills_root=SKILL_FIXTURES, workdir_root=tmp_path)
    await host.load()
    mock = MockLLMProvider()
    mock.queue_error("llm down")

    ctx = WorkflowContext(
        task_id="demo-3",
        query="echo please",
        llm=mock,
        skill_host=host,
    )
    out = await DemoWorkflow().run(ctx)
    assert out.verdict == "error"
    assert out.error and "llm down" in out.error
    assert any(e.type == EventType.TASK_ERROR for e in ctx.trace)
