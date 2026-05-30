"""Unit tests for the P13.B ``_build_graph`` pure function.

We exercise the function directly (no FastAPI app) because the graph
algorithm is non-trivial and we want fast, focused feedback if the
compatibility-merge logic or cycle detection regresses.

The integration test in ``test_app_skills_graph.py`` covers the route
binding + JSON serialisation; here we lock the algorithm.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.api.routers.skills import _build_graph, _find_cycles
from backend.core.skill_host.admin import SkillSnapshot
from backend.core.skill_host.types import SkillMeta


def _meta(name: str, *, compat: dict | None = None, domain: str = "writing") -> SkillMeta:
    """Build a minimal SkillMeta. Only fields ``_build_graph`` cares about
    are populated — everything else picks up the model defaults."""
    return SkillMeta(
        name=name,
        path=Path("/tmp") / name,
        description=f"{name} skill",
        domain=domain,
        version="1.0.0",
        raw_meta={"name": name, "compatibility": compat or {}},
    )


def _snap(name: str) -> SkillSnapshot:
    return SkillSnapshot(
        name=name,
        enabled=False,
        version_hash="deadbeef",
        loaded_from=Path("/tmp/_disabled") / name,
    )


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def test_graph_empty_when_no_skills():
    g = _build_graph([], [])
    assert g.nodes == []
    assert g.edges == []
    assert g.dangling == []
    assert g.cycles == []


def test_graph_includes_disabled_skills():
    metas = [_meta("a")]
    g = _build_graph(metas, [_snap("b_disabled")])
    names = [n.name for n in g.nodes]
    enabled = {n.name: n.enabled for n in g.nodes}
    assert "a" in names
    assert "b_disabled" in names
    assert enabled["a"] is True
    assert enabled["b_disabled"] is False


def test_graph_edge_from_downstream_declaration():
    """``a.compatibility.downstream = b`` ⇒ edge ``a → b`` declared by source."""
    metas = [_meta("a", compat={"downstream": "b"}), _meta("b")]
    g = _build_graph(metas, [])
    assert len(g.edges) == 1
    e = g.edges[0]
    assert (e.source, e.target) == ("a", "b")
    assert e.declared_by == "source"


def test_graph_edge_from_upstream_declaration():
    """``b.compatibility.upstream = a`` ⇒ edge ``a → b`` declared by target."""
    metas = [_meta("a"), _meta("b", compat={"upstream": "a"})]
    g = _build_graph(metas, [])
    assert len(g.edges) == 1
    e = g.edges[0]
    assert (e.source, e.target) == ("a", "b")
    assert e.declared_by == "target"


def test_graph_edge_declared_by_both_sides_merges():
    """When both ends declare the relation, the edge is "both" — not duplicated."""
    metas = [
        _meta("a", compat={"downstream": ["b"]}),
        _meta("b", compat={"upstream": ["a"]}),
    ]
    g = _build_graph(metas, [])
    assert len(g.edges) == 1
    assert g.edges[0].declared_by == "both"


def test_graph_compat_accepts_both_string_and_list_forms():
    """Real SKILL.md files use both ``downstream: x`` and ``downstream: [x, y]``."""
    metas = [
        _meta("a", compat={"downstream": "b"}),          # string
        _meta("b", compat={"downstream": ["c", "d"]}),   # list
        _meta("c"),
        _meta("d"),
    ]
    g = _build_graph(metas, [])
    edge_pairs = {(e.source, e.target) for e in g.edges}
    assert ("a", "b") in edge_pairs
    assert ("b", "c") in edge_pairs
    assert ("b", "d") in edge_pairs


def test_graph_picks_up_top_level_downstream_skills_field():
    """Several existing SKILL.md files (writing-core, peer-review,
    paper-orchestration, …) declare a top-level ``downstream_skills:``
    field instead of nesting under ``compatibility``. We honour both
    forms — losing 9 real-world skills' edges in the graph view would
    silently misrepresent the DAG.

    NOTE: this is intentionally a separate, top-level dict key (not a
    ``compatibility.downstream_skills`` alias) to mirror exactly what
    the loader sees in the wild.
    """
    a = SkillMeta(
        name="a",
        path=Path("/tmp/a"),
        description="emits to b via top-level field",
        domain="writing",
        version="1.0.0",
        raw_meta={"name": "a", "downstream_skills": ["b"]},  # NO `compatibility` key
    )
    b = _meta("b")
    g = _build_graph([a, b], [])
    edge_pairs = {(e.source, e.target) for e in g.edges}
    assert ("a", "b") in edge_pairs
    # Source-side declaration only — both-merge happens only when the
    # *other* end uses the upstream form.
    assert g.edges[0].declared_by == "source"


def test_graph_top_level_field_coexists_with_compatibility_block():
    """When a skill has BOTH ``compatibility.downstream`` and a top-level
    ``downstream_skills`` listing the same target, the edge is still a
    single deduped row (set-merge semantics). This pins the dedup so a
    skill author migrating between conventions doesn't get duplicate
    edges in the graph view."""
    a = SkillMeta(
        name="a",
        path=Path("/tmp/a"),
        description="declares b twice",
        domain="writing",
        version="1.0.0",
        raw_meta={
            "name": "a",
            "compatibility": {"downstream": "b"},
            "downstream_skills": ["b"],
        },
    )
    b = _meta("b")
    g = _build_graph([a, b], [])
    assert len(g.edges) == 1
    assert g.edges[0].source == "a" and g.edges[0].target == "b"


def test_graph_self_loops_via_compat_are_dropped():
    """A skill that declares itself as upstream/downstream is user error; skip silently."""
    metas = [_meta("loner", compat={"downstream": "loner", "upstream": "loner"})]
    g = _build_graph(metas, [])
    assert g.edges == []
    assert g.cycles == []


def test_graph_dangling_references_listed():
    """Names referenced under compat that don't match any installed skill go to dangling."""
    metas = [_meta("a", compat={"downstream": ["does-not-exist"]})]
    g = _build_graph(metas, [])
    assert g.dangling == ["does-not-exist"]
    # The edge is still emitted (so the UI can show the orphan link).
    assert g.edges and g.edges[0].target == "does-not-exist"


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


