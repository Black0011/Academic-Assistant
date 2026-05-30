"""Markdown / plain-text chunker for the M7.3 DocumentStore.

Design (PLAN §20.8 M7.3):

1. Heading-aware top-level split. ATX headings (``#``..``######``) become
   the natural section boundaries; ``section_path`` tracks the breadcrumb
   so retrieval can render ``doc_title > Methods > Architecture``.
2. Each section that exceeds ``target_tokens`` is sliced with a sliding
   window with ``overlap_tokens`` of overlap so neighbouring chunks share
   context (avoids dropping a fact at a boundary).
3. Code fences (``` ``` ``` ```) and table rows (``|---|`` separators) are
   never split mid-block — we treat them as atomic and only break on the
   next blank line.
4. Tokens are estimated as ``chars / 4`` (good enough across English /
   Chinese; the embedder is the ground truth at retrieval time).

The output is a list of plain dataclasses; the caller builds the final
:class:`DocChunk` with the deterministic ``chunk_id``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Hard caps for safety. Match `MAX_INGEST_BYTES` in the documents router.
DEFAULT_TARGET_TOKENS = 800
DEFAULT_OVERLAP_TOKENS = 100
TOKEN_CHAR_RATIO = 4

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_RE = re.compile(r"^```")


@dataclass
class Chunk:
    """Pre-id chunk emitted by :func:`chunk_markdown`.

    The store is responsible for assigning ``chunk_id`` and writing the
    final :class:`backend.memory.models.DocChunk` row.
    """

    text: str
    char_offset_start: int
    char_offset_end: int
    section_path: list[str] = field(default_factory=list)


def chunk_markdown(
    text: str,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    respect_headings: bool = True,
) -> list[Chunk]:
    """Split markdown / plain text into retrieval-friendly chunks.

    The function never raises on weird input — pathological documents
    (no headings, single line, all whitespace) just collapse to a single
    chunk or an empty list.
    """
    if not text:
        return []
    target_chars = max(200, target_tokens * TOKEN_CHAR_RATIO)
    overlap_chars = max(0, min(target_chars - 1, overlap_tokens * TOKEN_CHAR_RATIO))

    sections = _split_sections(text) if respect_headings else [(0, list[str](), text)]

    chunks: list[Chunk] = []
    for offset, path, body in sections:
        body = body.strip("\n")
        if not body.strip():
            continue
        if len(body) <= target_chars:
            chunks.append(
                Chunk(
                    text=body,
                    char_offset_start=offset,
                    char_offset_end=offset + len(body),
                    section_path=list(path),
                )
            )
            continue
        # Section is too long → sliding window over atomic blocks.
        for piece in _slide(body, offset, target_chars, overlap_chars):
            piece.section_path = list(path)
            chunks.append(piece)
    return chunks


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _split_sections(text: str) -> list[tuple[int, list[str], str]]:
    """Walk the document and yield (offset, breadcrumb, body) tuples.

    Sections are delimited by ATX headings; the breadcrumb is built by
    tracking the deepest seen heading at each level.
    """
    lines = text.splitlines(keepends=True)

    # Pre-compute per-line offsets so we can report char positions cheaply.
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    # Track active stack of (level, title); rebuild path on each heading.
    stack: list[tuple[int, str]] = []
    sections: list[tuple[int, list[str], str]] = []
    cur_start = 0
    cur_path: list[str] = []
    cur_lines: list[str] = []
    in_fence = False

    def flush(end_idx: int) -> None:
        if not cur_lines:
            return
        body = "".join(cur_lines)
        sections.append((cur_start, list(cur_path), body))

    for idx, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            cur_lines.append(line)
            continue
        match = None if in_fence else _HEADING_RE.match(line.rstrip("\n"))
        if match:
            flush(idx)
            level = len(match.group(1))
            title = match.group(2).strip()
            # Pop deeper / equal entries.
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            cur_path = [t for _, t in stack]
            cur_start = offsets[idx]
            cur_lines = []
            continue
        if not cur_lines and not line.strip():
            # Skip leading blank lines that follow a heading flush.
            cur_start = offsets[idx + 1]
            continue
        cur_lines.append(line)

    flush(len(lines))

    if not sections:
        return [(0, [], text)]
    return sections


def _slide(
    body: str,
    base_offset: int,
    target_chars: int,
    overlap_chars: int,
) -> list[Chunk]:
    """Slide a window across ``body`` respecting code fences + table rows."""
    blocks = _atomic_blocks(body)
    out: list[Chunk] = []

    cursor = 0
    n = len(body)
    while cursor < n:
        end = min(cursor + target_chars, n)
        # Snap ``end`` back to the nearest atomic-block boundary so we
        # never split a code fence / table.
        end = _snap_to_block_end(blocks, cursor, end)
        slice_text = body[cursor:end].strip()
        if slice_text:
            out.append(
                Chunk(
                    text=slice_text,
                    char_offset_start=base_offset + cursor,
                    char_offset_end=base_offset + end,
                )
            )
        if end >= n:
            break
        cursor = max(cursor + 1, end - overlap_chars)
    return out


def _atomic_blocks(body: str) -> list[tuple[int, int]]:
    """Return [(start, end), ...] half-open ranges that should not be split."""
    blocks: list[tuple[int, int]] = []
    in_fence = False
    line_start = 0
    block_start: int | None = None
    for line in body.splitlines(keepends=True):
        line_end = line_start + len(line)
        if _FENCE_RE.match(line):
            if not in_fence:
                in_fence = True
                block_start = line_start
            else:
                in_fence = False
                if block_start is not None:
                    blocks.append((block_start, line_end))
                block_start = None
        elif _is_table_row(line):
            if block_start is None:
                block_start = line_start
            # extend block
        else:
            if block_start is not None and not in_fence:
                blocks.append((block_start, line_start))
                block_start = None
        line_start = line_end
    if block_start is not None:
        blocks.append((block_start, line_start))
    return blocks


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if not stripped.startswith("|"):
        return False
    return stripped.endswith("|") or "|" in stripped[1:]


def _snap_to_block_end(blocks: list[tuple[int, int]], cursor: int, end: int) -> int:
    """If ``end`` falls inside an atomic block, push it to that block's end."""
    for start, stop in blocks:
        if start < end < stop:
            return stop
        if end <= start:
            break
    return end


__all__ = [
    "DEFAULT_OVERLAP_TOKENS",
    "DEFAULT_TARGET_TOKENS",
    "TOKEN_CHAR_RATIO",
    "Chunk",
    "chunk_markdown",
]
