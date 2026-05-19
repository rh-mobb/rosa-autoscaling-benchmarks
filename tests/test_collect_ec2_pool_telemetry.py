"""
tests/test_collect_ec2_pool_telemetry.py

Unit tests for scripts/collect-ec2-pool-telemetry.py:
  - extract_instance_id: parses EC2 instance IDs from Kubernetes providerIDs
  - parse_journal_timestamp: parses systemd journal line timestamps to epoch ms
  - collect_node_logs: extracts service activation milestones from journal text
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Module loading ─────────────────────────────────────────────────────────────
_SCRIPTS = Path(__file__).parent.parent / "scripts"

spec = importlib.util.spec_from_file_location(
    "collect_ec2_pool_telemetry",
    _SCRIPTS / "collect-ec2-pool-telemetry.py",
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[attr-defined]

extract_instance_id = mod.extract_instance_id
parse_journal_timestamp = mod.parse_journal_timestamp
collect_node_logs = mod.collect_node_logs


# ── extract_instance_id ───────────────────────────────────────────────────────


class TestExtractInstanceId:
    def test_standard_format(self) -> None:
        pid = "aws:///us-east-1a/i-0abc1234def56789"
        assert extract_instance_id(pid) == "i-0abc1234def56789"

    def test_different_region(self) -> None:
        pid = "aws:///eu-west-1b/i-0123456789abcdef0"
        assert extract_instance_id(pid) == "i-0123456789abcdef0"

    def test_no_region_prefix(self) -> None:
        # Bare instance ID path
        pid = "aws:////i-0abc1234def56789"
        assert extract_instance_id(pid) == "i-0abc1234def56789"

    def test_invalid_returns_none(self) -> None:
        assert extract_instance_id("not-a-provider-id") is None

    def test_empty_string(self) -> None:
        assert extract_instance_id("") is None

    def test_old_style_id(self) -> None:
        # Older 8-char instance IDs (still valid format)
        pid = "aws:///us-east-1c/i-1a2b3c4d"
        assert extract_instance_id(pid) == "i-1a2b3c4d"


# ── parse_journal_timestamp ───────────────────────────────────────────────────

REFERENCE_YEAR = 2026


class TestParseJournalTimestamp:
    def test_standard_format(self) -> None:
        line = "May 08 02:10:30 hostname systemd[1]: Started ignition-fetch.service"
        ts = parse_journal_timestamp(line, REFERENCE_YEAR)
        assert ts is not None
        dt = datetime.fromtimestamp(ts / 1000, tz=UTC)
        assert dt.month == 5
        assert dt.day == 8
        assert dt.hour == 2
        assert dt.minute == 10
        assert dt.second == 30

    def test_single_digit_day(self) -> None:
        line = "Jan  5 00:00:01 host systemd[1]: Started kubelet.service"
        ts = parse_journal_timestamp(line, REFERENCE_YEAR)
        assert ts is not None
        dt = datetime.fromtimestamp(ts / 1000, tz=UTC)
        assert dt.month == 1
        assert dt.day == 5

    def test_journal_header_not_parsed(self) -> None:
        # The "-- Logs begin at ..." header does not start with the expected format
        line = "-- Logs begin at Thu 2026-05-08 02:05:00 UTC, end at ..."
        ts = parse_journal_timestamp(line, REFERENCE_YEAR)
        assert ts is None

    def test_no_timestamp_returns_none(self) -> None:
        line = "this line has no timestamp at all"
        assert parse_journal_timestamp(line, REFERENCE_YEAR) is None

    def test_invalid_month_returns_none(self) -> None:
        line = "Xyz 08 02:10:30 hostname systemd[1]: Started something"
        assert parse_journal_timestamp(line, REFERENCE_YEAR) is None

    def test_future_date_wraps_year(self) -> None:
        # A December date parsed in January context should roll back a year
        # Simulate: reference year is 2026 (January), log line is December
        line = "Dec 31 23:59:59 hostname systemd[1]: Started something"
        ts = parse_journal_timestamp(line, 2026)
        assert ts is not None
        dt = datetime.fromtimestamp(ts / 1000, tz=UTC)
        # Should be Dec 31 2025, not Dec 31 2026 (which is ~30+ days in the future)
        assert dt.year == 2025
        assert dt.month == 12

    def test_result_is_epoch_ms(self) -> None:
        line = "May 08 02:10:30 hostname systemd[1]: Started ignition-fetch.service"
        ts = parse_journal_timestamp(line, REFERENCE_YEAR)
        assert ts is not None
        assert ts > 1_000_000_000_000  # sanity: must be > year 2001 in ms


# ── collect_node_logs ─────────────────────────────────────────────────────────

# Synthetic journal output representing a successful CoreOS boot
_SAMPLE_JOURNAL = """\
-- Logs begin at Thu 2026-05-08 02:05:00 UTC, end at Thu 2026-05-08 02:30:00 UTC. --
May 08 02:06:00 ip-10-0-1-100 systemd[1]: Starting ignition-fetch.service - Ignition (fetch)...
May 08 02:06:05 ip-10-0-1-100 systemd[1]: Started ignition-fetch.service - Ignition (fetch).
May 08 02:06:10 ip-10-0-1-100 systemd[1]: Starting ignition-disks.service - Ignition (disks)...
May 08 02:06:20 ip-10-0-1-100 systemd[1]: Started ignition-disks.service - Ignition (disks).
May 08 02:06:30 ip-10-0-1-100 systemd[1]: Starting ignition-files.service - Ignition (files)...
May 08 02:06:45 ip-10-0-1-100 systemd[1]: Started ignition-files.service - Ignition (files).
May 08 02:07:00 ip-10-0-1-100 systemd[1]: Starting ignition-complete.service - Ignition (complete)...
May 08 02:07:05 ip-10-0-1-100 systemd[1]: Started ignition-complete.service - Ignition (complete).
May 08 02:08:00 ip-10-0-1-100 systemd[1]: Starting crio.service - CRI-O Kubernetes Container Runtime...
May 08 02:08:10 ip-10-0-1-100 systemd[1]: Started crio.service - CRI-O Kubernetes Container Runtime.
May 08 02:08:30 ip-10-0-1-100 systemd[1]: Starting kubelet.service - Kubernetes Node Agent (kubelet)...
May 08 02:08:45 ip-10-0-1-100 systemd[1]: Started kubelet.service - Kubernetes Node Agent (kubelet).
"""


class TestCollectNodeLogs:
    def _make_collect(self, journal_text: str) -> dict[str, int]:
        """Call collect_node_logs with mocked _run_oc returning journal_text."""
        with patch.object(mod, "_run_oc", return_value=journal_text):
            return collect_node_logs("fake-node", kubeconfig=None, reference_year=REFERENCE_YEAR)

    def test_all_services_detected(self) -> None:
        result = self._make_collect(_SAMPLE_JOURNAL)
        assert "ignition_fetch_done" in result
        assert "ignition_disks_done" in result
        assert "ignition_files_done" in result
        assert "ignition_complete" in result
        assert "crio_started" in result
        assert "kubelet_started" in result

    def test_timestamps_are_ordered(self) -> None:
        result = self._make_collect(_SAMPLE_JOURNAL)
        times = list(result.values())
        assert times == sorted(times)

    def test_started_not_starting(self) -> None:
        # "Starting" lines should not be captured, only "Started"
        journal = (
            "May 08 02:06:00 host systemd[1]: Starting ignition-fetch.service...\n"
            "May 08 02:06:05 host systemd[1]: Started ignition-fetch.service.\n"
        )
        result = self._make_collect(journal)
        assert "ignition_fetch_done" in result
        # Verify the timestamp is from the "Started" line (02:06:05), not "Starting"
        ts = result["ignition_fetch_done"]
        dt = datetime.fromtimestamp(ts / 1000, tz=UTC)
        assert dt.second == 5

    def test_first_occurrence_wins(self) -> None:
        journal = (
            "May 08 02:06:05 host systemd[1]: Started ignition-fetch.service.\n"
            "May 08 02:07:00 host systemd[1]: Started ignition-fetch.service.\n"
        )
        result = self._make_collect(journal)
        assert "ignition_fetch_done" in result
        dt = datetime.fromtimestamp(result["ignition_fetch_done"] / 1000, tz=UTC)
        assert dt.second == 5  # first occurrence wins

    def test_oc_failure_returns_empty(self) -> None:
        with patch.object(mod, "_run_oc", side_effect=RuntimeError("oc failed")):
            result = collect_node_logs("fake-node", kubeconfig=None, reference_year=REFERENCE_YEAR)
        assert result == {}

    def test_empty_journal_returns_empty(self) -> None:
        result = self._make_collect("")
        assert result == {}

    def test_partial_journal_no_crash(self) -> None:
        journal = (
            "May 08 02:06:05 host systemd[1]: Started ignition-fetch.service.\n"
            "truncated line without proper format\n"
            "another bad line\n"
        )
        result = self._make_collect(journal)
        assert "ignition_fetch_done" in result
        assert len(result) == 1
