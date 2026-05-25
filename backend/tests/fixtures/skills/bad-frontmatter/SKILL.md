---
name: bad-frontmatter
description: "unterminated string
triggers:
  - whatever
---

# Bad frontmatter

The frontmatter YAML above is intentionally malformed so tests can assert
that the Loader logs and skips it rather than crashing.
