# -*- coding: utf-8 -*-
"""Tests for tolerance logic in app.py audio validation helpers."""

import ast
from pathlib import Path

import numpy as np


def _load_audio_validation_ns():
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    needed = {"_audio_validation_metrics", "_audio_find_best_validation_shift"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in needed]
    namespace = {"np": np}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(repo / "app.py"), "exec"), namespace)
    return namespace


def _sample_series(n=300):
    t = np.linspace(0.0, 30.0, n)
    rpm_ref = 3000.0 + 400.0 * np.sin(2 * np.pi * 0.15 * t)
    return t, rpm_ref


def test_tolerance_abs_only_ratio():
    ns = _load_audio_validation_ns()
    t, ref = _sample_series()
    aud = ref + 300.0
    res = ns["_audio_validation_metrics"](
        t, aud, t, ref, 0.0, "Absolutwert",
        tol_abs_rpm=500.0, tol_pct=None, tol_logic="ODER",
    )
    assert res["ok"] is True
    assert res["tolerance_logic"] == "ABS"
    assert res["within_tolerance_ratio_pct"] == 100.0
    assert res["outside_tolerance_count"] == 0


def test_tolerance_pct_only_ratio():
    ns = _load_audio_validation_ns()
    t, ref = _sample_series()
    aud = ref * 1.10
    res = ns["_audio_validation_metrics"](
        t, aud, t, ref, 0.0, "Prozentual",
        tol_abs_rpm=None, tol_pct=5.0, tol_logic="ODER",
    )
    assert res["ok"] is True
    assert res["tolerance_logic"] == "PCT"
    assert res["within_tolerance_ratio_pct"] == 0.0
    assert res["within_tolerance_count"] == 0


def test_tolerance_and_vs_or():
    ns = _load_audio_validation_ns()
    t, ref = _sample_series()
    aud = ref + 200.0
    res_or = ns["_audio_validation_metrics"](
        t, aud, t, ref, 0.0, "Absolutwert",
        tol_abs_rpm=250.0, tol_pct=5.0, tol_logic="ODER",
    )
    res_and = ns["_audio_validation_metrics"](
        t, aud, t, ref, 0.0, "Absolutwert",
        tol_abs_rpm=250.0, tol_pct=5.0, tol_logic="UND",
    )
    assert res_or["ok"] is True and res_and["ok"] is True
    assert res_or["tolerance_logic"] == "ODER"
    assert res_and["tolerance_logic"] == "UND"
    assert res_or["within_tolerance_ratio_pct"] >= res_and["within_tolerance_ratio_pct"]


def test_find_best_match_keeps_tolerance_fields():
    ns = _load_audio_validation_ns()
    t, ref = _sample_series(n=200)
    # reference is shifted +1s; best shift should be near -1s
    ref_t = t + 1.0
    aud = ref.copy()
    best, dbg = ns["_audio_find_best_validation_shift"](
        t, aud, ref_t, ref, "Absolutwert",
        -2.0, 2.0, 0.1,
        tol_abs_rpm=150.0, tol_pct=3.0, tol_logic="ODER",
    )
    assert isinstance(dbg, list) and len(dbg) > 0
    assert best["ok"] is True
    assert abs(best["shift_s"] + 1.0) <= 0.2
    assert "within_tolerance_ratio_pct" in best
    assert "within_tolerance_count" in best
