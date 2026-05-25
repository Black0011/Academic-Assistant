"""Unit tests for the P14.C ``_apply_edge_ops`` pure function.

We exercise this directly (no SkillAdmin / no FastAPI) because the
YAML surgery is tricky enough that we want O(ms) feedback when it
regresses. The integration tests in ``test_app_skills_edges.py`` cover
the route binding + filesystem + reload path.
"""

from __future__ import annotations

import frontmatter
import pytest

from backend.core.skill_host.admin import (
    EdgeOp,
    SkillAdminError,
    _apply_edge_ops,
    _coerce_name_list,
    _frontmatter_has_inline_comments,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SKILL_TEMPLATE = """---
name: {name}
description: a description
domain: writing
triggers:
  - foo
version: "1.0.0"
---
# {name}

Body.
"""


def _build(name: str = "skill-a", *, frontmatter_extra: str = "") -> str:
    base = SKILL_TEMPLATE.format(name=name)
    if not frontmatter_extra:
        return base
    fm_end = base.find("\n---\n", 4)
    assert fm_end != -1
    return base[: fm_end] + "\n" + frontmatter_extra.rstrip("\n") + base[fm_end:]


def _meta(body: str) -> dict:
    return dict(frontmatter.loads(body).metadata or {})


# ---------------------------------------------------------------------------
# _coerce_name_list
# ---------------------------------------------------------------------------


def test_coerce_handles_string_list_and_garbage():
    assert _coerce_name_list("foo") == ["foo"]
    assert _coerce_name_list(["foo", "  ", "bar"]) == ["foo", "bar"]
    assert _coerce_name_list(None) == []
    assert _coerce_name_list({"x": 1}) == []
    assert _coerce_name_list([1, 2, 3]) == []  # non-string entries dropped


# ---------------------------------------------------------------------------
# add path
# ---------------------------------------------------------------------------


def test_add_downstream_creates_compatibility_block():
    body = _build()
    new_body, report = _apply_edge_ops(
        body,
        adds=[EdgeOp(kind="downstream", target="skill-b")],
        removes=[],
    )
    meta = _meta(new_body)
    assert meta["compatibility"] == {"downstream": "skill-b"}
    assert report.added == [("downstream", "skill-b")]
    assert report.skipped_dup == []


def test_add_downstream_promotes_to_list_when_multiple():
    body = _build(frontmatter_extra="compatibility:\n  downstream: skill-b")
    new_body, report = _apply_edge_ops(
        body,
        adds=[EdgeOp(kind="downstream", target="skill-c")],
        removes=[],
    )
    meta = _meta(new_body)
    # Two entries → list form (sorted on emit, deterministic for git diff).
    assert meta["compatibility"]["downstream"] == ["skill-b", "skill-c"]
    assert report.added == [("downstream", "skill-c")]


def test_add_upstream_writes_compat_upstream():
    body = _build()
    new_body, _ = _apply_edge_ops(
        body, adds=[EdgeOp(kind="upstream", target="skill-x")], removes=[]
    )
    meta = _meta(new_body)
    assert meta["compatibility"] == {"upstream": "skill-x"}


def test_add_dedupe_skips_existing():
    body = _build(frontmatter_extra="compatibility:\n  downstream: skill-b")
    new_body, report = _apply_edge_ops(
        body, adds=[EdgeOp(kind="downstream", target="skill-b")], removes=[]
    )
    meta = _meta(new_body)
    # Single value stays single (we don't promote to list for dups).
    assert meta["compatibility"]["downstream"] == "skill-b"
    assert report.added == []
    assert report.skipped_dup == [("downstream", "skill-b")]


# ---------------------------------------------------------------------------
# remove path — searches BOTH compatibility.* AND legacy downstream_skills
# ---------------------------------------------------------------------------


def test_remove_from_compat_downstream_list():
    body = _build(
        frontmatter_extra="compatibility:\n  downstream: [skill-b, skill-c]"
    )
    new_body, report = _apply_edge_ops(
        body, adds=[], removes=[EdgeOp(kind="downstream", target="skill-b")]
    )
    meta = _meta(new_body)
    assert meta["compatibility"]["downstream"] == "skill-c"
    assert report.removed == [("downstream", "skill-b")]


def test_remove_collapses_compatibility_when_empty():
    """If removing the last edge empties ``compatibility``, drop the key
    entirely so we never leave ``compatibility: {}`` cruft on disk."""
    body = _build(frontmatter_extra="compatibility:\n  downstream: skill-b")
    new_body, _ = _apply_edge_ops(
        body, adds=[], removes=[EdgeOp(kind="downstream", target="skill-b")]
    )
    meta = _meta(new_body)
    assert "compatibility" not in meta


def test_remove_searches_top_level_downstream_skills_too():
    """Nine in-tree skills use the legacy ``downstream_skills:`` form;
    the graph view's delete-edge button must work for those too."""
    body = _build(frontmatter_extra="downstream_skills: [skill-b, skill-c]")
    new_body, report = _apply_edge_ops(
        body, adds=[], removes=[EdgeOp(kind="downstream", target="skill-b")]
    )
    meta = _meta(new_body)
    assert meta["downstream_skills"] == "skill-c"
    assert report.removed == [("downstream", "skill-b")]


def test_remove_drops_legacy_field_when_emptied():
    body = _build(frontmatter_extra="downstream_skills: skill-b")
    new_body, _ = _apply_edge_ops(
        body, adds=[], removes=[EdgeOp(kind="downstream", target="skill-b")]
    )
    meta = _meta(new_body)
    assert "downstream_skills" not in meta


def test_remove_missing_target_records_skipped_missing():
    body = _build()
    _, report = _apply_edge_ops(
        body, adds=[], removes=[EdgeOp(kind="downstream", target="nope")]
    )
    assert report.removed == []
    assert report.skipped_missing == [("downstream", "nope")]


def test_remove_from_both_forms_simultaneously():
    """If an author wrote the same target in BOTH the compat block AND
    the legacy field (rare, mostly mid-migration), one remove cleans both."""
    body = _build(
        frontmatter_extra=(
            "compatibility:\n  downstream: skill-b\n"
            "downstream_skills: skill-b"
        )
    )
    new_body, report = _apply_edge_ops(
        body, adds=[], removes=[EdgeOp(kind="downstream", target="skill-b")]
    )
    meta = _meta(new_body)
    assert "compatibility" not in meta
    assert "downstream_skills" not in meta
    assert report.removed == [("downstream", "skill-b")]


# ---------------------------------------------------------------------------
# Mixed add + remove
# ---------------------------------------------------------------------------


def test_add_and_remove_in_one_call():
    body = _build(frontmatter_extra="compatibility:\n  downstream: [b, c]")
    new_body, report = _apply_edge_ops(
        body,
        adds=[EdgeOp(kind="upstream", target="root")],
        removes=[EdgeOp(kind="downstream", target="b")],
    )
    meta = _meta(new_body)
    assert meta["compatibility"] == {"upstream": "root", "downstream": "c"}
    assert report.added == [("upstream", "root")]
    assert report.removed == [("downstream", "b")]


# ---------------------------------------------------------------------------
# Unparseable / structurally bad input
# ---------------------------------------------------------------------------


def test_apply_edge_ops_rejects_no_frontmatter():
    with pytest.raises(SkillAdminError) as exc:
        _apply_edge_ops("just body, no fm", adds=[], removes=[])
    assert exc.value.code == "validation"


# ---------------------------------------------------------------------------
# Comment-loss warning
# ---------------------------------------------------------------------------


def test_inline_comment_detection_flags_decorative_comments():
    body_with = _build(frontmatter_extra="# v2.2.5 metadata\ncompatibility:\n  downstream: b")
    body_without = _build(frontmatter_extra="compatibility:\n  downstream: b")
    assert _frontmatter_has_inline_comments(body_with) is True
    assert _frontmatter_has_inline_comments(body_without) is False


def test_warning_emitted_when_original_had_comments():
    body = _build(frontmatter_extra="# decorative\ncompatibility:\n  downstream: b")
    _, report = _apply_edge_ops(
        body, adds=[EdgeOp(kind="upstream", target="x")], removes=[]
    )
    assert any("comment" in w for w in report.warnings)


def test_no_warning_when_no_comments():
    body = _build()
    _, report = _apply_edge_ops(
        body, adds=[EdgeOp(kind="upstream", target="x")], removes=[]
    )
    assert report.warnings == []


# ---------------------------------------------------------------------------
# Roundtrip: result must remain a valid SKILL.md (frontmatter parseable +
# body intact). This is the contract _validate_skill_md will lean on.
# ---------------------------------------------------------------------------


def test_body_below_frontmatter_is_unchanged():
    body = _build()
    new_body, _ = _apply_edge_ops(
        body, adds=[EdgeOp(kind="downstream", target="x")], removes=[]
    )
    new_post = frontmatter.loads(new_body)
    # Body content survives intact.
    assert "# skill-a" in new_post.content
    assert "Body." in new_post.content


def test_emitted_body_is_re_parseable_and_idempotent_on_second_pass():
    body = _build()
    once, _ = _apply_edge_ops(
        body, adds=[EdgeOp(kind="downstream", target="b")], removes=[]
    )
    twice, report = _apply_edge_ops(
        once, adds=[EdgeOp(kind="downstream", target="b")], removes=[]
    )
    # Adding the same edge twice = no-op (skipped_dup), file unchanged.
    assert report.skipped_dup == [("downstream", "b")]
    assert _meta(twice) == _meta(once)
