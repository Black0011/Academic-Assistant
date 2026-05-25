# backend/core/skill_host/AGENTS.md

The skill runtime. Reads `skills/*/SKILL.md`, matches them against a query,
injects them into prompts, and runs their scripts.

## Pieces

| File          | Responsibility                                                            |
| ------------- | ------------------------------------------------------------------------- |
| `loader.py`   | Walks `skills/`, parses frontmatter + body, returns `Skill` records.      |
| `matcher.py`  | Ranks skills against a query (frontmatter `triggers`, embeddings, domain).|
| `injector.py` | Renders matched skills into the planner prompt slot.                      |
| `executor.py` | Spawns the skill script in a subprocess with a budget.                    |
| `registry.py` | In-memory cache of skills loaded once at boot; hot-reload in dev only.    |

## Hard invariants

- The loader **must not** import skill scripts. Static parse only.
- The executor **must** isolate scripts (subprocess + per-call timeout). It
  already declines anything outside `skills/<name>/`.
- Discovery is filesystem-driven. We never hardcode a skill name in code.
- **M7.2**: any HTTP-driven write goes through a **staging dir**
  (`skills/_pending/`) → atomic mv → reload. Never edit `skills/<name>/` in
  place from a request handler. The host's existing invariants still hold;
  the API merely orchestrates filesystem ops + a `registry.reload(name)`.

## Adding capability vs. discipline

If you need a new way to *do* something, add an L1 skill (`skills/`).
If you need a new "always do X" or "never do Y" constraint, add an L2 rule
(`rules/`) and let `rule_engine.py` inject it. Don't add behaviour to the
host itself unless you're changing the runtime contract.

## Failure modes worth a check

| Symptom                                              | Where to look                                  |
| ---------------------------------------------------- | ---------------------------------------------- |
| Skill matches everything (low precision)             | `matcher.py` — too many overlapping triggers   |
| Skill not found at runtime                           | `loader.py` ignored it — frontmatter invalid?  |
| Script killed mid-run                                | `executor.py` budget exhausted; bump or fix    |
| Two skills register same name                        | Folder rename forgotten — see consistency check|

## Tests

Every change here needs:

- A unit test against `loader.py` with a fixture skill (good + bad
  frontmatter).
- A unit test against `matcher.py` showing the ranking on a known set.
- An integration test in `backend/tests/integration/test_app_workflows.py`
  that exercises the host end-to-end via a mock LLM.
