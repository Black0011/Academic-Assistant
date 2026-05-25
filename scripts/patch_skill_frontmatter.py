#!/usr/bin/env python3
"""
M0 helper: patch every skills/*/SKILL.md to ensure frontmatter has
`domain` and `triggers` fields (idempotent, safe).

This script is ONE-OFF tooling for the M0 migration; after M0 it can be
kept as a reference or deleted.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"

MAPPING: dict[str, dict] = {
    "autoresearch": {
        "domain": "research",
        "triggers": ["research", "literature survey", "调研", "综述"],
    },
    "literature-search": {
        "domain": "research",
        "triggers": ["search papers", "文献检索", "find related work"],
    },
    "paper-reading": {
        "domain": "research",
        "triggers": ["read paper", "精读", "structured reading"],
    },
    "download-paper": {
        "domain": "research",
        "triggers": ["download paper", "download pdf", "下载论文"],
    },
    "survey-writing": {
        "domain": "survey",
        "triggers": ["write survey", "综述写作", "literature review"],
    },
    "survey-table": {
        "domain": "survey",
        "triggers": ["survey table", "comparison table", "对比表"],
    },
    "paper-writing": {
        "domain": "writing",
        "triggers": ["write paper", "draft section", "论文写作", "paper outline"],
    },
    "paper-revision": {
        "domain": "revision",
        "triggers": ["revise paper", "improve paper", "论文修改", "reviewer comments"],
    },
    "rebuttal-writer": {
        "domain": "rebuttal",
        "triggers": ["rebuttal", "reviewer response", "审稿回应"],
    },
    "paper-presentation": {
        "domain": "presentation",
        "triggers": ["present paper", "paper talk", "论文汇报", "make slides"],
    },
    "presentation-maker": {
        "domain": "presentation",
        "triggers": ["create presentation", "slides", "演讲稿"],
    },
    "pptx": {"domain": "presentation", "triggers": ["pptx", "powerpoint", "python-pptx"]},
    "brainstorming": {"domain": "meta", "triggers": ["brainstorm", "research ideas", "头脑风暴"]},
    "creative-thinking": {
        "domain": "meta",
        "triggers": ["creative thinking", "novel angle", "创新"],
    },
    "skill-creator": {"domain": "meta", "triggers": ["create skill", "new skill", "自造 skill"]},
}


FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def patch_file(path: Path, domain: str, triggers: list[str]) -> bool:
    text = path.read_text(encoding="utf-8")
    m = FM_RE.match(text)
    if not m:
        print(f"  [skip] no frontmatter: {path}")
        return False
    fm_body = m.group(1)
    changed = False

    if "\ndomain:" not in ("\n" + fm_body):
        fm_body = fm_body.rstrip() + f"\ndomain: {domain}"
        changed = True

    if "\ntriggers:" not in ("\n" + fm_body):
        trig_yaml = "\ntriggers:\n" + "\n".join(f"  - {t}" for t in triggers)
        fm_body = fm_body.rstrip() + trig_yaml
        changed = True

    if "\nversion:" not in ("\n" + fm_body):
        fm_body = fm_body.rstrip() + '\nversion: "1.0.0"'
        changed = True

    if not changed:
        print(f"  [ok]   already patched: {path.parent.name}")
        return False

    new_text = f"---\n{fm_body.rstrip()}\n---\n" + text[m.end() :]
    path.write_text(new_text, encoding="utf-8")
    print(f"  [done] patched: {path.parent.name}")
    return True


def main() -> int:
    if not SKILLS_DIR.exists():
        print(f"skills dir not found: {SKILLS_DIR}", file=sys.stderr)
        return 2

    patched = 0
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            print(f"  [warn] no SKILL.md in {skill_dir.name}")
            continue
        cfg = MAPPING.get(skill_dir.name)
        if not cfg:
            print(f"  [warn] no mapping entry for {skill_dir.name} (skipped)")
            continue
        if patch_file(skill_md, cfg["domain"], cfg["triggers"]):
            patched += 1

    print(f"\nPatched {patched} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
