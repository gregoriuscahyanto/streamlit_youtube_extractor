# AGENTS.md

This repository is optimized for agent-assisted engineering. Keep this file short; it is the map, not the manual.

## Start here
- Product purpose: `docs/PRODUCT.md`
- Architecture and boundaries: `ARCHITECTURE.md`
- Compact context map: `docs/CONTEXT.md` and `python scripts/agent_context.py`
- Reliability and observability rules: `docs/RELIABILITY.md`
- Security and secrets rules: `docs/SECURITY.md`
- Quality gates and test commands: `docs/QUALITY.md`
- Active execution plans: `docs/exec-plans/active/`

## Local commands
Use the same commands locally and in CI:

```bash
python -m pip install -r requirements-dev.txt
python scripts/agent_context.py
python scripts/run_tests_rtk.py
python scripts/harness_lint.py
python -m py_compile app.py app_tabs/setup_tab.py app_tabs/sync_tab.py app_tabs/mat_selection_tab.py app_tabs/roi_setup_tab.py app_tabs/audio_tab.py
```

## Non-negotiable invariants
- Do not commit secrets, user videos, generated MAT/JSON results, logs, or local caches.
- Keep UI code in `app.py` and `app_tabs/`; keep reusable logic in backend modules.
- New behavior needs a regression test or a documented reason in the execution plan.
- Prefer small, reviewable changes. Update docs when behavior or architecture changes.
- Use repository-local knowledge instead of relying on chat history.

## Agent workflow
1. Read the relevant docs above.
2. Make the smallest coherent change.
3. Run tests/lints.
4. Record architectural decisions in `docs/DECISIONS.md` when they affect future work.
5. Add or update an execution plan for multi-step work.
