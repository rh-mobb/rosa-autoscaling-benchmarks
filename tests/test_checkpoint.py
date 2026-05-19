"""
tests/test_checkpoint.py — Unit tests for scripts/checkpoint.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# ── Module loading ────────────────────────────────────────────────────────────
_SCRIPTS = Path(__file__).parent.parent / "scripts"

spec = importlib.util.spec_from_file_location("checkpoint", _SCRIPTS / "checkpoint.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[attr-defined]

ALL_TESTS = mod.ALL_TESTS
TERMINAL_STATUSES = mod.TERMINAL_STATUSES
elapsed_human = mod.elapsed_human
load_checkpoint = mod.load_checkpoint
save_checkpoint = mod.save_checkpoint


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def run_id() -> str:
    return "20260501T001423-classic"


@pytest.fixture()
def results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def initialized_run(run_id: str, results_dir: Path) -> str:
    """Create and return a run with an initialized checkpoint."""
    d = results_dir / run_id
    d.mkdir(parents=True)
    data: dict = {
        "run_id": run_id,
        "cluster_type": "classic",
        "cluster_name": "rosa-bench-classic",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T00:00:00Z",
        "tests": {
            test: {
                "status": "pending",
                "started_at_ms": None,
                "completed_at_ms": None,
                "elapsed_ms": None,
                "elapsed_human": None,
                "note": "",
            }
            for test in ALL_TESTS
        },
    }
    save_checkpoint(run_id, data)
    return run_id


# ── ALL_TESTS ──────────────────────────────────────────────────────────────────


class TestAllTests:
    def test_count(self) -> None:
        assert len(ALL_TESTS) == 16

    def test_ordering(self) -> None:
        def stage_sort_key(test_id: str) -> tuple[int, int]:
            prefix = test_id.split("-", 1)[0]
            if prefix.endswith("b") and prefix[:-1].isdigit():
                return int(prefix[:-1]), 1
            return int(prefix), 0

        keys = [stage_sort_key(t) for t in ALL_TESTS]
        assert keys == sorted(keys), ALL_TESTS

    def test_names_match_skills(self) -> None:
        expected = {
            "01-cluster-install",
            "02-machine-pool",
            "03-autoscale-up",
            "04-autoscale-down",
            "05-unschedulable",
            "05b-dynamic-instance",
            "06-hpa",
            "07-vpa-advise",
            "08-hpa-triggers-cas",
            "09-overprovisioning",
            "09b-karpenter-overprovisioning",
            "10-autonode-scale",
            "11-planned-surge",
            "12-sudden-spike",
            "13-parallel-nodes",
            "14-cas-scale",
        }
        assert set(ALL_TESTS) == expected


# ── load / save ───────────────────────────────────────────────────────────────


class TestLoadSave:
    def test_roundtrip(self, initialized_run: str, results_dir: Path) -> None:
        data = load_checkpoint(initialized_run)
        assert data["run_id"] == initialized_run
        assert "tests" in data
        assert all(t in data["tests"] for t in ALL_TESTS)

    def test_load_missing_exits(self, run_id: str, results_dir: Path) -> None:
        with pytest.raises(SystemExit):
            load_checkpoint(run_id)

    def test_save_updates_updated_at(self, initialized_run: str, results_dir: Path) -> None:
        import time

        data = load_checkpoint(initialized_run)
        time.sleep(0.01)
        save_checkpoint(initialized_run, data)
        data2 = load_checkpoint(initialized_run)
        assert "T" in data2["updated_at"]


# ── Status transitions ────────────────────────────────────────────────────────


class TestStatusTransitions:
    def _set(self, run_id: str, test: str, status: str, note: str = "") -> None:
        mod._set_status(run_id, test, status, note=note)

    def test_all_pending_initially(self, initialized_run: str) -> None:
        data = load_checkpoint(initialized_run)
        for t in ALL_TESTS:
            assert data["tests"][t]["status"] == "pending"

    def test_start_sets_in_progress(self, initialized_run: str) -> None:
        self._set(initialized_run, "01-cluster-install", "in_progress")
        data = load_checkpoint(initialized_run)
        entry = data["tests"]["01-cluster-install"]
        assert entry["status"] == "in_progress"
        assert entry["started_at_ms"] is not None

    def test_complete_sets_elapsed(self, initialized_run: str) -> None:
        import time

        self._set(initialized_run, "01-cluster-install", "in_progress")
        time.sleep(0.05)
        self._set(initialized_run, "01-cluster-install", "completed")
        data = load_checkpoint(initialized_run)
        entry = data["tests"]["01-cluster-install"]
        assert entry["status"] == "completed"
        assert entry["elapsed_ms"] is not None
        assert entry["elapsed_ms"] >= 0

    def test_fail_records_note(self, initialized_run: str) -> None:
        self._set(initialized_run, "02-machine-pool", "failed", note="timeout")
        data = load_checkpoint(initialized_run)
        assert data["tests"]["02-machine-pool"]["note"] == "timeout"

    def test_invalid_status_exits(self, initialized_run: str) -> None:
        with pytest.raises(SystemExit):
            mod._set_status(initialized_run, "01-cluster-install", "bogus-status")

    def test_unknown_test_exits(self, initialized_run: str) -> None:
        with pytest.raises(SystemExit):
            mod._set_status(initialized_run, "99-nonexistent", "completed")


# ── cmd_next (resume logic) ───────────────────────────────────────────────────


class TestCmdNext:
    def _next(self, run_id: str, capsys: pytest.CaptureFixture) -> str:
        """Call cmd_next and capture stdout."""
        import argparse
        args = argparse.Namespace(run_id=run_id)
        mod.cmd_next(args)
        return capsys.readouterr().out.strip()

    def test_next_is_first_when_all_pending(
        self, initialized_run: str, capsys: pytest.CaptureFixture
    ) -> None:
        result = self._next(initialized_run, capsys)
        assert result == ALL_TESTS[0]

    def test_next_skips_completed(
        self, initialized_run: str, capsys: pytest.CaptureFixture
    ) -> None:
        mod._set_status(initialized_run, "01-cluster-install", "completed")
        result = self._next(initialized_run, capsys)
        assert result == ALL_TESTS[1]

    def test_next_skips_skipped(
        self, initialized_run: str, capsys: pytest.CaptureFixture
    ) -> None:
        mod._set_status(initialized_run, "01-cluster-install", "skipped")
        result = self._next(initialized_run, capsys)
        assert result == ALL_TESTS[1]

    def test_next_does_not_skip_failed(
        self, initialized_run: str, capsys: pytest.CaptureFixture
    ) -> None:
        mod._set_status(initialized_run, "01-cluster-install", "failed")
        result = self._next(initialized_run, capsys)
        assert result == ALL_TESTS[0]  # failed = needs retry

    def test_next_returns_empty_when_all_done(
        self, initialized_run: str, capsys: pytest.CaptureFixture
    ) -> None:
        for t in ALL_TESTS:
            mod._set_status(initialized_run, t, "completed")
        result = self._next(initialized_run, capsys)
        assert result == ""


# ── TERMINAL_STATUSES ─────────────────────────────────────────────────────────


class TestTerminalStatuses:
    def test_completed_and_skipped_are_terminal(self) -> None:
        assert "completed" in TERMINAL_STATUSES
        assert "skipped" in TERMINAL_STATUSES

    def test_failed_is_not_terminal(self) -> None:
        assert "failed" not in TERMINAL_STATUSES

    def test_pending_is_not_terminal(self) -> None:
        assert "pending" not in TERMINAL_STATUSES
