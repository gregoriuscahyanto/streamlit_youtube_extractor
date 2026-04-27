from __future__ import annotations

import re
from pathlib import Path


LOG_PATH = Path("logs/roi_list_layout_test.log")


def _write_log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(message, encoding="utf-8")


def _roi_editor_config_block(app_source: str) -> str:
    marker = 'key=str(st.session_state.get("roi_editor_widget_key"'
    marker_pos = app_source.find(marker)
    if marker_pos < 0:
        raise AssertionError("ROI data_editor key wurde nicht gefunden.")

    config_pos = app_source.rfind("column_config={", 0, marker_pos)
    if config_pos < 0:
        raise AssertionError("ROI column_config wurde nicht gefunden.")
    return app_source[config_pos:marker_pos]


def _extract_width(block: str, column_key: str) -> int:
    pattern = rf'"{re.escape(column_key)}":\s*st\.column_config\.\w+Column\([^)]*width=(\d+)'
    match = re.search(pattern, block, flags=re.S)
    if not match:
        raise AssertionError(f"Breite fuer Spalte {column_key!r} wurde nicht gefunden.")
    return int(match.group(1))


def test_roi_list_uses_compact_column_widths() -> None:
    try:
        app_source = Path("app.py").read_text(encoding="utf-8")
        block = _roi_editor_config_block(app_source)

        select_col_match = re.search(
            r"_sel_col:\s*st\.column_config\.CheckboxColumn\([^)]*width=(\d+)",
            block,
            flags=re.S,
        )
        if not select_col_match:
            raise AssertionError("Checkbox-Spaltenbreite wurde nicht gefunden.")

        widths = {
            "checkbox": int(select_col_match.group(1)),
            "Name": _extract_width(block, "Name"),
            "Format": _extract_width(block, "Format"),
            "Pattern": _extract_width(block, "Pattern"),
            "Scale": _extract_width(block, "Scale"),
        }

        assert widths["checkbox"] <= 48
        assert widths["Name"] >= 140
        assert widths["Format"] >= 160
        assert widths["Pattern"] <= 64
        assert widths["Scale"] <= 60
        assert widths["Name"] > widths["Pattern"]
        assert widths["Format"] > widths["Scale"]
        assert sum(widths.values()) <= 500
        assert 'TextColumn("Pat."' in block
        assert 'NumberColumn("Sc."' in block

        _write_log(f"OK: ROI-Liste kompakt ohne horizontales Scrollen konfiguriert: {widths}")
    except Exception as exc:
        _write_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        raise
