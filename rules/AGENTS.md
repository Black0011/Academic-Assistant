# rules/AGENTS.md

L2 **Behaviour Rules** — discipline the agent must follow regardless of skill.
Rules are markdown with YAML frontmatter, loaded by the rule engine at
prompt-composition time.

Rules are **constraints**, not capabilities. If you find yourself describing
*how to do a thing*, that's a skill — go to `skills/AGENTS.md`. If you're
describing *what must always be true / never happen*, you're in the right
place.

## Required frontmatter

Enforced mechanically:

```yaml
---
description: One-line summary the matcher uses for ranking.
alwaysApply: true                # or false (then `triggers:` is required)
---
```

When `alwaysApply: false`:

```yaml
---
description: Cite every claim in revision drafts
alwaysApply: false
triggers:
  - revise paper
  - 修改稿
domain: revision                 # optional scope hint
priority: 50                     # 0..100, lower wins ties
---
```

## Body

Plain markdown. Keep each rule small and atomic. Multi-rule files are
banned by the consistency check — split them.

Good rule body:

```markdown
# Knowledge protection

- Never delete a knowledge card; mark `archived: true` instead.
- Never overwrite a synthesis note in place; bump `version` and append.
- On user-reported data loss, run the rollback procedure in
  `backend/api/routers/memory.py:rollback_run`.
```

Bad: a paragraph essay restating principles. The agent skims; bullets win.

## When to add vs. promote to a check

| Need                                          | Where it goes                                |
| --------------------------------------------- | -------------------------------------------- |
| Behaviour the *model* must follow             | New rule here                                |
| Static repository invariant                   | `scripts/check_consistency.py`               |
| Rule the executor itself can enforce          | `backend/core/skill_host/executor.py` budget / sandbox |
| Cross-cutting cost / time guard               | `backend/core/budget.py`                     |

If a rule keeps getting violated, that's a signal you should mechanise it
instead. Promote to a check.

## Adding a rule — checklist

1. New file: `rules/<short-kebab>.md`. One rule per file.
2. Fill required frontmatter. Run `make consistency`.
3. If the rule references a function, link it: ``[`memory.rollback`](…)``.
4. Add a unit test asserting the rule fires when expected
   (`backend/tests/unit/test_rule_engine_*.py`).
