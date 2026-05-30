from pathlib import Path

import pytest

from backend.core.llm import MockLLMProvider
from backend.core.skill_host.loader import SkillLoader
from backend.core.skill_host.matcher import SkillMatcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


@pytest.mark.asyncio
async def test_keyword_only_returns_best_match():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    matcher = SkillMatcher(loader.registry, embedder=None)
    results = await matcher.match("please echo this message")
    assert results
    assert results[0].skill.name == "echo-test"
    assert results[0].kw_score > 0


@pytest.mark.asyncio
async def test_falls_back_to_builtin_when_no_match():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    matcher = SkillMatcher(loader.registry, embedder=None)
    results = await matcher.match("totally unrelated XYZZY quantum foo", min_score=0.5)
    assert len(results) == 1
    assert results[0].skill.name == "general-assistant"


@pytest.mark.asyncio
async def test_exclusive_collision_keeps_highest():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    matcher = SkillMatcher(loader.registry, embedder=None)
    # Both sleep-test and exclusive-alt have trigger "sleep" and exclusive=True
    results = await matcher.match("please sleep", top_k=5)
    exclusive_in_results = [r for r in results if r.skill.exclusive]
    assert len(exclusive_in_results) <= 1


@pytest.mark.asyncio
async def test_domain_filter():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    matcher = SkillMatcher(loader.registry, embedder=None)
    # All our fixtures are domain=test
    results = await matcher.match("echo", domain="test")
    assert all(r.skill.domain == "test" for r in results if r.skill.name != "general-assistant")
    # Wrong domain → fallback
    results2 = await matcher.match("echo", domain="writing", min_score=0.1)
    assert len(results2) == 1
    assert results2[0].skill.name == "general-assistant"


@pytest.mark.asyncio
async def test_embedder_is_used_and_cached():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    mock = MockLLMProvider()
    matcher = SkillMatcher(loader.registry, embedder=mock)

    # First call populates the cache. Deterministic Mock embedder.
    r1 = await matcher.match("echo")
    assert r1
    # Number of embed() calls so far (query + one per skill)
    n_skills = len(loader.registry.snapshot())
    first_embed_count = sum(1 for _ in range(0))  # count tracking

    # Second call should only embed the query again (skills cached).
    # We can observe this indirectly via the embed cache attribute.
    cache_after_first = dict(matcher._embed_cache)
    r2 = await matcher.match("echo message")
    assert r2
    cache_after_second = dict(matcher._embed_cache)
    assert cache_after_first == cache_after_second
    assert len(cache_after_second) == n_skills


@pytest.mark.asyncio
async def test_embedder_failure_falls_back_to_keyword():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()

    class BrokenEmbedder:
        async def embed(self, texts, *, model=None):
            raise RuntimeError("embed down")

    matcher = SkillMatcher(loader.registry, embedder=BrokenEmbedder())
    results = await matcher.match("echo")
    # Still finds the match via keyword fallback
    assert results[0].skill.name == "echo-test"
