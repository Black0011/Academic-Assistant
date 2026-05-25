# skills/AGENTS.md

L1 **Capability Skills** — what the agent *can do*. Each skill is a folder
with at least a `SKILL.md` (frontmatter + body); optionally `script.py`,
`templates/`, fixtures.

## Conventions

- Folder name == skill name == frontmatter `name`. All kebab-case.
- One skill = one capability. If you're adding a second top-level
  responsibility, split the folder.
- Pure content, no Python imports. The skill host loads SKILL.md as text
  and resolves scripts via the executor.

## Required frontmatter

Enforced by `scripts/check_consistency.py` (`Fix:` hints inline). Minimum:

```yaml
---
name: literature-search           # must equal folder name
description: >-
  One-paragraph capability summary, ending with "Use when …".
domain: research                  # one of: research | writing | revision |
                                  #          rebuttal | survey | presentation |
                                  #          ideation | meta
triggers:                         # ≥1, free-form strings the matcher hashes
  - search papers
  - 文献检索
version: "1.0.0"                  # SemVer string
---
```

Optional (declare when present):

```yaml
compatibility:
  requires: ["python-3.9"]
inputs: { … }                     # JSON-Schema-ish; the executor enforces
outputs: { … }
```

## Body

Markdown. Be concrete. The host injects this into the planner prompt — long
prose hurts. Prefer:

- A 3–5-step happy path (numbered list)
- Decision tables (when X, do Y)
- Templates and snippets (with placeholders)

Avoid:

- "Best practices" lecture paragraphs
- Restating what `domain` already implies
- Anything that should be a check (move it to `scripts/check_consistency.py`)

## Scripts

If your skill ships a script, put it next to SKILL.md:

```
skills/<name>/
├── SKILL.md
└── script.py        # entry point: `def run(args: dict) -> dict:`
```

`backend/core/skill_host/executor.py` runs scripts in a subprocess with a
budget. Scripts must be pure-Python stdlib unless declared in
`compatibility.requires`.

## Adding a skill — checklist

1. `mkdir skills/my-skill && cp skills/literature-search/SKILL.md skills/my-skill/SKILL.md`
2. Edit frontmatter. Folder name **must** match `name`.
3. Run `make consistency` — fix any `Fix:` hints.
4. Add a fixture-based test under `backend/tests/unit/test_skill_host_*.py`
   if the skill has a script.
5. Commit. The discovery layer picks it up at next app boot.
