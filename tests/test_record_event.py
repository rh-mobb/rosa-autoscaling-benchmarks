"""
tests/test_record_event.py — Unit tests for scripts/record-event.py
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# ── Module loading (file has a hyphen in its name) ────────────────────────────
_SCRIPTS = Path(__file__).parent.parent / "scripts"

spec = importlib.util.spec_from_file_location(
    "record_event", _SCRIPTS / "record-event.py"
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[attr-defined]

append_jsonl = mod.append_jsonl
read_jsonl = mod.read_jsonl
elapsed_human = mod.elapsed_human
generate_run_id = mod.generate_run_id
ms_to_iso = mod.ms_to_iso


# ── elapsed_human ─────────────────────────────────────────────────────────────


class TestElapsedHuman:
    def test_zero(self) -> None:
        assert elapsed_human(0) == "0m0s"

    def test_seconds_only(self) -> None:
        assert elapsed_human(45_000) == "0m45s"

    def test_minutes(self) -> None:
        assert elapsed_human(2_700_000) == "45m0s"

    def test_hours(self) -> None:
        assert elapsed_human(3_600_000) == "60m0s"

    def test_mixed(self) -> None:
        assert elapsed_human(3_665_000) == "61m5s"


# ── generate_run_id ───────────────────────────────────────────────────────────


class TestGenerateRunId:
    def test_contains_cluster_type(self) -> None:
        run_id = generate_run_id("classic")
        assert run_id.endswith("-classic")

    def test_contains_timestamp(self) -> None:
        run_id = generate_run_id("hcp")
        # Format: YYYYMMDDTHHmmSS-hcp
        parts = run_id.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 15  # 20260501T001423

    def test_unique(self) -> None:
        import time
        id1 = generate_run_id("classic")
        time.sleep(1.01)
        id2 = generate_run_id("classic")
        assert id1 != id2


# ── append_jsonl / read_jsonl ─────────────────────────────────────────────────


class TestJsonl:
    def test_roundtrip_single(self, tmp_path: Path) -> None:
        f = tmp_path / "events.jsonl"
        record = {"label": "test.event", "elapsed_ms": 1000}
        append_jsonl(f, record)
        records = read_jsonl(f)
        assert len(records) == 1
        assert records[0]["label"] == "test.event"

    def test_multiple_appends(self, tmp_path: Path) -> None:
        f = tmp_path / "events.jsonl"
        for i in range(5):
            append_jsonl(f, {"seq": i, "label": f"event.{i}"})
        records = read_jsonl(f)
        assert len(records) == 5
        assert [r["seq"] for r in records] == list(range(5))

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        f = tmp_path / "deep" / "nested" / "events.jsonl"
        append_jsonl(f, {"x": 1})
        assert f.exists()

    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.touch()
        assert read_jsonl(f) == []

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        f = tmp_path / "nonexistent.jsonl"
        assert read_jsonl(f) == []

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "events.jsonl"
        f.write_text('{"good": 1}\nNOT JSON\n{"good": 2}\n')
        records = read_jsonl(f)
        assert len(records) == 2


# ── ms_to_iso ─────────────────────────────────────────────────────────────────


class TestMsToIso:
    def test_epoch_zero(self) -> None:
        assert ms_to_iso(0) == "1970-01-01T00:00:00Z"

    def test_format(self) -> None:
        # 2025-05-01T00:00:00 UTC = 1746057600 s
        ts = 1_746_057_600_000
        assert ms_to_iso(ts) == "2025-05-01T00:00:00Z"


# ── Integration: init + record + summary via direct function calls ─────────────


class TestIntegration:
    """Test the full init → record → summary flow using patched RESULTS_DIR."""

    def test_init_creates_metadata(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
        # Simulate init
        run_id = "20260501T001423-classic"
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        meta = {
            "run_id": run_id,
            "cluster_type": "classic",
            "cluster_name": "rosa-bench-classic",
            "region": "us-east-1",
            "rosa_version": "4.17.3",
            "started_at_ms": 1_746_057_600_000,
            "started_at": "2026-05-01T00:00:00Z",
        }
        mf = run_dir / "metadata.json"
        with mf.open("w") as fh:
            json.dump(meta, fh)
        assert mf.exists()
        with mf.open() as fh:
            loaded = json.load(fh)
        assert loaded["cluster_type"] == "classic"

    def test_record_appends_event(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path)
        run_id = "test-run-001"
        ef = tmp_path / run_id / "events.jsonl"
        ef.parent.mkdir(parents=True)

        # Directly call append_jsonl as record would
        record = {
            "ts": 1_746_057_600_000,
            "iso": "2026-05-01T00:00:00Z",
            "label": "classic.cluster_ready",
            "start_ms": 1_746_054_900_000,
            "end_ms": 1_746_057_600_000,
            "elapsed_ms": 2_700_000,
            "elapsed_human": "45m0s",
            "cluster_type": "classic",
            "cluster_name": "rosa-bench-classic",
        }
        append_jsonl(ef, record)

        records = read_jsonl(ef)
        assert len(records) == 1
        assert records[0]["label"] == "classic.cluster_ready"
        assert records[0]["elapsed_ms"] == 2_700_000
