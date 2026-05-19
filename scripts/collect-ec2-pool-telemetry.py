#!/usr/bin/env python3
"""
scripts/collect-ec2-pool-telemetry.py

Collect post-factum EC2 and in-cluster telemetry for a newly provisioned
machine pool and emit structured milestone events to events.jsonl.

All data sources are queried AFTER the pool is Ready — no background process
or polling daemon required.

Data sources:
  1. oc get nodes -l <selector>          → node names + EC2 instance IDs (providerID)
  2. aws cloudtrail lookup-events        → RunInstances time (when MachineAPI called EC2)
  3. oc adm node-logs <node> -u <units>  → ignition + kubelet/crio systemd timestamps
  4. aws cloudwatch get-metric-statistics → StatusCheckFailed_Instance → 0 (1-min res.)
  5. aws ec2 get-console-output          → raw serial output saved for LLM analysis

Emitted events (all elapsed from --since-ms = T_POOL_START):
  pool.<name>.ec2_launch_requested   — CloudTrail RunInstances timestamp
  pool.<name>.ignition_fetch_done    — systemd Started ignition-fetch.service
  pool.<name>.ignition_disks_done    — systemd Started ignition-disks.service
  pool.<name>.ignition_files_done    — systemd Started ignition-files.service
  pool.<name>.ignition_complete      — systemd Started ignition-complete.service
  pool.<name>.crio_started           — systemd Started crio.service
  pool.<name>.kubelet_started        — systemd Started kubelet.service
  pool.<name>.ec2_status_checks_ok   — CloudWatch StatusCheckFailed_Instance=0

Usage:
  python3 scripts/collect-ec2-pool-telemetry.py \\
    --cluster       "${ROSA_CLUSTER_NAME}" \\
    --pool          "${pool_name}" \\
    --node-selector "${node_selector}" \\
    --run-id        "${BENCHMARK_RUN_ID}" \\
    --region        "${AWS_REGION}" \\
    --raw-dir       "results/${BENCHMARK_RUN_ID}/raw" \\
    --prefix        "pool.${pool_name}" \\
    --cluster-type  classic \\
    --cluster-name  "${ROSA_CLUSTER_NAME}" \\
    --since-ms      "${T_POOL_START}"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).parent

# ── Journal log units to collect ─────────────────────────────────────────────
IGNITION_UNITS = [
    "ignition-fetch.service",
    "ignition-disks.service",
    "ignition-files.service",
    "ignition-complete.service",
]
SYSTEM_UNITS = ["crio.service", "kubelet.service"]

# Map unit name → event label suffix
_UNIT_TO_LABEL: dict[str, str] = {
    "ignition-fetch.service": "ignition_fetch_done",
    "ignition-disks.service": "ignition_disks_done",
    "ignition-files.service": "ignition_files_done",
    "ignition-complete.service": "ignition_complete",
    "crio.service": "crio_started",
    "kubelet.service": "kubelet_started",
}

# Systemd "Started" line: marks when a unit transitions to active
_STARTED_RE = re.compile(r"systemd\[\d+\]:\s+Started\b", re.IGNORECASE)

# Journal timestamp prefix: "May 08 02:10:30" (no year)
_JOURNAL_TS_RE = re.compile(r"^(\w{3})\s{1,2}(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s")

_MONTH_MAP: dict[str, int] = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        1,
    )
}

# ── Helpers ───────────────────────────────────────────────────────────────────


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _emit(label: str, since_ms: int, end_ms: int, *, run_id: str,
          cluster_type: str, cluster_name: str,
          meta: dict[str, str] | None = None) -> None:
    """Persist a milestone via record-event.py and print confirmation."""
    if not run_id:
        return
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
    if meta:
        cmd += ["--meta"] + [f"{k}={v}" for k, v in meta.items()]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        elapsed_s = (end_ms - since_ms) // 1000
        print(
            f"[ec2-telemetry]  {label}: {elapsed_s // 60}m{elapsed_s % 60}s "
            f"@ {ms_to_dt(end_ms).isoformat()}",
            file=sys.stderr,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"[ec2-telemetry] WARNING: record failed for {label}: "
            f"{exc.stderr.decode(errors='replace')[:200]}",
            file=sys.stderr,
        )


def _run_oc(args: list[str], *, kubeconfig: str | None = None) -> str:
    """Run oc and return stdout. Raises RuntimeError on non-zero exit."""
    env = os.environ.copy()
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    result = subprocess.run(["oc", *args], capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"oc {' '.join(args[:4])} failed (exit {result.returncode}): "
            f"{result.stderr.strip()[:300]}"
        )
    return result.stdout


# ── Step 1: Node discovery ────────────────────────────────────────────────────


def get_pool_nodes(node_selector: str, *, kubeconfig: str | None) -> list[dict[str, Any]]:
    """Return node objects matching node_selector."""
    try:
        raw = _run_oc(["get", "nodes", "-l", node_selector, "-o", "json"], kubeconfig=kubeconfig)
        return json.loads(raw).get("items", [])
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"[ec2-telemetry] WARNING: could not list nodes: {exc}", file=sys.stderr)
        return []


def extract_instance_id(provider_id: str) -> str | None:
    """
    Extract EC2 instance ID from a Kubernetes node providerID.
    Expected format: aws:///us-east-1a/i-0abc1234def56789
    """
    m = re.search(r"/(i-[0-9a-f]+)$", provider_id)
    return m.group(1) if m else None


# ── Step 2: CloudTrail — RunInstances ─────────────────────────────────────────


def find_run_instances_time(
    instance_ids: list[str],
    *,
    region: str,
    since_dt: datetime,
    until_dt: datetime,
) -> datetime | None:
    """
    Find the CloudTrail RunInstances event that launched these instances.

    CloudTrail events typically appear within 5-15 minutes after the API call;
    since we run this after the node is Ready (~5-20 min), they should be visible.
    Returns the event time, or None if not found or boto3 unavailable.
    """
    try:
        import boto3  # type: ignore[import]
        ct = boto3.client("cloudtrail", region_name=region)
    except Exception as exc:
        print(f"[ec2-telemetry] WARNING: CloudTrail unavailable ({exc})", file=sys.stderr)
        return None

    target_ids = set(instance_ids)
    try:
        paginator = ct.get_paginator("lookup_events")
        pages = paginator.paginate(
            LookupAttributes=[
                {"AttributeKey": "EventName", "AttributeValue": "RunInstances"}
            ],
            StartTime=since_dt,
            EndTime=until_dt,
        )
        for page in pages:
            for event in page.get("Events", []):
                try:
                    detail = json.loads(event.get("CloudTrailEvent", "{}"))
                    launched = {
                        item["instanceId"]
                        for item in (
                            detail.get("responseElements", {})
                            .get("instancesSet", {})
                            .get("items", [])
                        )
                        if "instanceId" in item
                    }
                    if launched & target_ids:
                        et: datetime = event["EventTime"]
                        if et.tzinfo is None:
                            et = et.replace(tzinfo=UTC)
                        return et
                except (KeyError, json.JSONDecodeError, TypeError):
                    continue
    except Exception as exc:
        print(f"[ec2-telemetry] WARNING: CloudTrail lookup failed: {exc}", file=sys.stderr)
    return None


# ── Step 3: Node journal logs — ignition + kubelet ────────────────────────────


def parse_journal_timestamp(line: str, reference_year: int) -> int | None:
    """
    Parse the leading timestamp of a systemd journal line ('May 08 02:10:30')
    into epoch milliseconds, using reference_year for the year component.

    If the result is more than 30 days in the future, subtract one year to
    handle year-boundary edge cases.
    """
    m = _JOURNAL_TS_RE.match(line)
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(1))
    if not month:
        return None
    try:
        h, mi, s = (int(x) for x in m.group(3).split(":"))
        dt = datetime(reference_year, month, int(m.group(2)), h, mi, s, tzinfo=UTC)
        if dt > datetime.now(tz=UTC) + timedelta(days=30):
            dt = dt.replace(year=reference_year - 1)
        return int(dt.timestamp() * 1000)
    except (ValueError, OverflowError):
        return None


def collect_node_logs(
    node_name: str,
    *,
    kubeconfig: str | None,
    reference_year: int,
) -> dict[str, int]:
    """
    Fetch ignition + kubelet/crio journal for node_name and return
    {label_suffix: epoch_ms} for each service's first "Started" line.
    """
    units = IGNITION_UNITS + SYSTEM_UNITS
    oc_args = ["adm", "node-logs", node_name] + [
        flag for u in units for flag in ("-u", u)
    ]
    try:
        log_text = _run_oc(oc_args, kubeconfig=kubeconfig)
    except RuntimeError as exc:
        print(f"[ec2-telemetry] WARNING: node-logs failed for {node_name}: {exc}", file=sys.stderr)
        return {}

    milestones: dict[str, int] = {}
    for line in log_text.splitlines():
        if not _STARTED_RE.search(line):
            continue
        ts_ms = parse_journal_timestamp(line, reference_year)
        if ts_ms is None:
            continue
        line_lower = line.lower()
        for unit, label in _UNIT_TO_LABEL.items():
            if label in milestones:
                continue
            unit_name = unit.replace(".service", "")  # e.g. "ignition-fetch"
            if unit_name in line_lower:
                milestones[label] = ts_ms
                break
    return milestones


# ── Step 4: CloudWatch — StatusCheckFailed_Instance ──────────────────────────


def find_status_check_ok_time(
    instance_id: str,
    *,
    region: str,
    since_dt: datetime,
    until_dt: datetime,
) -> datetime | None:
    """
    Find the first 1-minute window where StatusCheckFailed_Instance=0.
    Returns the datapoint timestamp or None.
    """
    try:
        import boto3  # type: ignore[import]
        cw = boto3.client("cloudwatch", region_name=region)
    except Exception as exc:
        print(f"[ec2-telemetry] WARNING: CloudWatch unavailable ({exc})", file=sys.stderr)
        return None

    try:
        resp = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="StatusCheckFailed_Instance",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=since_dt,
            EndTime=until_dt + timedelta(minutes=5),
            Period=60,
            Statistics=["Maximum"],
        )
        for dp in sorted(resp.get("Datapoints", []), key=lambda d: d["Timestamp"]):
            if dp.get("Maximum", 1) == 0:
                ts: datetime = dp["Timestamp"]
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                return ts
    except Exception as exc:
        print(
            f"[ec2-telemetry] WARNING: CloudWatch query failed for {instance_id}: {exc}",
            file=sys.stderr,
        )
    return None


# ── Step 5: EC2 serial console output ────────────────────────────────────────


def fetch_console_output(instance_id: str, *, region: str) -> str:
    """Fetch EC2 serial console output (up to 64 KB). Returns empty string on failure."""
    try:
        import boto3  # type: ignore[import]
        ec2 = boto3.client("ec2", region_name=region)
        resp = ec2.get_console_output(InstanceId=instance_id, Latest=True)
        return resp.get("Output", "") or ""
    except Exception as exc:
        print(
            f"[ec2-telemetry] WARNING: get-console-output failed for {instance_id}: {exc}",
            file=sys.stderr,
        )
        return ""


# ── CLI ───────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Collect post-factum EC2/cluster telemetry for a machine pool."
    )
    p.add_argument("--cluster", required=True)
    p.add_argument("--pool", required=True, help="Machine pool name (for labeling only)")
    p.add_argument("--node-selector", required=True, help="e.g. pool-type=standard")
    p.add_argument("--run-id", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--raw-dir", required=True, help="Directory for raw console output files")
    p.add_argument("--prefix", required=True, help="Event label prefix, e.g. pool.standard")
    p.add_argument("--cluster-type", default="classic")
    p.add_argument("--cluster-name", default="")
    p.add_argument(
        "--since-ms",
        type=int,
        default=0,
        help="T_POOL_START epoch ms; used as start_ms for all emitted events",
    )
    p.add_argument("--kubeconfig", default="")
    return p


def main() -> None:
    args = build_parser().parse_args()

    kubeconfig = args.kubeconfig or None
    since_ms = args.since_ms or (now_ms() - 3600_000)  # default: 1 h ago
    since_dt = ms_to_dt(since_ms)
    until_dt = datetime.now(tz=UTC)
    cluster_name = args.cluster_name or args.cluster
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    emit_kwargs = dict(
        run_id=args.run_id,
        cluster_type=args.cluster_type,
        cluster_name=cluster_name,
    )

    print(
        f"[ec2-telemetry] Starting collection for pool '{args.pool}' "
        f"(since {since_dt.isoformat()}) ...",
        file=sys.stderr,
    )

    # ── Step 1: Discover nodes ────────────────────────────────────────────────
    nodes = get_pool_nodes(args.node_selector, kubeconfig=kubeconfig)
    if not nodes:
        print(
            f"[ec2-telemetry] WARNING: no nodes found for selector '{args.node_selector}'. "
            "Verify oc is logged in and the pool nodes are Ready.",
            file=sys.stderr,
        )
        sys.exit(0)

    print(f"[ec2-telemetry] Found {len(nodes)} node(s).", file=sys.stderr)

    instance_ids: list[str] = []
    node_to_iid: dict[str, str] = {}
    for node in nodes:
        name = node.get("metadata", {}).get("name", "")
        pid = node.get("spec", {}).get("providerID", "")
        iid = extract_instance_id(pid)
        if iid:
            instance_ids.append(iid)
            node_to_iid[name] = iid
        else:
            print(
                f"[ec2-telemetry] WARNING: could not parse instance ID from "
                f"providerID '{pid}' (node {name})",
                file=sys.stderr,
            )

    # ── Step 2: CloudTrail RunInstances ──────────────────────────────────────
    if instance_ids:
        run_instances_dt = find_run_instances_time(
            instance_ids, region=args.region, since_dt=since_dt, until_dt=until_dt
        )
        if run_instances_dt:
            _emit(
                f"{args.prefix}.ec2_launch_requested",
                since_ms,
                int(run_instances_dt.timestamp() * 1000),
                meta={"instance_ids": ",".join(instance_ids[:3])},
                **emit_kwargs,
            )
        else:
            print(
                "[ec2-telemetry] INFO: CloudTrail RunInstances not found "
                "(may still be propagating — retry in a few minutes if needed).",
                file=sys.stderr,
            )

    # ── Step 3: Node journal (ignition + kubelet) ─────────────────────────────
    if nodes:
        first_node = nodes[0].get("metadata", {}).get("name", "")
        journal_milestones = collect_node_logs(
            first_node,
            kubeconfig=kubeconfig,
            reference_year=datetime.now(tz=UTC).year,
        )
        for label_suffix, end_ms in sorted(journal_milestones.items(), key=lambda kv: kv[1]):
            _emit(
                f"{args.prefix}.{label_suffix}",
                since_ms,
                end_ms,
                meta={"node": first_node},
                **emit_kwargs,
            )
        if not journal_milestones:
            print(
                f"[ec2-telemetry] INFO: No journal milestones extracted for node "
                f"'{first_node}' (unit logs may be unavailable on HCP).",
                file=sys.stderr,
            )

    # ── Step 4: CloudWatch StatusCheckFailed ─────────────────────────────────
    if instance_ids:
        first_iid = instance_ids[0]
        sc_dt = find_status_check_ok_time(
            first_iid, region=args.region, since_dt=since_dt, until_dt=until_dt
        )
        if sc_dt:
            _emit(
                f"{args.prefix}.ec2_status_checks_ok",
                since_ms,
                int(sc_dt.timestamp() * 1000),
                meta={"instance_id": first_iid, "resolution": "1min"},
                **emit_kwargs,
            )

    # ── Step 5: Serial console output (raw save for LLM) ─────────────────────
    for iid in instance_ids:
        output = fetch_console_output(iid, region=args.region)
        if output:
            console_path = raw_dir / f"console-{iid}.txt"
            console_path.write_text(output, encoding="utf-8")
            print(
                f"[ec2-telemetry] Console output saved: {console_path} ({len(output):,} bytes)",
                file=sys.stderr,
            )
        else:
            print(
                f"[ec2-telemetry] INFO: No console output available for {iid} yet.",
                file=sys.stderr,
            )

    print(f"[ec2-telemetry] Collection complete for pool '{args.pool}'.", file=sys.stderr)


if __name__ == "__main__":
    main()
