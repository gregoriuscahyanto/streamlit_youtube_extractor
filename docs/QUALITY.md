# Quality Gates

## Required checks

```bash
python scripts/run_tests_rtk.py
python scripts/harness_lint.py
python scripts/agent_context.py
python -m py_compile app.py app_tabs/setup_tab.py app_tabs/sync_tab.py app_tabs/mat_selection_tab.py app_tabs/roi_setup_tab.py app_tabs/audio_tab.py
```

`ruff` is useful when installed, but it is optional for this legacy codebase until the existing style debt is cleaned up.

## Test policy
- Pure utility changes need unit tests.
- UI regressions should be covered with Streamlit AppTest or focused source-level tests when AppTest cannot exercise the browser path.
- Cloud/R2 behavior should be tested with fakes or recorded shape fixtures, not live credentials.
- MAT compatibility fixes should include at least one fixture-style test for the expected field path.

## Definition of done
- Checks pass locally.
- Any new state key or persistent field is documented.
- Any new external dependency is justified in README or `docs/DECISIONS.md`.
- Any new agent workflow or repository rule is discoverable from `AGENTS.md` or `docs/CONTEXT.md`.
