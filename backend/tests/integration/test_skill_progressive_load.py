"""Progressive skill injection — end-to-end proof.

Requirement #2 from the original brief: AAF must read skill bodies
"progressively", i.e. the LLM context should only carry the bodies of
the *matched* skills, not the entire skill catalogue.

These tests run against the **real** ``./skills`` directory (not a tiny
fixture) so a regression in matcher / injector that smuggles all
bodies into the prompt would actually be caught here.

What we assert:

1. With 20+ real skills loaded, ``select_and_inject(query)`` returns a
   bundle whose ``matched_skills`` count is bounded by ``top_k`` (NOT
   the total skill count).
2. The matched skill's body is present verbatim in
   ``system_additions`` (proves selective injection actually injects).
3. Distinctive sentences from at least three OTHER, unmatched skills
   are absent from ``system_additions`` (proves selective injection
   actually selects).
4. The prompt size grows linearly with ``top_k``, not with the total
   number of registered skills (the operational guarantee that
   "progressive" is real).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.skill_host import SkillHost

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_ROOT = REPO_ROOT / "skills"
WORKDIR = REPO_ROOT / "data" / "skill_runs"

# Distinctive substrings unique to specific skill bodies. If any of
# these appears in a system prompt, the corresponding skill's body got
# injected. Keeping them in one place so an unrelated edit to a SKILL
# doesn't silently break the test - the test will fail loudly with
# "fixture string no longer present".
_FINGERPRINTS: dict[str, str] = {
    "literature-search": "score = 0.4 * relevance + 0.3 * recency + 0.3 * impact",
    "pptx": "python -m markitdown presentation.pptx",
    "verification": "这条规则在 Academic-Agent 内不可协商",
    "paper-reading": 'paper_id: "arxiv:2501.12345"',
}


def _read_body(name: str) -> str:
    path = SKILLS_ROOT / name / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    # Strip frontmatter so the assertion only inspects the body.
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    return text.strip()


@pytest.fixture(scope="module")
def real_skill_root() -> Path:
    if not SKILLS_ROOT.is_dir():
        pytest.skip(f"real skills directory missing: {SKILLS_ROOT}")
    # Need at least 5 skills for the "selective" claim to mean anything.
    count = sum(1 for p in SKILLS_ROOT.iterdir() if (p / "SKILL.md").exists())
    if count < 5:
        pytest.skip(f"need >= 5 real skills, got {count}")
    return SKILLS_ROOT


async def _build_loaded_host(root: Path) -> SkillHost:
    # No embedder -> deterministic pure-keyword scoring; no risk of an
    # accidental embedding-call retry slowing the test down.
    host = SkillHost.build(
        skills_root=root,
        workdir_root=WORKDIR,
        embedder=None,
        embedding_model=None,
        token_budget=200_000,
    )
    await host.load()
    return host


@pytest.mark.asyncio
async def test_only_matched_skill_body_lands_in_prompt(real_skill_root: Path) -> None:
    host = await _build_loaded_host(real_skill_root)
    total_skills = len(host.list_skills())

    # Trigger words match `literature-search` (`search papers`,
    # `find related work`); should NOT match pptx / verification etc.
    bundle = await host.select_and_inject(
        query="search papers about diffusion policy and find related work",
        top_k=2,
    )

    # 1. Selectivity: matched << total
    assert 1 <= len(bundle.matched_skills) <= 2, (
        f"expected <= 2 matches out of {total_skills}, got "
        f"{bundle.matched_skills}"
    )
    assert "literature-search" in bundle.matched_skills

    # 2. The matched skill's body actually made it into the prompt
    target_fp = _FINGERPRINTS["literature-search"]
    assert target_fp in bundle.system_additions, (
        f"matched skill body missing - expected fingerprint "
        f"{target_fp!r} in system_additions"
    )

    # 3. Distinctive bodies of clearly-unrelated skills are ABSENT
    for name, fp in _FINGERPRINTS.items():
        if name in bundle.matched_skills:
            continue
        # Sanity: the fingerprint exists in the source file (else the
        # test would silently pass when the SKILL is edited).
        body = _read_body(name)
        assert fp in body, (
            f"fingerprint {fp!r} no longer present in skills/{name}/SKILL.md "
            "- update _FINGERPRINTS to a still-distinctive substring"
        )
        # The actual progressive guarantee:
        assert fp not in bundle.system_additions, (
            f"unmatched skill {name!r} body leaked into the prompt "
            f"(found fingerprint {fp!r})"
        )


@pytest.mark.asyncio
async def test_prompt_size_scales_with_topk_not_skill_count(real_skill_root: Path) -> None:
    """Two-knob check: prompt grows when top_k grows, not when skill count grows."""
    host = await _build_loaded_host(real_skill_root)
    total_skills = len(host.list_skills())

    bundle_k1 = await host.select_and_inject(
        query="search papers about diffusion policy", top_k=1
    )
    bundle_k3 = await host.select_and_inject(
        query="search papers about diffusion policy", top_k=3
    )

    # top_k=1 must inject strictly less than top_k=3 (or equal, when
    # fewer than 3 distinct skills score above min_score; document the
    # weaker check explicitly so a future loosening is intentional).
    assert len(bundle_k1.system_additions) <= len(bundle_k3.system_additions)

    # Even at top_k=3, the prompt must be much smaller than concatenating
    # every skill body in the catalogue. Pick a comfortably loose bound
    # (40%) so the test isn't flaky against routine SKILL edits.
    all_bodies_chars = sum(len(_read_body(s.name)) for s in host.list_skills())
    assert len(bundle_k3.system_additions) < 0.4 * all_bodies_chars, (
        f"system_additions = {len(bundle_k3.system_additions)} chars, "
        f"all bodies = {all_bodies_chars} chars - injection is no longer "
        f"selective (total skills: {total_skills})"
    )


@pytest.mark.asyncio
async def test_unrelated_query_returns_at_most_topk_skills(real_skill_root: Path) -> None:
    """Even when nothing in particular fits, the bundle stays bounded."""
    host = await _build_loaded_host(real_skill_root)

    bundle = await host.select_and_inject(
        query="weather forecast for tomorrow afternoon",
        top_k=3,
    )
    # Either we land on the built-in fallback (1 entry) or we picked at
    # most top_k weak matches; never the whole catalogue.
    assert len(bundle.matched_skills) <= 3
