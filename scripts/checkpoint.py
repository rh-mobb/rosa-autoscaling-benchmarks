#!/usr/bin/env python3
"""
scripts/checkpoint.py

Read and write per-test completion state for a benchmark run. Stores state in
results/<run-id>/checkpoint.json so benchmark-run-all can resume from the last
completed test if a session is interrupted.

Checkpoint JSON structure:
  {
    "run_id": "20260501T001423-classic",
    "cluster_type": "classic",
    "cluster_name": "rosa-bench-classic",
    "updated_at": "2026-05-01T00:14:23Z",
    "tests": {
      "01-cluster-install": {
        "status": "completed",          # pending | in_progress | completed | failed | skipped
        "started_at_ms": 1746054900000,
        "completed_at_ms": 1746057600000,
        "elapsed_ms": 2700000,
        "elapsed_human": "45m0s",
        "note": ""
      },
      "02-machine-pool": { "status": "in_progress", ... }
    }
  }

Sub-commands
------------
  init      Create checkpoint file (idempotent — safe to call if file exists).
  status    Print status of one or all tests.
  start     Mark a test as in_progress.
  complete  Mark a test as completed.
  fail      Mark a test as failed.
  skip      Mark a test as skipped.
  next      Print the first test that is not completed/skipped (for resume logic).

Usage examples
--------------
  # Initialize at the start of a run:
  python3 scripts/checkpoint.py init --run-id "$RUN_ID" \\
      --cluster-type classic --cluster-name rosa-bench-classic

  # Before running a test:
  STATUS=$(python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 01-cluster-install)
  # Returns: pending | in_progress | completed | failed | skipped

  # Mark in-progress:
  python3 scripts/checkpoint.py start --run-id "$RUN_ID" --test 01-cluster-install

  # Mark complete:
  python3 scripts/checkpoint.py complete --run-id "$RUN_ID" --test 01-cluster-install

  # Find the next test to run (for resume):
  python3 scripts/checkpoint.py next --run-id "$RUN_ID"
  # Returns: 02-machine-pool  (or empty string if all done)

  # List all test statuses:
  python3 scripts/checkpoint.py status --run-id "$RUN_ID"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "results"

# Canonical test ordering — must match skill names
ALL_TESTS = [
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
    "15-spot-instances",
    "16-arm-nodes",
]

TERMINAL_STATUSES = {"completed", "skipped"}
VALID_STATUSES = {"pending", "in_progress", "completed", "failed", "skipped"}


# ── File helpers ──────────────────────────────────────────────────────────────


def checkpoint_file(run_id: str) -> Path:
    return RESULTS_DIR / run_id / "checkpoint.json"


def utc_now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def elapsed_human(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}m{s % 60}s"


def load_checkpoint(run_id: str) -> dict:  # type: ignore[type-arg]
    f = checkpoint_file(run_id)
    if not f.exists():
        print(
            f"ERROR: No checkpoint found for run '{run_id}'. Run 'init' first.",
            file=sys.stderr,
        )
        sys.exit(1)
    with f.open(encoding="utf-8") as fh:
        return json.load(fh)  # type: ignore[no-any-return]


def save_checkpoint(run_id: str, data: dict) -> None:  # type: ignore[type-arg]
    f = checkpoint_file(run_id)
    data["updated_at"] = ms_to_iso(utc_now_ms())
    with f.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


# ── Sub-commands ──────────────────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace) -> None:
    """Create checkpoint file. Idempotent — does not overwrite existing data."""
    f = checkpoint_file(args.run_id)
    f.parent.mkdir(parents=True, exist_ok=True)

    if f.exists():
        print(
            f"[checkpoint] Resume mode: checkpoint for '{args.run_id}' already exists.",
            file=sys.stderr,
        )
        return

    data: dict = {  # type: ignore[type-arg]
        "run_id": args.run_id,
        "cluster_type": args.cluster_type,
        "cluster_name": args.cluster_name,
        "created_at": ms_to_iso(utc_now_ms()),
        "updated_at": ms_to_iso(utc_now_ms()),
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
    save_checkpoint(args.run_id, data)
    print(f"[checkpoint] Initialized for run '{args.run_id}'.", file=sys.stderr)


def cmd_status(args: argparse.Namespace) -> None:
    """Print status. Single test → prints just the status string. All → table."""
    data = load_checkpoint(args.run_id)
    tests = data["tests"]

    if args.test:
        if args.test not in tests:
            print(
                f"ERROR: Unknown test '{args.test}'. Valid: {', '.join(ALL_TESTS)}",
                file=sys.stderr,
            )
            sys.exit(1)
        # Print just the status string so bash scripts can capture it
        print(tests[args.test]["status"])
    else:
        # Pretty table for human use
        print(f"\nCheckpoint for run: {args.run_id}")
        print(f"{'Test':<30} {'Status':<15} {'Elapsed'}")
        print("-" * 65)
        for test in ALL_TESTS:
            t = tests.get(test, {})
            status = t.get("status", "pending")
            eh = t.get("elapsed_human") or "-"
            print(f"{test:<30} {status:<15} {eh}")
        print()


def _set_status(
    run_id: str,
    test: str,
    status: str,
    note: str = "",
    started_at_ms: int | None = None,
) -> None:
    if status not in VALID_STATUSES:
        print(f"ERROR: Invalid status '{status}'.", file=sys.stderr)
        sys.exit(1)

    data = load_checkpoint(run_id)
    if test not in data["tests"]:
        if test not in ALL_TESTS:
            print(f"ERROR: Unknown test '{test}'.", file=sys.stderr)
            sys.exit(1)
        # Test was added to ALL_TESTS after checkpoint was initialized — auto-register.
        data["tests"][test] = {
            "status": "pending",
            "started_at_ms": None,
            "completed_at_ms": None,
            "elapsed_ms": None,
            "elapsed_human": None,
            "note": "",
        }
        print(f"[checkpoint] Auto-registered new test '{test}'.", file=sys.stderr)

    now = utc_now_ms()
    entry = data["tests"][test]
    entry["status"] = status

    if status == "in_progress":
        entry["started_at_ms"] = now
    elif status in TERMINAL_STATUSES | {"failed"}:
        entry["completed_at_ms"] = now
        if entry.get("started_at_ms") or started_at_ms:
            start = entry.get("started_at_ms") or started_at_ms or now
            entry["elapsed_ms"] = now - start
            entry["elapsed_human"] = elapsed_human(now - start)

    if note:
        entry["note"] = note

    save_checkpoint(run_id, data)
    print(f"[checkpoint] {test} → {status}", file=sys.stderr)


def cmd_start(args: argparse.Namespace) -> None:
    _set_status(args.run_id, args.test, "in_progress")


def cmd_complete(args: argparse.Namespace) -> None:
    _set_status(args.run_id, args.test, "completed", note=args.note or "")


def cmd_fail(args: argparse.Namespace) -> None:
    _set_status(args.run_id, args.test, "failed", note=args.reason or "")


def cmd_skip(args: argparse.Namespace) -> None:
    _set_status(args.run_id, args.test, "skipped", note=args.reason or "")


def cmd_next(args: argparse.Namespace) -> None:
    """Print the first test not yet completed or skipped (for resume logic)."""
    data = load_checkpoint(args.run_id)
    tests = data["tests"]
    for test in ALL_TESTS:
        if tests.get(test, {}).get("status") not in TERMINAL_STATUSES:
            print(test)
            return
    # All done — print empty string
    print("")


# ── CLI ───────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage benchmark run checkpoint state.")
    sub = p.add_subparsers(dest="command", required=True)

    def add_run_id(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--run-id", required=True, help="Benchmark run ID")

    def add_test(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--test", required=True, metavar="TEST_ID",
            help=f"One of: {', '.join(ALL_TESTS)}"
        )

    # init
    pi = sub.add_parser("init", help="Initialize checkpoint for a new run.")
    add_run_id(pi)
    pi.add_argument("--cluster-type", default="unknown")
    pi.add_argument("--cluster-name", default="")

    # status
    ps = sub.add_parser("status", help="Print status of one or all tests.")
    add_run_id(ps)
    ps.add_argument("--test", default="", metavar="TEST_ID",
                    help="Specific test ID (omit to list all)")

    # start
    pst = sub.add_parser("start", help="Mark a test as in_progress.")
    add_run_id(pst)
    add_test(pst)

    # complete
    pc = sub.add_parser("complete", help="Mark a test as completed.")
    add_run_id(pc)
    add_test(pc)
    pc.add_argument("--note", default="")

    # fail
    pf = sub.add_parser("fail", help="Mark a test as failed.")
    add_run_id(pf)
    add_test(pf)
    pf.add_argument("--reason", default="")

    # skip
    psk = sub.add_parser("skip", help="Mark a test as skipped.")
    add_run_id(psk)
    add_test(psk)
    psk.add_argument("--reason", default="")

    # next
    pn = sub.add_parser("next", help="Print the next test to run (for resume).")
    add_run_id(pn)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "init": cmd_init,
        "status": cmd_status,
        "start": cmd_start,
        "complete": cmd_complete,
        "fail": cmd_fail,
        "skip": cmd_skip,
        "next": cmd_next,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
