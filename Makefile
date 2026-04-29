.PHONY: install-dev test lint ci run

install-dev:
	python -m pip install --upgrade pip
	python -m pip install -r requirements-dev.txt

test:
	python scripts/run_tests_rtk.py

lint:
	python scripts/harness_lint.py
	python scripts/agent_context.py

ci: lint test
	python -m py_compile app.py app_tabs/setup_tab.py app_tabs/sync_tab.py app_tabs/mat_selection_tab.py app_tabs/roi_setup_tab.py app_tabs/track_analysis_tab.py app_tabs/audio_tab.py

run:
	streamlit run app.py
