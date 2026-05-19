#!/usr/bin/env python3
"""
scripts/record-event.py

Append timestamped benchmark events to a per-run JSONL log and maintain a
human-readable summary. Events are written atomically one line at a time so
partial runs are never corrupted.

JSONL format — one JSON object per line in results/<run-id>/events.jsonl:
  {"ts": 1746057600123, "label": "classic.cluster_ready", "start_ms": ...,
   "end_ms": ..., "elapsed_ms": ..., "elapsed_human": "45m0s",
   "cluster_type": "classic", "cluster_name": "rosa-bench-classic", "meta": {}}

Sub-commands
------------
init        Create a new run directory and metadata file. Prints the run-id.
record      Append a single timing event.
list        Print all recorded events for a run (human readable).
summary     Print a summary table of all recorded timings.

Usage examples
--------------
  # Start a new run (call once at the top of a create script):
  RUN_ID=$(python3 scripts/record-event.py init \\
      --cluster-type classic --cluster-name rosa-bench-classic)
  export BENCHMARK_RUN_ID="$RUN_ID"

  # Record a timing event (called by emit_timing in common.sh):
  python3 scripts/record-event.py record \\
      --run-id "$BENCHMARK_RUN_ID" \\
      --label classic.cluster_ready \\
      --start-ms 1746054900000 --end-ms 1746057600000 \\
      --cluster-type classic --cluster-name rosa-bench-classic

  # List events for a run:
  python3 scripts/record-event.py list --run-id "$BENCHMARK_RUN_ID"

  # Print summary table:
  python3 scripts/record-event.py summary --run-id "$BENCHMARK_RUN_ID"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

RESULTS_DIR = Path(__file__).parent.parent / "results"


# ── Helpers ───────────────────────────────────────────────────────────────────


def run_dir(run_id: str) -> Path:
    return RESULTS_DIR / run_id


def events_file(run_id: str) -> Path:
    return run_dir(run_id) / "events.jsonl"


def metadata_file(run_id: str) -> Path:
    return run_dir(run_id) / "metadata.json"


def elapsed_human(elapsed_ms: int) -> str:
    s = elapsed_ms // 1000
    return f"{s // 60}m{s % 60}s"


def utc_now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def append_jsonl(path: Path, record: dict) -> None:  # type: ignore[type-arg]
    """Append one JSON record to a JSONL file (O_APPEND guarantees atomicity on POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_jsonl(path: Path) -> list[dict]:  # type: ignore[type-arg]
    if not path.exists():
        return []
    records = []
    import contextlib

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                with contextlib.suppress(json.JSONDecodeError):
                    records.append(json.loads(line))
    return records


def generate_run_id(cluster_type: str) -> str:
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    return f"{ts}-{cluster_type}"


# ── Sub-commands ──────────────────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace) -> None:
    """Create a new run directory and metadata. Print the run-id to stdout."""
    run_id = args.run_id or generate_run_id(args.cluster_type)
    d = run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)

    meta = {
        "run_id": run_id,
        "cluster_type": args.cluster_type,
        "cluster_name": args.cluster_name,
        "region": args.region or os.environ.get("AWS_REGION", ""),
        "rosa_version": args.rosa_version or os.environ.get("ROSA_VERSION", ""),
        "started_at_ms": utc_now_ms(),
        "started_at": ms_to_iso(utc_now_ms()),
    }

    mf = metadata_file(run_id)
    # Preserve existing metadata if resuming the same run-id
    if not mf.exists():
        with mf.open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
            fh.write("\n")

    # Always print run-id to stdout so bash can capture it
    print(run_id)


def cmd_record(args: argparse.Namespace) -> None:
    """Append a timing event to the run's JSONL log."""
    end_ms = args.end_ms if args.end_ms is not None else utc_now_ms()
    elapsed_ms = end_ms - args.start_ms

    record: dict = {  # type: ignore[type-arg]
        "ts": end_ms,
        "iso": ms_to_iso(end_ms),
        "label": args.label,
        "start_ms": args.start_ms,
        "end_ms": end_ms,
        "elapsed_ms": elapsed_ms,
        "elapsed_human": elapsed_human(elapsed_ms),
        "cluster_type": args.cluster_type or "",
        "cluster_name": args.cluster_name or "",
    }

    # Parse any extra --meta key=value pairs
    meta: dict[str, str] = {}
    for kv in args.meta or []:
        if "=" in kv:
            k, v = kv.split("=", 1)
            meta[k] = v
    if meta:
        record["meta"] = meta

    append_jsonl(events_file(args.run_id), record)

    # Echo a human-readable confirmation to stderr (stdout is for scripts)
    print(
        f"[EVENT] {record['label']} — {record['elapsed_human']} "
        f"({record['elapsed_ms']} ms) @ {record['iso']}",
        file=sys.stderr,
    )


