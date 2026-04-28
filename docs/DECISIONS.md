# Architecture Decisions

## 2026-04-28: Repository-local harness knowledge

Decision: add `AGENTS.md`, architecture docs, quality docs, and executable repo checks.

Reason: agentic work needs a small stable entry point plus deeper repository-local truth sources. This avoids relying on stale chat context and makes future changes mechanically checkable.

Consequence: future architectural or workflow changes should update docs and tests together with code.
