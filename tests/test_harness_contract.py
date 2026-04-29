from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_agents_is_short_map_with_core_links():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 140
    for target in ["ARCHITECTURE.md", "docs/CONTEXT.md", "docs/QUALITY.md", "docs/SECURITY.md", "docs/RELIABILITY.md"]:
        assert target in text


def test_harness_docs_exist():
    for rel in [
        "docs/PRODUCT.md",
        "docs/CONTEXT.md",
        "docs/QUALITY.md",
        "docs/RELIABILITY.md",
        "docs/SECURITY.md",
        "docs/STATE_KEYS.md",
        "docs/DECISIONS.md",
    ]:
        assert (ROOT / rel).is_file(), rel


def test_rtk_test_runner_is_declared():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    quality = (ROOT / "docs" / "QUALITY.md").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "scripts/run_tests_rtk.py" in agents
    assert "scripts/run_tests_rtk.py" in quality
    assert "python scripts/run_tests_rtk.py" in makefile
    assert (ROOT / "scripts" / "run_tests_rtk.py").is_file()


def test_user_data_is_ignored():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ["logs/", "captures/", "results/", "r2_mount/", ".streamlit/secrets.toml"]:
        assert pattern in text


def test_harness_lint_checks_for_mojibake_rule():
    lint = (ROOT / "scripts" / "harness_lint.py").read_text(encoding="utf-8")
    assert "_check_no_mojibake" in lint
    assert "contains likely mojibake" in lint
