# Harness Engineering Patch

This ZIP is an overlay for `gregoriuscahyanto/streamlit_youtube_extractor`.
Copy the files into the repository root, then run:

```bash
python -m pip install -r requirements-dev.txt
python scripts/harness_lint.py
python -m pytest
python -m compileall .
```

What changed:
- Added short `AGENTS.md` as the agent entrypoint.
- Added repository-local system-of-record docs under `docs/`.
- Added mechanical harness linting via `scripts/harness_lint.py`.
- Added CI workflow for tests, syntax checks, and harness checks.
- Added development dependency file, Ruff config, EditorConfig, Git attributes, and stronger ignores for user data.

The patch intentionally does not rewrite the application logic. It makes future agent changes safer, more readable, and easier to validate.
