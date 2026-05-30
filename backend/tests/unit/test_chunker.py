"""Unit tests for the markdown chunker (M7.3)."""

from __future__ import annotations

from backend.memory.chunker import chunk_markdown


def test_short_text_collapses_to_single_chunk() -> None:
    text = "Just a couple of sentences. Nothing exciting here."
    chunks = chunk_markdown(text, target_tokens=200)
    assert len(chunks) == 1
    assert chunks[0].text.startswith("Just a couple")
    assert chunks[0].section_path == []


def test_headings_become_section_paths() -> None:
    text = (
        "# Title\nIntro paragraph.\n\n"
        "## Methods\nMethod paragraph.\n\n"
        "### Architecture\nArchitecture paragraph.\n\n"
        "## Results\nResults paragraph.\n"
    )
    chunks = chunk_markdown(text, target_tokens=400)
    paths = {tuple(c.section_path) for c in chunks}
    assert ("Title",) in paths
    assert ("Title", "Methods") in paths
    assert ("Title", "Methods", "Architecture") in paths
    assert ("Title", "Results") in paths


def test_long_section_slides_with_overlap() -> None:
    para = "lorem ipsum " * 200  # ~2400 chars >> target.
    text = f"# Doc\n{para}"
    chunks = chunk_markdown(text, target_tokens=200, overlap_tokens=20)
    assert len(chunks) >= 3
    # All chunks share the same path.
    assert all(c.section_path == ["Doc"] for c in chunks)
    # Adjacent chunks should overlap in characters.
    if len(chunks) >= 2:
        assert chunks[0].char_offset_end > chunks[1].char_offset_start


def test_code_fence_is_not_split_mid_block() -> None:
    body_lines = ["normal line"] * 50
    code_block = ["```", *(["print('x')"] * 80), "```"]
    text = "# Doc\n" + "\n".join(body_lines + code_block + body_lines)
    chunks = chunk_markdown(text, target_tokens=120, overlap_tokens=10)
    # The fenced block must live in exactly one chunk (never split).
    fence_chunks = [c for c in chunks if "```" in c.text]
    assert any(c.text.count("```") == 2 for c in fence_chunks), (
        "expected the code fence to stay atomic"
    )


def test_chinese_text_chunks_without_loss() -> None:
    body = "段落内容,包含一些中文标点." * 60  # ~1700 chars.
    text = f"# 文档\n{body}\n## 二级\n{body}"
    chunks = chunk_markdown(text, target_tokens=300, overlap_tokens=30)
    assert len(chunks) >= 2
    joined = "".join(c.text for c in chunks)
    assert "段落内容" in joined


def test_no_headings_yields_one_section() -> None:
    text = "no heading here. Just some prose. " * 5
    chunks = chunk_markdown(text, target_tokens=300)
    assert len(chunks) == 1
    assert chunks[0].section_path == []


def test_empty_input_returns_empty_list() -> None:
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n\n   ") == []
