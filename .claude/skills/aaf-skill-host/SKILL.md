---
name: aaf-skill-host
description: >-
  Contracts and implementation patterns for AAF's self-built Skill Host —
  the component that reads skills/ at runtime, matches skills to a query,
  injects them into LLM prompts, and safely executes skill-bundled scripts.
  Load this skill when creating or modifying any file under
  backend/core/skill_host/.
domain: engineering
triggers:
  - skill host
  - skill loader
  - skill matcher
  - skill injector
  - skill executor
  - backend/core/skill_host
version: "1.0.0"
---

# AAF Skill Host — Implementation Contract

Skill Host is the runtime replacement for Cursor/Claude Code's built-in skill loader. AAF ships its own so that any LLM backend can drive the same 15 academic skills without Cursor.

See `PLAN.md` §6 for the full spec.

## 1. Four modules and their boundaries

```
backend/core/skill_host/
├── loader.py      — scan disk, parse SKILL.md, build SkillRegistry
├── matcher.py     — score skills against a query, return top-k
├── injector.py    — compose skill body + scripts into prompt + tool specs
├── executor.py    — sandboxed subprocess run of skill scripts
└── registry.py    — thin façade: SkillHost = Loader+Matcher+Injector+Executor
```

**Key rule**: each module has exactly one responsibility. Never call an LLM from the Loader. Never touch the filesystem from the Matcher. Never execute scripts from the Injector.

## 2. SkillMeta contract

```python
class ScriptMeta(BaseModel):
    name: str                    # filename stem
    path: Path
    description: str             # from script docstring
    requires_network: bool       # from "# aaf:network" magic comment
    max_duration_s: int | None   # from "# aaf:timeout N" magic comment

class SkillMeta(BaseModel):
    name: str                    # must equal directory name
    path: Path
    description: str             # frontmatter "description"
    domain: str | None           # frontmatter "domain"
    triggers: list[str]
    version: str                 # frontmatter "version", default "0.0.0"
    requires: list[str]          # compatibility.requires
    network: str                 # none|optional|required
    exclusive: bool              # frontmatter "exclusive"
    scripts: list[ScriptMeta]
    references: list[Path]
    body: str                    # markdown after frontmatter
    description_embedding: list[float] | None = None
```

Parsing uses `python-frontmatter`. Unknown frontmatter fields **must be preserved** in a `raw_meta: dict` for forward compatibility.

## 3. Loader rules

- Scan `<root>/skills/*/SKILL.md`. A skill without `SKILL.md` is ignored (warn).
- For each skill, scan `<skill>/scripts/*.py` and parse docstrings.
- Compute embedding for `description` lazily (on first match call) — don't block startup if embedder is unavailable.
- Provide `reload(name)` for partial refresh and `watch()` for inotify/fsevents in dev mode.
- Thread-safe: the SkillRegistry uses a reader-writer lock; reloads acquire the writer lock.
- **Never raise on bad SKILL.md.** Log and skip.

## 4. Matcher algorithm

```python
score = 0.4 * kw_score + 0.6 * sem_score
```

where `kw_score` is normalised count of trigger-keyword hits in (query + context) and `sem_score` is cosine similarity between query embedding and description embedding.

Constraints:
- `top_k` default 3, `min_score` default 0.3.
- Two matched skills both declaring `exclusive: true` → keep only the higher-scoring one.
- If embedder is unavailable, fallback to pure keyword matching and log once.
- If nothing scores above `min_score`, return the built-in `general-assistant` skill as the single result.
- Never return duplicates.

## 5. Injector output contract

```python
class InjectionBundle(BaseModel):
    system_additions: str        # appended to system prompt
    tool_specs: list[ToolSpec]   # OpenAI-shaped tool list
    script_index: dict[str, Path]  # tool_name → absolute path
```

Tool naming: `{skill_name}__{script_stem}` (two underscores, no hyphens in the script stem part — rename the file instead).

Heuristic skills (L3) are joined as a dedicated `## ⚡ Learned strategies` subsection at the end of `system_additions`.

