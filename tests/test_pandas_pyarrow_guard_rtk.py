"""RTK guard: disable pandas pyarrow backend early in app bootstrap."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_app_disables_pandas_pyarrow_before_pandas_import():
    txt = (ROOT / "app.py").read_text(encoding="utf-8")
    guard = 'os.environ.setdefault("PANDAS_USE_PYARROW", "0")'
    imp = "import pandas as pd"
    assert guard in txt
    assert imp in txt
    assert txt.index(guard) < txt.index(imp)
