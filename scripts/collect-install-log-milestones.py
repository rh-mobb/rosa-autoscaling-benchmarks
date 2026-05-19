#!/usr/bin/env python3
"""
scripts/collect-install-log-milestones.py

Fetch ROSA Classic install logs post-install, extract known OpenShift installer
milestone strings (with their embedded ISO timestamps), emit them to events.jsonl,
and save the full raw log for later LLM analysis.

Call this AFTER wait_for_cluster_state returns "ready".  The installer log is
retained by OCM/ROSA even after the cluster is up, so a one-shot fetch works
reliably and avoids the fragility of long-lived --watch connections.

Usage:
  python3 scripts/collect-install-log-milestones.py \\
    --cluster      "${ROSA_CLUSTER_NAME}" \\
    --run-id       "${BENCHMARK_RUN_ID}" \\
    --raw-dir      "results/${BENCHMARK_RUN_ID}/raw" \\
    --since-ms     "${T_START}" \\
    --prefix       "classic.install_log" \\
    --cluster-type classic \\
    --cluster-name "${ROSA_CLUSTER_NAME}"

  # Read from a saved file instead (testing / offline replay):
  python3 scripts/collect-install-log-milestones.py \\
    --log-file     results/my-run/raw/install.log \\
    --run-id       "${BENCHMARK_RUN_ID}" \\
    --raw-dir      results/my-run/raw \\
    --since-ms     "${T_START}"
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent

# ── Milestone patterns ────────────────────────────────────────────────────────
# Each tuple: (regex pattern, label_suffix).
# Patterns are case-insensitive.  Only the first occurrence of each label is
# recorded; duplicate lines (retries, echoes) are skipped.
MILESTONES: list[tuple[str, str]] = [
    (r"creating infrastructure resources", "infra_creating"),
    (r"waiting for the kubernetes api|waiting for api", "waiting_for_api"),
    (r"\bapi v[\d.]+ up\b", "api_reachable"),
    (r"bootstrap complete", "bootstrap_complete"),
    (r"destroying the bootstrap|removing the bootstrap", "bootstrap_destroying"),
    (r"bootstrap destroyed|bootstrap removed", "bootstrap_destroyed"),
    (r"waiting for the cluster version", "waiting_for_cluster_version"),
    (r"cluster version operator initialized", "cluster_version_init"),
    (r"install complete", "install_complete"),
]

_COMPILED = [(re.compile(pat, re.IGNORECASE), label) for pat, label in MILESTONES]

# ── Timestamp extraction ──────────────────────────────────────────────────────
# Handles three common installer log formats:
#   Logrus key=value:  time="2026-05-09T01:23:45Z" level=info msg="..."
#   JSON:              {"time":"2026-05-09T01:23:45Z","level":"info","msg":"..."}
#   Logrus no-quotes:  time=2026-05-09T01:23:45Z level=info msg=...
_TS_PATTERNS = [
    re.compile(r'time="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?)"'),
    re.compile(r'"time"\s*:\s*"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?)"'),
    re.compile(r'\btime=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)\b'),
]


def extract_timestamp_ms(line: str) -> int | None:
    """Extract the ISO timestamp embedded in a log line; return epoch milliseconds."""
    for pat in _TS_PATTERNS:
        m = pat.search(line)
        if m:
            ts_str = m.group(1)
            try:
                if ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return int(dt.timestamp() * 1000)
            except ValueError:
                pass
    return None


# ── Log parsing ───────────────────────────────────────────────────────────────


def parse_install_log(content: str) -> list[tuple[str, int]]:
    """
    Scan install log content for known milestone patterns.

    Returns a list of (label_suffix, epoch_ms) tuples sorted by timestamp.
    Only the first occurrence of each label is kept.
    Lines without a parseable timestamp are skipped with a warning.
    """
    found: dict[str, int] = {}
    for line in content.splitlines():
        for pattern, label in _COMPILED:
            if label in found:
                continue
            if pattern.search(line):
                ts_ms = extract_timestamp_ms(line)
                if ts_ms is not None:
                    found[label] = ts_ms
                else:
                    print(
                        f"[install-log] WARNING: '{label}' matched but no timestamp "
                        f"in line: {line[:120]}",
                        file=sys.stderr,
                    )
    return sorted(found.items(), key=lambda kv: kv[1])


# ── ROSA log fetch ────────────────────────────────────────────────────────────


def fetch_install_log(cluster: str) -> str:
    """
    Run `rosa logs install -c <cluster>` and return the full stdout.

    Exits non-zero from rosa is treated as a warning (partial log is still
    saved and processed).
    """
    print(f"[install-log] Fetching install logs for cluster '{cluster}' ...", file=sys.stderr)
    try:
        result = subprocess.run(
            ["rosa", "logs", "install", "-c", cluster],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(
                f"[install-log] WARNING: rosa logs install exited {result.returncode}: "
                f"{result.stderr.strip()[:300]}",
                file=sys.stderr,
            )
        return result.stdout
    except FileNotFoundError:
        print("[install-log] ERROR: rosa CLI not found in PATH.", file=sys.stderr)
        return ""
    except subprocess.TimeoutExpired:
        print("[install-log] ERROR: rosa logs install timed out after 120s.", file=sys.stderr)
        return ""


# ── Milestone recording ───────────────────────────────────────────────────────


def record_milestone(
    label: str,
    since_ms: int,
    end_ms: int,
    *,
    run_id: str,
    cluster_type: str,
    cluster_name: str,
) -> None:
    """Persist a milestone event via record-event.py."""
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "record-event.py"),
        "record",
        "--run-id", run_id,
        "--label", label,
        "--start-ms", str(since_ms),
        "--end-ms", str(end_ms),
        "--cluster-type", cluster_type,
        "--cluster-name", cluster_name,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        print(
            f"[install-log] WARNING: record-event.py failed for {label}: "
            f"{exc.stderr.decode(errors='replace')[:200]}",
            file=sys.stderr,
        )


# ── CLI ───────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Collect ROSA Classic install log milestones post-install."
    )
    p.add_argument("--cluster", default="", help="ROSA cluster name (required unless --log-file)")
    p.add_argument("--run-id", required=True)
    p.add_argument("--raw-dir", required=True, help="Directory to save raw install.log")
    p.add_argument(
        "--since-ms",
        type=int,
        default=0,
        help="Cluster creation T_START epoch ms; used as start_ms for all emitted events",
    )
    p.add_argument("--prefix", default="classic.install_log")
    p.add_argument("--cluster-type", default="classic")
    p.add_argument("--cluster-name", default="")
    p.add_argument(
        "--log-file",
        default="",
        help="Read log from this file instead of running rosa (useful for testing / replay)",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    if not args.cluster and not args.log_file:
        print("[install-log] ERROR: --cluster or --log-file is required.", file=sys.stderr)
        sys.exit(1)

    # Fetch or read log content
    if args.log_file:
        content = Path(args.log_file).read_text(encoding="utf-8", errors="replace")
        print(f"[install-log] Reading log from file: {args.log_file}", file=sys.stderr)
    else:
        content = fetch_install_log(args.cluster)

    if not content.strip():
        print("[install-log] WARNING: No install log content. Nothing to record.", file=sys.stderr)
        sys.exit(0)

    # Persist raw log
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "install.log"
    raw_path.write_text(content, encoding="utf-8")
    print(f"[install-log] Raw log saved: {raw_path} ({len(content):,} bytes)", file=sys.stderr)

    # Parse milestones
    milestones = parse_install_log(content)
    if not milestones:
        print(
            "[install-log] WARNING: No recognized milestone patterns found in log.",
            file=sys.stderr,
        )
        sys.exit(0)

    # Baseline: prefer --since-ms, fall back to timestamp of the first milestone
    since_ms = args.since_ms or milestones[0][1]
    cluster_name = args.cluster_name or args.cluster

    print(f"[install-log] Emitting {len(milestones)} milestone(s)...", file=sys.stderr)
    for label_suffix, end_ms in milestones:
        full_label = f"{args.prefix}.{label_suffix}"
        iso = datetime.fromtimestamp(end_ms / 1000, tz=UTC).isoformat()
        elapsed_s = (end_ms - since_ms) // 1000
        print(
            f"[install-log]  {full_label}: {elapsed_s // 60}m{elapsed_s % 60}s @ {iso}",
            file=sys.stderr,
        )
        record_milestone(
            full_label,
            since_ms,
            end_ms,
            run_id=args.run_id,
            cluster_type=args.cluster_type,
            cluster_name=cluster_name,
        )

    print(f"[install-log] Done: {len(milestones)} milestone(s) recorded.", file=sys.stderr)


if __name__ == "__main__":
    main()
