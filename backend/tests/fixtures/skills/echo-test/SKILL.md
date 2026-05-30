---
name: echo-test
description: >-
  Test-only skill: echoes the input message back verbatim and writes it to
  an artifact file. Used by Skill Host unit tests.
domain: test
triggers:
  - echo
  - echo message
  - test echo
version: "1.0.0"
---

# Echo Test Skill

A minimal skill used only in the Skill Host test suite.

## Tools

- `echo`: return the `message` argument verbatim and write it to
  `artifacts/echo.txt`.
