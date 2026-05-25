# backend/proposals/AGENTS.md

Gated change requests for the framework itself (M8.1).

This subsystem is the formal gate for any modification of code, skills,
rules, or configs that an LLM / agent / human wants to land. The gate is
a **state machine**, not a deploy hook — `apply` only stamps status and
writes the audit log. The diff is the proposer's input; humans or CI
take it from there.

## Why gated, not auto-applied

We deliberately don't write files from the API:

- safety: an LLM-written proposal can't suddenly mutate `backend/`
- reviewability: humans or CI consume the unified-diff field
- composability: `SkillAdmin` (M7.2) already handles file-level skill
  edits with staging + atomic + rollback; `Proposal.apply` is the
  orthogonal "approval" axis

To extend later: add a `apply_strategy` enum (`record_only`, `skill_admin`,
`whitelisted_path`) and dispatch to the matching backend.

## Layout

```
backend/proposals/
├── __init__.py        ← exports models + stores
├── models.py          ← Proposal, AuditEvent, status / risk / kind enums
└── store.py           ← ProposalStore Protocol, InMemory + Yaml impls
```

The HTTP surface lives at `backend/api/routers/proposals.py`. Wire-up
goes through `AppState.proposals`; the lifespan in `backend/app.py`
picks the implementation based on `settings.proposals_backend`.

## State machine

| from       | action     | to          |
| ---------- | ---------- | ----------- |
| draft      | submit     | pending     |
| draft      | withdraw   | withdrawn   |
| pending    | approve    | approved    |
| pending    | reject     | rejected    |
| pending    | withdraw   | withdrawn   |
| approved   | apply      | applied     |
| approved   | withdraw   | withdrawn   |
| anything else | *       | **409**     |

Illegal transitions raise `IllegalTransitionError`; the router converts
to HTTP 409. Don't let any other layer "fix up" the status outside the
store — the audit log is the contract.

## Audit log

Every state change AND every `PATCH` writes a `ProposalAuditEvent`. The
event records `actor` (user_id or `"system"`), `action`, optional
`notes`, and an immutable timestamp. Don't truncate or rewrite past
entries — append only.

## When you extend

1. New status / action: update `_TRANSITIONS` in `store.py`, the
   `ProposalStatus` / `ProposalAction` enums in `models.py`, *and* the
   matching SDK + frontend mirrors. Add a unit test for the new edge.
2. New `apply` backend (e.g. "auto-apply skills/ proposals"):
   - **Don't** re-implement file writes here. Reach for `SkillAdmin` or
     a future `FrameworkPatcher`.
   - Keep the gate behaviour separable: `apply` should still be safe to
     replay because the store stamps `applied_at` once.
3. Storage: write atomically (`tmp + os.replace`); the `YamlProposalStore`
   already does this.

## Tests

- `backend/tests/unit/test_proposals_store.py` — covers the store
  protocol (both impls), happy paths, illegal transitions, and the
  audit log invariants.
- `backend/tests/integration/test_app_proposals.py` — covers the router,
  open-mode auth, 409 on illegal transitions, list filtering.
