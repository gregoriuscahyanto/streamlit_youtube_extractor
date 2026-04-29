# Agent Context Map

Use this page when a future agent needs a compact starting point.

## First command

```bash
python scripts/agent_context.py
```

The script prints the repository map, key docs, tab ownership, and high-signal test commands without dumping large files into context.

## Reading order

1. `AGENTS.md` for workflow rules.
2. `ARCHITECTURE.md` for ownership boundaries.
3. `docs/STATE_KEYS.md` before changing cross-tab Streamlit state.
4. The specific `app_tabs/*.py` renderer or backend module touched by the task.
5. The narrow regression test that matches the task.

Default test runner:

```bash
python scripts/run_tests_rtk.py
```

This runs tests through RTK (`rtk test "<python -m pytest ...>"`) when RTK is available and falls back to direct pytest otherwise.

Avoid reading generated data, logs, R2 mounts, MAT files, and full OCRExtractor sources unless the task explicitly needs them.
