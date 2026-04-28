# Quality Gates

## Required checks

```bash
python -m pytest
python scripts/harness_lint.py
python -m compileall .
```

## Test policy
- Pure utility changes need unit tests.
- UI regressions should be covered with Streamlit AppTest or focused source-level tests when AppTest cannot exercise the browser path.
- Cloud/R2 behavior should be tested with fakes or recorded shape fixtures, not live credentials.
- MAT compatibility fixes should include at least one fixture-style test for the expected field path.

## Definition of done
- Checks pass locally.
- Any new state key or persistent field is documented.
- Any new external dependency is justified in README or `docs/DECISIONS.md`.
