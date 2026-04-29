# Architecture Decisions

## 2026-04-28: Repository-local harness knowledge

Decision: add `AGENTS.md`, architecture docs, quality docs, and executable repo checks.

Reason: agentic work needs a small stable entry point plus deeper repository-local truth sources. This avoids relying on stale chat context and makes future changes mechanically checkable.

## 2026-04-29: Compact agent context script

Decision: add `docs/CONTEXT.md` and `scripts/agent_context.py`.

Reason: future agents should start from a compact map instead of spending context on large implementation files, generated results, logs, or binary MATLAB artifacts.

## 2026-04-29: RTK-first test runner

Decision: add `scripts/run_tests_rtk.py` and make it the default `make test` command.

Reason: RTK reduces command-output tokens and keeps test feedback compact; the script also keeps a deterministic fallback to direct pytest when RTK is unavailable.

Consequence: future architectural or workflow changes should update docs and tests together with code.
