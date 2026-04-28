.PHONY: install-dev test lint ci run

install-dev:
	python -m pip install --upgrade pip
	python -m pip install -r requirements-dev.txt

test:
	python -m pytest

lint:
	python scripts/harness_lint.py
	ruff check .

ci: lint test
	python -m compileall .

run:
	streamlit run app.py
