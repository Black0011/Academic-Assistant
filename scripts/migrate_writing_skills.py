#!/usr/bin/env python3
"""One-shot migration: copy 9 writing SKILLs from Academic-Agent v3.0.0 into AAF.

Source repo:   ~/Code/Academic-Agent/.cursor/skills/<name>/SKILL.md
Target repo:   ~/Code/academic-agent-framework/skills/<name>/SKILL.md

Each source SKILL already has the v2.2.5 DAG metadata (preconditions /
consumes / produces / failure_modes / downstream_skills) which AAF's
parse_frontmatter ignores harmlessly. We only need to inject the three
fields AAF's check_consistency.py validates: ``domain``, ``triggers``,
``version``. They're inserted right after the multi-line ``description``
block (before ``compatibility:``) so the order stays close to AAF's
existing skills.

Re-running is idempotent: if the target file already contains all three
required fields it is left untouched.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import structlog

from backend.core.errors import ConfigError

log = structlog.get_logger(__name__)

SRC_ROOT = Path("/Users/bizhiliang/Code/Academic-Agent/.cursor/skills")
DST_ROOT = Path("/Users/bizhiliang/Code/academic-agent-framework/skills")

# domain + triggers per SKILL — derived from each SKILL.md description text.
SKILLS: dict[str, dict[str, object]] = {
    "paper-orchestration": {
        "domain": "writing",
        "triggers": [
            "orchestrate paper",
            "整篇重写",
            "多 agent 分章",
            "redraft",
            "多节联动",
            "full draft",
            "论文整体规划",
        ],
    },
    "writing-chapters": {
        "domain": "writing",
        "triggers": [
            "write chapter",
            "写第 N 章",
            "write methodology",
            "write results",
            "逐章节写作",
            "chapter-by-chapter",
        ],
    },
    "evidence-driven-writing": {
        "domain": "writing",
        "triggers": [
            "write introduction",
            "write related work",
            "literature synthesis",
            "文献综述",
            "导言",
            "把这堆论文织成正文",
        ],
    },
    "experiment-results-planning": {
        "domain": "writing",
        "triggers": [
            "design experiment",
            "设计实验",
            "experimental protocol",
            "实验占位数据",
            "table schema",
            "figure manifest",
            "写 results",
        ],
    },
    "writing-core": {
        "domain": "writing",
        "triggers": [
            "去AI化",
            "polish prose",
            "remove AI flavour",
            "去除AI味",
            "正文太机械",
            "style audit",
        ],
    },
    "peer-review": {
        "domain": "revision",
        "triggers": [
            "投稿前自审",
            "pre-submission review",
            "审稿视角",
            "内审",
            "mock review",
            "顶会评审视角",
        ],
    },
    "verification": {
        "domain": "meta",
        "triggers": [
            "verify completion",
            "真的写完了吗",
            "are you sure",
            "verification report",
            "确认完成",
        ],
    },
    "brainstorming-research": {
        "domain": "ideation",
        "triggers": [
            "新论文",
            "我要开始写",
            "start a new paper",
            "论文初始化",
            "选题确定了",
        ],
    },
    "prompts-collection": {
        "domain": "meta",
        "triggers": [
            "polish prompt",
            "翻译 prompt",
            "润色 prompt",
            "去 AI 化 prompt",
            "摘要打磨 prompt",
            "give me a prompt",
        ],
    },
}

VERSION = "1.0.0"

# Matches a YAML frontmatter block: ``---\n…\n---\n``
FRONTMATTER_RE = re.compile(r"\A(---\s*\n)(.*?\n)(---\s*\n)", re.DOTALL)


def has_field(frontmatter_body: str, key: str) -> bool:
    """True iff ``key:`` appears at column 0 (top-level) of the YAML body."""
    return bool(re.search(rf"^{re.escape(key)}\s*:", frontmatter_body, re.MULTILINE))


def inject_required_fields(text: str, *, domain: str, triggers: list[str]) -> str:
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ConfigError("source has no YAML frontmatter")
    open_marker, body, close_marker = m.group(1), m.group(2), m.group(3)

    lines = [
        f"domain: {domain}",
        "triggers:",
        *[f"  - {t}" for t in triggers],
        f'version: "{VERSION}"',
    ]
    inject = "\n".join(lines) + "\n"

    # Skip injection if all 3 keys already present (idempotent re-runs).
    if all(has_field(body, k) for k in ("domain", "triggers", "version")):
        return text

    # Insert right BEFORE ``compatibility:`` if present (keeps the AAF
    # ordering convention from skills/literature-search/SKILL.md), else
    # append at the end of the body.
    compat_match = re.search(r"^compatibility\s*:", body, re.MULTILINE)
    if compat_match:
        new_body = body[: compat_match.start()] + inject + body[compat_match.start() :]
    else:
        new_body = body.rstrip("\n") + "\n" + inject

    return open_marker + new_body + close_marker + text[m.end() :]


def main() -> int:
    if not SRC_ROOT.is_dir():
        log.error("migrate.source_root_missing", path=str(SRC_ROOT))
        return 2

    DST_ROOT.mkdir(parents=True, exist_ok=True)
    migrated: list[dict[str, object]] = []
    for name, meta in SKILLS.items():
        src = SRC_ROOT / name / "SKILL.md"
        dst_dir = DST_ROOT / name
        dst = dst_dir / "SKILL.md"
        if not src.is_file():
            log.warning("migrate.skip_missing_source", skill=name, path=str(src))
            continue
        text = src.read_text(encoding="utf-8")
        try:
            adapted = inject_required_fields(
                text,
                domain=str(meta["domain"]),
                # mypy: SKILLS values are statically typed `object`; the schema
                # of each entry is enforced by the literal dict above.
                triggers=list(meta["triggers"]),  # type: ignore[arg-type]
            )
        except ConfigError as exc:
            log.error("migrate.adapt_failed", skill=name, reason=str(exc))
            continue
        dst_dir.mkdir(exist_ok=True)
        dst.write_text(adapted, encoding="utf-8")
        migrated.append(
            {
                "skill": name,
                "src_bytes": len(text.encode("utf-8")),
                "dst_bytes": len(adapted.encode("utf-8")),
            }
        )
        log.info(
            "migrate.skill_adapted",
            skill=name,
            src_bytes=migrated[-1]["src_bytes"],
            dst_bytes=migrated[-1]["dst_bytes"],
        )

    log.info(
        "migrate.summary",
        count=len(migrated),
        target_root=str(DST_ROOT),
        skills=[m["skill"] for m in migrated],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
