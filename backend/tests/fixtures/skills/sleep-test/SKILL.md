---
name: sleep-test
description: >-
  Test-only skill: sleeps for N seconds. Used to exercise the executor's
  timeout path.
domain: test
triggers:
  - sleep
  - test timeout
version: "1.0.0"
exclusive: true
---

# Sleep Test Skill

Blocks for `seconds` seconds (default 30). The Skill Host executor kills
it via SIGKILL to test the timeout code path.
