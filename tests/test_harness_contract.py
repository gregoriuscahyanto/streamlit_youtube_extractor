from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_agents_is_short_map_with_core_links():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 140
    for target in ["ARCHITECTURE.md", "docs/QUALITY.md", "docs/SECURITY.md", "docs/RELIABILITY.md"]:
        assert target in text


def test_harness_docs_exist():
    for rel in [
        "docs/PRODUCT.md",
        "docs/QUALITY.md",
        "docs/RELIABILITY.md",
        "docs/SECURITY.md",
        "docs/STATE_KEYS.md",
        "docs/DECISIONS.md",
    ]:
        assert (ROOT / rel).is_file(), rel


def test_user_data_is_ignored():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ["logs/", "captures/", "results/", ".streamlit/secrets.toml"]:
        assert pattern in text
