"""
tests/test_collect_install_log_milestones.py

Unit tests for scripts/collect-install-log-milestones.py:
  - extract_timestamp_ms: parses logrus, JSON, and no-quote timestamp formats
  - parse_install_log: detects all known milestone patterns; deduplicates; orders by time
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from datetime import UTC, datetime

# Pre-computed epoch ms for timestamps used across tests
_MS_2026_05_09_01_23_45 = int(datetime(2026, 5, 9, 1, 23, 45, tzinfo=UTC).timestamp() * 1000)
_MS_2026_05_09_00_15_00 = int(datetime(2026, 5, 9, 0, 15, 0, tzinfo=UTC).timestamp() * 1000)

# ── Module loading (hyphen in filename) ───────────────────────────────────────
_SCRIPTS = Path(__file__).parent.parent / "scripts"

spec = importlib.util.spec_from_file_location(
    "collect_install_log_milestones",
    _SCRIPTS / "collect-install-log-milestones.py",
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[attr-defined]

extract_timestamp_ms = mod.extract_timestamp_ms
parse_install_log = mod.parse_install_log


# ── extract_timestamp_ms ──────────────────────────────────────────────────────

LOGRUS_LINE = 'time="2026-05-09T01:23:45Z" level=info msg="Bootstrap complete"'
JSON_LINE = '{"time":"2026-05-09T01:23:45Z","level":"info","msg":"Bootstrap complete"}'
NOQUOTE_LINE = "time=2026-05-09T01:23:45Z level=info msg=Bootstrap complete"
OFFSET_LINE = 'time="2026-05-09T01:23:45+00:00" level=info msg="API v4.17.3 up"'


class TestExtractTimestampMs:
    def test_logrus_format(self) -> None:
        ts = extract_timestamp_ms(LOGRUS_LINE)
        assert ts is not None
        assert ts == _MS_2026_05_09_01_23_45

    def test_json_format(self) -> None:
        ts = extract_timestamp_ms(JSON_LINE)
        assert ts is not None
        assert ts == _MS_2026_05_09_01_23_45

    def test_noquote_format(self) -> None:
        ts = extract_timestamp_ms(NOQUOTE_LINE)
        assert ts is not None
        assert ts == _MS_2026_05_09_01_23_45

    def test_utc_offset_format(self) -> None:
        ts = extract_timestamp_ms(OFFSET_LINE)
        assert ts is not None
        assert ts == _MS_2026_05_09_01_23_45

    def test_no_timestamp_returns_none(self) -> None:
        assert extract_timestamp_ms("INFO Bootstrap complete") is None

    def test_malformed_timestamp_returns_none(self) -> None:
        assert extract_timestamp_ms('time="not-a-date" level=info msg="x"') is None


# ── parse_install_log ─────────────────────────────────────────────────────────

# Minimal synthetic log covering all milestone patterns
_SAMPLE_LOG = """\
time="2026-05-09T00:01:00Z" level=info msg="Creating infrastructure resources"
time="2026-05-09T00:05:00Z" level=info msg="Waiting for the Kubernetes API"
time="2026-05-09T00:10:00Z" level=info msg="API v4.17.3 up"
time="2026-05-09T00:15:00Z" level=info msg="Bootstrap complete"
time="2026-05-09T00:16:00Z" level=info msg="Destroying the bootstrap resources"
time="2026-05-09T00:17:00Z" level=info msg="Bootstrap destroyed"
time="2026-05-09T00:30:00Z" level=info msg="Waiting for the cluster version"
time="2026-05-09T00:40:00Z" level=info msg="Cluster version operator initialized"
time="2026-05-09T00:50:00Z" level=info msg="Install complete!"
"""

# Expected label suffixes in order
_EXPECTED_LABELS = [
    "infra_creating",
    "waiting_for_api",
    "api_reachable",
    "bootstrap_complete",
    "bootstrap_destroying",
    "bootstrap_destroyed",
    "waiting_for_cluster_version",
    "cluster_version_init",
    "install_complete",
]


class TestParseInstallLog:
    def test_all_milestones_detected(self) -> None:
        results = parse_install_log(_SAMPLE_LOG)
        labels = [label for label, _ in results]
        assert labels == _EXPECTED_LABELS

    def test_results_ordered_by_timestamp(self) -> None:
        results = parse_install_log(_SAMPLE_LOG)
        times = [ts for _, ts in results]
        assert times == sorted(times)

    def test_first_occurrence_wins(self) -> None:
        # Duplicate "Bootstrap complete" lines — only the first should be recorded
        log = (
            'time="2026-05-09T00:15:00Z" level=info msg="Bootstrap complete"\n'
            'time="2026-05-09T00:15:30Z" level=info msg="Bootstrap complete (retry)"\n'
        )
        results = parse_install_log(log)
        bootstrap = [ts for label, ts in results if label == "bootstrap_complete"]
        assert len(bootstrap) == 1
        # Should be the first occurrence
        assert bootstrap[0] == _MS_2026_05_09_00_15_00

    def test_empty_log_returns_empty_list(self) -> None:
        assert parse_install_log("") == []

    def test_log_with_no_matching_lines_returns_empty(self) -> None:
        assert parse_install_log("INFO nothing interesting here\n") == []

    def test_line_without_timestamp_is_skipped(self) -> None:
        # No timestamp — should not crash, just skip
        log = "Bootstrap complete\n" + LOGRUS_LINE + "\n"
        results = parse_install_log(log)
        # The second line has a timestamp but no milestone keyword
        # The first line has a milestone but no timestamp — should be skipped
        assert all(ts is not None for _, ts in results)

    def test_json_format_milestones(self) -> None:
        log = (
            '{"time":"2026-05-09T00:15:00Z","level":"info","msg":"Bootstrap complete"}\n'
            '{"time":"2026-05-09T00:50:00Z","level":"info","msg":"Install complete!"}\n'
        )
        results = parse_install_log(log)
        labels = [l for l, _ in results]
        assert "bootstrap_complete" in labels
        assert "install_complete" in labels

    def test_case_insensitive_matching(self) -> None:
        log = 'time="2026-05-09T00:15:00Z" level=info msg="BOOTSTRAP COMPLETE"\n'
        results = parse_install_log(log)
        assert any(label == "bootstrap_complete" for label, _ in results)

    def test_partial_log_no_crash(self) -> None:
        log = (
            'time="2026-05-09T00:01:00Z" level=info msg="Creating infrastructure resources"\n'
            "truncated line without closing quote\n"
        )
        results = parse_install_log(log)
        assert len(results) >= 1
