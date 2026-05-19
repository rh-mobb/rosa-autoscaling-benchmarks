"""Unit tests for scripts/update-reports-index.py helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "update_reports_index",
    _REPO_ROOT / "scripts" / "update-reports-index.py",
)
assert _SPEC and _SPEC.loader
_mod = importlib.util.module_from_spec(_SPEC)
sys.modules["update_reports_index"] = _mod
_SPEC.loader.exec_module(_mod)

parse_duration_human = _mod.parse_duration_human
_parse_html_report = _mod._parse_html_report
classify_report = _mod.classify_report


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("56m 2s", 56 * 60 + 2),
        ("~23m 7s", 23 * 60 + 7),
        ("N/A", None),
        ("", None),
        ("1h 0m 5s", 3600 + 5),
        ("0m 2s", 2),
    ],
)
def test_parse_duration_human(text: str, expected: float | None) -> None:
    assert parse_duration_human(text) == expected


def test_classify_report() -> None:
    assert classify_report("x-01-classic-cluster-install.html") == ("01_cluster_install", "classic")
    assert classify_report("x-01-hcp-cluster-install.html") == ("01_cluster_install", "hcp")
    assert classify_report("x-suite-01-through-09.html") == ("suite_01_09", None)


def test_parse_html_report_extracts_meta(tmp_path: Path) -> None:
    html = """<!DOCTYPE html><html><body><main><header>
    <h1>Benchmark 01 — Cluster install</h1>
    <dl class="meta">
      <dt>Run ID</dt><dd><code>20260506T035144-hcp</code></dd>
      <dt>Cluster name</dt><dd><code>hcp-bench</code></dd>
      <dt>Report generated</dt><dd><code>2026-05-06T04:17:40Z</code> (UTC)</dd>
    </dl></header>
    <div class="stats">
      <div class="stat warning">
        <div class="label">Total (wall clock)</div>
        <div class="value">56m 2s</div>
      </div>
    </div></main></body></html>"""
    p = tmp_path / "r.html"
    p.write_text(html, encoding="utf-8")
    d = _parse_html_report(p)
    assert d.get("run_id") == "20260506T035144-hcp"
    assert d.get("cluster_name") == "hcp-bench"
    assert d.get("report_generated_iso") == "2026-05-06T04:17:40Z"
    assert d.get("html_total_seconds") == 56 * 60 + 2
