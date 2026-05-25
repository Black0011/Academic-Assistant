# Writing your own skill

AAF separates the agent's "what it knows how to do" from the model
itself. This document walks you through adding each layer.

| Layer | Folder       | What it captures                                                | When to add one                                          |
|-------|--------------|-----------------------------------------------------------------|----------------------------------------------------------|
| L1    | `skills/`    | A capability — "how to do X". Markdown body + optional script.  | The agent gets a new ability (search arXiv, run BibTeX). |
| L2    | `rules/`     | A discipline — "always Y, never Z, when ambiguous ask".         | Behaviour the model must follow regardless of skill.     |
| L3    | (runtime)    | A learned strategy block (mutable, evolved by past runs).       | Don't hand-author; the system writes them.               |

Both L1 and L2 are plain markdown with YAML frontmatter, loaded via the
Skill Host (`backend/core/skill_host/`). They contain *no Python
imports* — the runtime treats them as content. A capability's optional
`script.py` runs in an isolated subprocess managed by `SkillExecutor`.

## 0. Mental model

The Planner picks **rules** that always apply (`alwaysApply: true`)
and the top-k **skills** whose triggers match the user query, then
injects them into the system prompt. The Executor runs scripts the
model decides to call. Heuristics are appended to the prompt as a
"strategies that worked here recently" section.

If you find yourself documenting *how* to perform a task → that's a
**skill**. If you're documenting *constraints* the agent must respect
→ that's a **rule**. If neither — you probably want a workflow
(`backend/workflows/`) or a static check (`scripts/check_consistency.py`).

## 1. Add a capability skill (L1)

```
skills/
└── citation-builder/
    ├── SKILL.md          # required
    ├── script.py         # optional
    ├── templates/        # optional, anything you reference from SKILL.md
    └── fixtures/         # optional, only used by tests
```

**Folder name === skill name === frontmatter `name`.** All kebab-case.
The consistency check (`scripts/check_consistency.py`) fails the build
if these drift.

### 1.1 Frontmatter

Required, enforced mechanically:

```yaml
---
name: citation-builder
description: >-
  Builds APA / IEEE / BibTeX citations from a paper card. Use when the
  user pastes a citation chunk and asks for a normalised entry.
domain: writing                # research | writing | revision | rebuttal | survey | presentation | ideation | meta
triggers:                      # ≥1, free-form, the matcher hashes them
  - cite this paper
  - bibtex
  - 引用格式
version: "1.0.0"
---
```

Optional fields the runtime reads:

```yaml
network: optional              # none | optional | required (executor will refuse to start the script if `none` and a hint says network needed)
exclusive: false               # true → don't combine with other skills in the same prompt
requires:                      # human-readable preconditions; not enforced
  - python>=3.10
references:                    # extra files to load alongside SKILL.md
  - templates/apa.tmpl
  - templates/ieee.tmpl
```

The full schema lives in `backend/core/skill_host/types.py`
(`SkillMeta`).

### 1.2 Body

Markdown — short, scannable, opinionated. The Planner injects this into
the prompt; verbose prose costs tokens and hurts performance. Prefer:

- A 3–5 step happy path (numbered list)
- Decision tables (`when X, do Y`)
- Concrete templates with placeholders

Skip:

- Tutorial paragraphs ("First we will…")
- Restating what `domain` already implies
- Anything that should be a **check** (move to
  `scripts/check_consistency.py`)

Example body:

```markdown
# Citation builder

## Decision table

| Source format          | Tool                                | Output      |
|------------------------|-------------------------------------|-------------|
| arXiv URL or arxiv id  | `script.py mode=arxiv`              | bibtex+apa  |
| DOI                    | `script.py mode=doi`                | bibtex+apa  |
| Free-form chunk        | `script.py mode=parse`              | best-guess  |

## Templates

- APA: see `templates/apa.tmpl`
- IEEE: see `templates/ieee.tmpl`
```

### 1.3 Script

If the skill needs to do something non-trivial (file IO, parsing, web
fetching), drop a `script.py` in the same folder. The Executor runs
`python script.py` in a subprocess with:

- `cwd = <workdir>/papers/<task_id>/`
- A whitelisted env (`PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`,
  `PYTHONIOENCODING`)
- The arguments as one JSON blob on stdin
- A timeout (default 120 s, override per-script via magic comment)

Magic comments at the top of the script declare runtime hints:

```python
#!/usr/bin/env python3
# aaf:network optional
# aaf:timeout 60
# aaf:uses-llm
# aaf:args {"paper_id": "string", "format": "string"}
"""Build a citation entry."""

from __future__ import annotations

import json
import sys


def main() -> None:
    args = json.loads(sys.stdin.read() or "{}")
    paper_id = args.get("paper_id", "")
    fmt = args.get("format", "apa")
    if not paper_id:
        sys.stderr.write("paper_id is required\n")
        sys.exit(2)

    # …do the work…
    print(json.dumps({"paper_id": paper_id, "format": fmt, "entry": "…"}))


if __name__ == "__main__":
    main()
```

Recognised hints (parsed from the first 30 lines):

| Magic line                       | Effect                                                  |
|----------------------------------|---------------------------------------------------------|
| `# aaf:network none`             | Executor refuses outbound network in the subprocess.    |
| `# aaf:network optional`         | Network is allowed; tools may degrade gracefully.       |
| `# aaf:network required`         | Network is mandatory; offline runs short-circuit error. |
| `# aaf:timeout <seconds>`        | Override the default 120 s timeout.                     |
| `# aaf:uses-llm`                 | Marks the script as making LLM calls (cost surfaced).   |
| `# aaf:args {"k": "type", …}`    | JSON args schema (used by the planner for type hints).  |