def test_find_cycles_empty_on_dag():
    """A pure DAG produces no SCC > 1."""
    adj = {"a": ["b"], "b": ["c"], "c": []}
    assert _find_cycles(adj) == []


def test_find_cycles_detects_simple_two_cycle():
    adj = {"a": ["b"], "b": ["a"]}
    cycles = _find_cycles(adj)
    assert len(cycles) == 1
    assert sorted(cycles[0]) == ["a", "b"]


def test_find_cycles_detects_three_cycle():
    adj = {"a": ["b"], "b": ["c"], "c": ["a"]}
    cycles = _find_cycles(adj)
    assert len(cycles) == 1
    assert sorted(cycles[0]) == ["a", "b", "c"]


def test_find_cycles_returns_multiple_components():
    adj = {
        # Cycle 1
        "a": ["b"], "b": ["a"],
        # Cycle 2 (disjoint)
        "c": ["d"], "d": ["c"],
        # Loose node
        "e": [],
    }
    cycles = _find_cycles(adj)
    assert len(cycles) == 2
    flat = sorted(name for c in cycles for name in c)
    assert flat == ["a", "b", "c", "d"]


def test_graph_end_to_end_with_cycle():
    """Full path: build_graph correctly surfaces a cycle in the cycles field."""
    metas = [
        _meta("x", compat={"downstream": "y"}),
        _meta("y", compat={"downstream": "x"}),
    ]
    g = _build_graph(metas, [])
    assert len(g.cycles) == 1
    assert sorted(g.cycles[0]) == ["x", "y"]


# ---------------------------------------------------------------------------
# Deterministic ordering — the UI depends on consistent ordering for diff
# rendering and aria-labels.
# ---------------------------------------------------------------------------


def test_graph_nodes_and_edges_are_sorted():
    metas = [
        _meta("zeta", compat={"downstream": "alpha"}),
        _meta("alpha"),
        _meta("middle", compat={"downstream": ["alpha", "zeta"]}),
    ]
    g = _build_graph(metas, [])
    assert [n.name for n in g.nodes] == ["alpha", "middle", "zeta"]
    assert [(e.source, e.target) for e in g.edges] == [
        ("middle", "alpha"),
        ("middle", "zeta"),
        ("zeta", "alpha"),
    ]


def test_node_carries_domain_and_version():
    metas = [_meta("a", domain="revision")]
    g = _build_graph(metas, [])
    assert g.nodes[0].domain == "revision"
    assert g.nodes[0].version == "1.0.0"
