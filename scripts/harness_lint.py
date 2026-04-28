"""Repository-structure checks for agentic engineering workflows."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = [
    "AGENTS.md",
    "ARCHITECTURE.md",
    "docs/PRODUCT.md",
    "docs/QUALITY.md",
    "docs/RELIABILITY.md",
    "docs/SECURITY.md",
    "docs/STATE_KEYS.md",
    "docs/DECISIONS.md",
    "requirements-dev.txt",
    "pyproject.toml",
]
REQUIRED_DIRS = [
    "docs/design-docs",
    "docs/exec-plans/active",
    "docs/exec-plans/completed",
    "docs/references",
    "tests",
]
FORBIDDEN_TRACKED_PATTERNS = (
    "logs/",
    "captures/",
    "results/",
    "r2_mount/",
    ".streamlit/secrets.toml",
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> int:
    errors: list[str] = []

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            errors.append(f"missing required file: {rel}")
    for rel in REQUIRED_DIRS:
        if not (ROOT / rel).is_dir():
            errors.append(f"missing required directory: {rel}")

    if (ROOT / "AGENTS.md").is_file():
        agents = _read("AGENTS.md")
        for rel in ["ARCHITECTURE.md", "docs/QUALITY.md", "docs/SECURITY.md", "docs/RELIABILITY.md"]:
            if rel not in agents:
                errors.append(f"AGENTS.md must link to {rel}")
        if len(agents.splitlines()) > 140:
            errors.append("AGENTS.md is too long; keep it as a map, not a manual")

    if (ROOT / ".gitignore").is_file():
        gitignore = _read(".gitignore")
        for pattern in FORBIDDEN_TRACKED_PATTERNS:
            if pattern not in gitignore:
                errors.append(f".gitignore must ignore {pattern}")

    if errors:
        print("Harness lint failed:")
        for err in errors:
            print(f"- {err}")
        return 1
    print("Harness lint passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