Stdout is captured (32 KB inline; the rest goes into an artifact file
under `<task_workdir>/artifacts/`). Anything written under
`<task_workdir>/artifacts/` is collected automatically and surfaced via
`ExecResult.artifacts`.

### 1.4 Test

Every L1 skill that ships a script needs a unit test under
`backend/tests/unit/test_skill_host_*.py`:

```python
import pytest
from backend.core.skill_host.executor import SkillExecutor

@pytest.mark.asyncio
async def test_citation_builder_arxiv(tmp_path):
    executor = SkillExecutor(workdir_root=tmp_path)
    result = await executor.run(
        script_path=Path("skills/citation-builder/script.py"),
        args={"paper_id": "2310.06770", "format": "apa"},
        tool_name="citation-builder",
        task_id="t-1",
    )
    assert result.ok
    assert "Author" in result.stdout
```

For workflows that consume your skill, also add an integration test in
`backend/tests/integration/test_app_workflows.py` posting to
`/api/workflows/<name>/run` with a tiny budget.

### 1.5 Checklist

```
☐ Folder name == frontmatter name (kebab-case)
☐ One skill = one capability (split if you want two)
☐ Frontmatter passes `make consistency`
☐ Body uses lists/tables, not paragraphs
☐ Optional script declares magic comments
☐ Unit test for the script (if any)
☐ Integration test if a workflow uses it
```

## 2. Add a behaviour rule (L2)

```
rules/
└── cite-on-revision.md       # one rule per file
```

### 2.1 Frontmatter

```yaml
---
description: Cite every claim added during a revision pass.
alwaysApply: false
triggers:
  - revise paper
  - 修改稿
domain: revision               # optional scope hint
priority: 50                   # 0..100, lower wins ties
---
```

When `alwaysApply: true`, omit `triggers:` (the rule is included
unconditionally). When `alwaysApply: false`, `triggers:` is required.

### 2.2 Body

Plain markdown. Bullets > paragraphs. The agent skims; pithy rules win.

```markdown
# Cite on revision

- Every new fact, number, or method comparison added in revision must
  carry an inline citation.
- If you don't have a confident citation, mark the claim
  `[NEEDS CITATION]` instead of dropping it.
- Don't rewrite the bibliography from scratch — append new entries.
```

### 2.3 When NOT to use a rule

| Need                                           | Lives in                                            |
|------------------------------------------------|-----------------------------------------------------|
| Behaviour the *model* must follow              | New rule here.                                      |
| Static repository invariant                    | `scripts/check_consistency.py`                      |
| Limit the executor itself can enforce          | `SkillExecutor` magic comments / sandbox            |
| Cross-cutting cost / time guard                | `backend/core/budget.py`                            |

If a rule keeps getting violated, that's a signal to mechanise it
(promote to a static check or a budget). Don't add the same rule
twice with stronger wording.

### 2.4 Test

Add a unit test asserting the rule fires when expected
(`backend/tests/unit/test_rule_engine_*.py`):

```python
@pytest.mark.asyncio
async def test_cite_on_revision_fires_for_revise_keyword(rule_engine):
    rules = await rule_engine.match("revise paper", domain="revision")
    assert any(r.name == "cite-on-revision" for r in rules)
```

### 2.5 Checklist

```
☐ One rule per file
☐ Required frontmatter present (alwaysApply or triggers)
☐ Body uses bullets / decision tables
☐ Unit test asserts firing condition
☐ `make consistency` passes
```

## 3. Heuristics (L3) — read, don't author

Heuristics are written by the runtime via the Evolver
(`backend/memory/paper_memory_evolver.py`) every time a workflow
finishes with a verdict. They live in the `heuristic` memory store
(YAML by default) and bear:

- a strategy block (planning hints, search tips, evaluation criteria),
- success/failure counters,
- a `frozen` flag,
- a `source_run_id` so they're rollback-able.

You inspect or curate them via the Memory Explorer in the frontend, or
the `/api/heuristics` endpoints (matched/freeze/unfreeze/bump). Don't
hand-write heuristic files — that defeats the purpose. If you find
yourself wanting to: write a **rule** instead.

## 4. Common pitfalls

| Symptom                                      | Likely cause                                  | Fix                                                      |
|----------------------------------------------|-----------------------------------------------|----------------------------------------------------------|
| Skill doesn't appear in `client.workflows.list_all()` outputs | Folder name vs frontmatter name mismatch      | Rename one; rerun `make consistency`.                     |
| Script never runs                             | `network: required` but Settings forbids net  | Set `AAF_ALLOW_NETWORK=true` or change the magic comment. |
| Skill body is huge but ignored                | Planner truncates to a token budget           | Tighten the body; offload templates to `references:`.     |
| Rule fires for every prompt                   | `alwaysApply: true`                           | Switch to `false` + add `triggers`.                       |
| Heuristic keeps re-promoting a bad strategy   | Evolver counted false positives               | Freeze it from the Memory Explorer (`POST .../freeze`).   |

## 5. Where to look next

- `skills/AGENTS.md` — the canonical convention map for skills.
- `rules/AGENTS.md` — the canonical convention map for rules.
- `backend/core/skill_host/AGENTS.md` (if present) — runtime details
  for the Skill Host.
- `backend/workflows/AGENTS.md` — how workflows consume skills/rules.
- `scripts/check_consistency.py` — the mechanical gate; read it once
  to know what failure messages mean.
