"""RTK regression checks for Cloud DB auto-connect retry behavior."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_app_has_retry_helper_with_three_attempts_default():
    # Ensure retry helper exists and defaults to 3 attempts.
    txt = _read("app.py")
    assert "def _connect_r2_with_retry(" in txt
    assert "max_attempts: int = 3" in txt
    assert "for i in range(attempts):" in txt
    assert "time.sleep(max(0.0, float(delay_s)))" in txt


def test_auto_connect_uses_retry_helper():
    # Auto-connect should use retry wrapper instead of direct single call.
    txt = _read("app.py")
    assert "_connect_r2_with_retry(acc, key, sec, bkt, max_attempts=3, delay_s=1.2)" in txt


def test_manual_setup_connect_uses_retry_helper():
    # Setup tab connect button should also use the same retry policy.
    txt = _read("app_tabs/setup_tab.py")
    assert "_connect_r2_with_retry(" in txt
    assert "max_attempts=3" in txt
