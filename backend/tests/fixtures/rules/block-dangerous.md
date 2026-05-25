---
name: block-dangerous
description: Reject any action explicitly flagged as dangerous.
scope: all
priority: 100
enforcement: hook
hook: backend.tests.fixtures.rule_hooks.block_dangerous
---

# Block dangerous actions

Hook rule: aborts any action whose ``payload.dangerous == True``.