Token budget: if the combined bundle > 8000 tokens, drop skills by ascending score until under budget; log `injector.truncated`.

### 5.1 Progressive-injection invariant (do not break)

**Only matched skills' bodies enter `system_additions`.** Even though the
Loader holds the full body of every registered skill in memory, the
Injector must never render the body of a skill that wasn't returned by
the Matcher. This is the runtime guarantee for the user-facing
"progressive skill reading" requirement (PLAN §6.4.1).

If you change `_render_system` / `_render_skill` in `injector.py`,
re-run `backend/tests/integration/test_skill_progressive_load.py` —
those tests run against the real `./skills/` directory and assert:

1. `len(bundle.matched_skills) <= top_k` regardless of total skill count
2. matched skill bodies appear verbatim in the prompt
3. distinctive substrings from at least three unmatched skills are
   absent from the prompt
4. `system_additions` size at `top_k=3` is < 40% of the all-bodies
   concatenation

Adding a "tool catalog" or "available skills" summary section is fine
*as long as it lists names/descriptions only*. Putting any unmatched
skill's body into `system_additions` breaks the invariant — split the
new behaviour into a separate field on `InjectionBundle` instead.

## 6. Executor

- Default sandbox: subprocess with `resource.RLIMIT_AS` and `RLIMIT_CPU`, `cwd=data/papers/<task_id>/`, whitelisted env:
  - `AAF_WORKDIR`
  - `AAF_TASK_ID`
  - `AAF_LLM_ENDPOINT` (only if script declared `# aaf:uses-llm`)
- Timeout via ProcessGroup kill; no orphans.
- Capture stdout/stderr; stdout is returned to the LLM as `tool_result`. stderr goes to logs.
- Script outputs files to `data/papers/<task_id>/artifacts/`; Executor returns absolute paths in `ExecResult.artifacts`.
- No network by default. If `SkillMeta.network == "required"`, drop into a network-enabled cgroup (Docker profile); if `"optional"`, leave to host decision.
- Wrap stdout > 32KB in a temp file and return a summary + path instead.

## 7. How a script declares metadata

Scripts communicate metadata to the Executor via comments at the top:

```python
#!/usr/bin/env python3
"""One-line description — shown to the LLM as the tool description."""
# aaf:network optional
# aaf:timeout 240
# aaf:uses-llm
# aaf:args { "query": "string", "k": "int?" }

import argparse, json, sys
...

if __name__ == "__main__":
    ...
```

`aaf:args` defines a mini JSON Schema the Injector uses to build the tool spec. When omitted, the Loader falls back to inspecting `argparse.ArgumentParser` if the script uses one.

## 8. Public façade (what workflows actually use)

```python
class SkillHost:
    async def select_and_inject(
        self, query: str, *, context: str = "",
        top_k: int = 3, heuristics: list[HeuristicSkill] = None,
    ) -> InjectionBundle: ...

    async def call_tool(self, tool_name: str, args: dict, *,
                        task_id: str, timeout: int | None = None,
                        ) -> ExecResult: ...

    def list_skills(self) -> list[SkillMeta]: ...
    async def reload(self, name: str | None = None) -> None: ...
```

Workflows only ever touch `SkillHost`. Never import `Loader`/`Matcher`/`Injector`/`Executor` directly from `backend/workflows/`.

## 9. Testing

- Unit tests for Loader must cover: missing frontmatter, malformed YAML, scripts with missing docstring, UTF-8 BOM.
- Matcher tests use a fixed fixture of 5 fake skills to make scoring deterministic.
- Injector tests assert prompt exactly matches a snapshot.
- Executor tests run real subprocess against a `skills/echo-test/` fixture skill (shipped under `backend/tests/fixtures/skills/`).

## 10. Non-goals (do not implement)

- Loading skills from HTTP URLs.
- Hot-swapping running scripts.
- Multi-language scripts (only Python 3.11). Shell/other scripts go through `Tool Registry` instead.
