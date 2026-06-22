"""RTK checks for external table support in the comparison tab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_compare_tab_has_external_table_upload_and_mapping():
    txt = _read("app_tabs/compare_tab.py")
    assert "def _read_external_table(" in txt
    assert "def _external_table_to_cols(" in txt
    assert "Externe Excel/CSV-Tabelle" in txt
    assert 'accept_multiple_files=True' in txt
    assert '"time_s"' in txt
    assert '"rpm"' in txt
    assert '"v_Fzg_kmph"' in txt
    assert "cmp_external_sources" in txt


def test_compare_charts_use_json_and_external_sources():
    txt = _read("app_tabs/compare_tab.py")
    assert "display_files = list(st.session_state.cmp_files) + list(external_files)" in txt
    assert "_external_table_to_cols(" in txt
    assert "_render_chart(chart, display_files, cmp_data, ci)" in txt
    assert "_render_geoplot_chart(chart, display_files, cmp_data, ci)" in txt
