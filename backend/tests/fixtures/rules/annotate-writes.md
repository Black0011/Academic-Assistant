---
name: annotate-writes
description: Annotate every write_file action before execution.
scope: all
priority: 50
enforcement: hook
hook: backend.tests.fixtures.rule_hooks.annotate_write
---

# Annotate writes

Hook rule: adds ``annotated=True`` to every ``write_file`` payload. Used
to verify the hook chain mutates actions.