def cmd_list(args: argparse.Namespace) -> None:
    """Print all events for a run in human-readable form."""
    events = read_jsonl(events_file(args.run_id))
    if not events:
        print(f"No events found for run '{args.run_id}'.", file=sys.stderr)
        return

    print(f"\nEvents for run: {args.run_id}")
    print(f"{'Label':<45} {'Elapsed':>10}  {'Timestamp'}")
    print("-" * 80)
    for e in events:
        print(
            f"{e['label']:<45} {e['elapsed_human']:>10}  {e.get('iso', ms_to_iso(e['ts']))}"
        )
    print()


def cmd_summary(args: argparse.Namespace) -> None:
    """Print summary JSON with total elapsed and all timing milestones."""
    events = read_jsonl(events_file(args.run_id))
    if not events:
        print(json.dumps({"run_id": args.run_id, "events": []}))
        return

    # Load metadata if present
    mf = metadata_file(args.run_id)
    meta = {}
    if mf.exists():
        with mf.open(encoding="utf-8") as fh:
            meta = json.load(fh)

    summary = {
        "run_id": args.run_id,
        "cluster_type": meta.get("cluster_type", ""),
        "cluster_name": meta.get("cluster_name", ""),
        "started_at": meta.get("started_at", ""),
        "event_count": len(events),
        "events": [
            {
                "label": e["label"],
                "elapsed_ms": e["elapsed_ms"],
                "elapsed_human": e["elapsed_human"],
                "iso": e.get("iso", ms_to_iso(e["ts"])),
            }
            for e in events
        ],
    }
    print(json.dumps(summary, indent=2))


def cmd_ls(_args: argparse.Namespace) -> None:
    """List all available run IDs (most recent first)."""
    if not RESULTS_DIR.exists():
        print("No results directory found.", file=sys.stderr)
        return

    runs = sorted(
        [d for d in RESULTS_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    if not runs:
        print("No benchmark runs found in results/.", file=sys.stderr)
        return

    print(f"\n{'Run ID':<35} {'Cluster':<12} {'Events':>6}  Started")
    print("-" * 80)
    for d in runs:
        mf = d / "metadata.json"
        ef = d / "events.jsonl"
        cluster_type = ""
        started = ""
        if mf.exists():
            with mf.open(encoding="utf-8") as fh:
                m = json.load(fh)
            cluster_type = m.get("cluster_type", "")
            started = m.get("started_at", "")
        event_count = len(read_jsonl(ef)) if ef.exists() else 0
        print(f"{d.name:<35} {cluster_type:<12} {event_count:>6}  {started}")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Record and inspect benchmark timing events."
    )
    sub = p.add_subparsers(dest="command", required=True)

    # init
    pi = sub.add_parser("init", help="Initialize a new benchmark run.")
    pi.add_argument("--run-id", default="", help="Explicit run ID (auto-generated if blank)")
    pi.add_argument("--cluster-type", default="unknown", help="classic | hcp | hcp-karpenter")
    pi.add_argument("--cluster-name", default="", help="ROSA cluster name")
    pi.add_argument("--region", default="", help="AWS region")
    pi.add_argument("--rosa-version", default="", help="Resolved ROSA version")

    # record
    pr = sub.add_parser("record", help="Append a timing event.")
    pr.add_argument("--run-id", required=True)
    pr.add_argument("--label", required=True, help="Dot-notation label e.g. classic.cluster_ready")
    pr.add_argument("--start-ms", required=True, type=int, help="Epoch milliseconds")
    pr.add_argument("--end-ms", type=int, default=None, help="Epoch ms (defaults to now)")
    pr.add_argument("--cluster-type", default="")
    pr.add_argument("--cluster-name", default="")
    pr.add_argument("--meta", nargs="*", metavar="key=value", help="Extra metadata")

    # list
    pl = sub.add_parser("list", help="List all events for a run.")
    pl.add_argument("--run-id", required=True)

    # summary
    ps = sub.add_parser("summary", help="Print summary JSON for a run.")
    ps.add_argument("--run-id", required=True)

    # ls
    sub.add_parser("ls", help="List all available run IDs.")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "init": cmd_init,
        "record": cmd_record,
        "list": cmd_list,
        "summary": cmd_summary,
        "ls": cmd_ls,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
