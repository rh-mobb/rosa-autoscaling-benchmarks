#!/usr/bin/env python3
"""
scripts/collect-node-telemetry.py

Collect post-factum EC2 and in-cluster telemetry for one or more newly
provisioned nodes and emit structured milestone events to events.jsonl.

Nodes can be specified explicitly by name (--nodes) or discovered by label
selector (--node-selector). The two modes can be combined.

Data sources:
  1. oc get nodes                         → EC2 instance IDs from providerID
  2. aws cloudtrail lookup-events         → RunInstances time (when EC2 was launched)
  3. oc adm node-logs <node> -u <units>   → ignition + kubelet/crio systemd timestamps
  4. aws cloudwatch get-metric-statistics → StatusCheckFailed_Instance=0 (1-min res.)
  5. aws ec2 get-console-output           → raw serial output saved for LLM analysis
  6. oc debug node/<node>                 → systemd-analyze, blame, cloud-init log

Emitted events (elapsed from --since-ms):
  <prefix>.ec2_launch_requested   — CloudTrail RunInstances timestamp
  <prefix>.ignition_fetch_done    — systemd Started ignition-fetch.service
  <prefix>.ignition_disks_done    — systemd Started ignition-disks.service
  <prefix>.ignition_files_done    — systemd Started ignition-files.service
  <prefix>.ignition_complete      — systemd Started ignition-complete.service
  <prefix>.crio_started           — systemd Started crio.service
  <prefix>.kubelet_started        — systemd Started kubelet.service
  <prefix>.ec2_status_checks_ok   — CloudWatch StatusCheckFailed_Instance=0

Raw files saved to --raw-dir/nodes/<node-name>/:
  console.txt               — EC2 serial console output (64 KB)
  systemd-analyze.txt       — boot timing summary (from oc debug)
  systemd-analyze-blame.txt — per-unit start times (from oc debug)
  cloud-init.txt            — /var/log/cloud-init-output.log (from oc debug)

Usage (explicit nodes, e.g. from benchmark scripts):
  python3 scripts/collect-node-telemetry.py \\
    --nodes worker-abc-1 \\
    --run-id "${BENCHMARK_RUN_ID}" \\
    --region "${AWS_REGION}" \\
    --raw-dir "results/${BENCHMARK_RUN_ID}/raw" \\
    --prefix "test03.new_node" \\
    --cluster-type classic \\
    --cluster-name "${ROSA_CLUSTER_NAME}" \\
    --since-ms "${T_CAS_TRIGGERED}"

Usage (label selector, e.g. from machine pool scripts):
  python3 scripts/collect-node-telemetry.py \\
    --node-selector "pool-type=standard" \\
    --pool standard \\
    --run-id "${BENCHMARK_RUN_ID}" \\
    --region "${AWS_REGION}" \\
    --raw-dir "results/${BENCHMARK_RUN_ID}/raw" \\
    --prefix "pool.standard" \\
    --cluster-type classic \\
    --cluster-name "${ROSA_CLUSTER_NAME}" \\
    --since-ms "${T_POOL_START}"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).parent

# ── Journal log units to collect via oc adm node-logs ─────────────────────────
IGNITION_UNITS = [
    "ignition-fetch.service",
    "ignition-disks.service",
    "ignition-files.service",
    "ignition-complete.service",
]
SYSTEM_UNITS = ["crio.service", "kubelet.service"]

_UNIT_TO_LABEL: dict[str, str] = {
    "ignition-fetch.service": "ignition_fetch_done",
    "ignition-disks.service": "ignition_disks_done",
    "ignition-files.service": "ignition_files_done",
    "ignition-complete.service": "ignition_complete",
    "crio.service": "crio_started",
    "kubelet.service": "kubelet_started",
}

# Systemd "Started" line
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

# systemd-analyze output: "45.678s (userspace)" or "1min 23.456s (userspace)"
_USERSPACE_RE = re.compile(r"(\d+)min\s+(\d+(?:\.\d+)?)s\s+\(userspace\)")
_USERSPACE_RE_S = re.compile(r"(\d+(?:\.\d+)?)s\s+\(userspace\)")

# ── Helpers ───────────────────────────────────────────────────────────────────


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _emit(
    label: str,
    since_ms: int,
    end_ms: int,
    *,
    run_id: str,
    cluster_type: str,
    cluster_name: str,
    meta: dict[str, str] | None = None,
) -> None:
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
            f"[node-telemetry]  {label}: {elapsed_s // 60}m{elapsed_s % 60}s "
            f"@ {ms_to_dt(end_ms).isoformat()}",
            file=sys.stderr,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"[node-telemetry] WARNING: record failed for {label}: "
            f"{exc.stderr.decode(errors='replace')[:200]}",
            file=sys.stderr,
        )


def _run_oc(args: list[str], *, kubeconfig: str | None = None) -> str:
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


def get_nodes_by_selector(selector: str, *, kubeconfig: str | None) -> list[dict[str, Any]]:
    try:
        raw = _run_oc(["get", "nodes", "-l", selector, "-o", "json"], kubeconfig=kubeconfig)
        return json.loads(raw).get("items", [])
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"[node-telemetry] WARNING: could not list nodes by selector: {exc}", file=sys.stderr)
        return []


def get_nodes_by_names(names: list[str], *, kubeconfig: str | None) -> list[dict[str, Any]]:
    nodes = []
    for name in names:
        try:
            raw = _run_oc(["get", "node", name, "-o", "json"], kubeconfig=kubeconfig)
            nodes.append(json.loads(raw))
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(
                f"[node-telemetry] WARNING: could not get node '{name}': {exc}",
                file=sys.stderr,
            )
    return nodes


def extract_instance_id(provider_id: str) -> str | None:
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
    try:
        import boto3  # type: ignore[import]
        ct = boto3.client("cloudtrail", region_name=region)
    except Exception as exc:
        print(f"[node-telemetry] WARNING: CloudTrail unavailable ({exc})", file=sys.stderr)
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
        print(f"[node-telemetry] WARNING: CloudTrail lookup failed: {exc}", file=sys.stderr)
    return None


# ── Step 3: Node journal logs — ignition + kubelet ────────────────────────────


def parse_journal_timestamp(line: str, reference_year: int) -> int | None:
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


def collect_node_journal_logs(
    node_name: str,
    *,
    kubeconfig: str | None,
    reference_year: int,
) -> dict[str, int]:
    units = IGNITION_UNITS + SYSTEM_UNITS
    # The OpenShift API limits the query to 4 total arguments, meaning each
    # "-u unit_name" pair counts as 2 items → at most 2 units per call.
    # Batch into chunks of 2 and merge text before parsing timestamps.
    _MAX_UNITS_PER_CALL = 2
    log_parts: list[str] = []
    for i in range(0, len(units), _MAX_UNITS_PER_CALL):
        batch = units[i : i + _MAX_UNITS_PER_CALL]
        oc_args = ["adm", "node-logs", node_name] + [
            flag for u in batch for flag in ("-u", u)
        ]
        try:
            log_parts.append(_run_oc(oc_args, kubeconfig=kubeconfig))
        except RuntimeError as exc:
            print(
                f"[node-telemetry] WARNING: node-logs failed for {node_name}: {exc}",
                file=sys.stderr,
            )
    log_text = "\n".join(log_parts)

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
            unit_name = unit.replace(".service", "")
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
    try:
        import boto3  # type: ignore[import]
        cw = boto3.client("cloudwatch", region_name=region)
    except Exception as exc:
        print(f"[node-telemetry] WARNING: CloudWatch unavailable ({exc})", file=sys.stderr)
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
            f"[node-telemetry] WARNING: CloudWatch query failed for {instance_id}: {exc}",
            file=sys.stderr,
        )
    return None


# ── Step 5: EC2 serial console output ────────────────────────────────────────


def fetch_console_output(instance_id: str, *, region: str) -> str:
    try:
        import boto3  # type: ignore[import]
        ec2 = boto3.client("ec2", region_name=region)
        resp = ec2.get_console_output(InstanceId=instance_id, Latest=True)
        return resp.get("Output", "") or ""
    except Exception as exc:
        print(
            f"[node-telemetry] WARNING: get-console-output failed for {instance_id}: {exc}",
            file=sys.stderr,
        )
        return ""


# ── Step 6: oc debug — systemd-analyze + cloud-init ──────────────────────────


def _split_debug_sections(output: str) -> dict[str, str]:
    """Split oc debug output by '=== Section ===' delimiters."""
    sections: dict[str, str] = {}
    current_section: str | None = None
    lines: list[str] = []
    for line in output.splitlines():
        m = re.match(r"^=== (.+?) ===\s*$", line)
        if m:
            if current_section is not None:
                sections[current_section] = "\n".join(lines).strip()
            current_section = m.group(1)
            lines = []
        elif current_section is not None:
            lines.append(line)
    if current_section is not None:
        sections[current_section] = "\n".join(lines).strip()
    return sections


def _parse_userspace_s(text: str) -> float | None:
    """Extract userspace startup duration in seconds from systemd-analyze output."""
    m2 = _USERSPACE_RE.search(text)
    if m2:
        return int(m2.group(1)) * 60 + float(m2.group(2))
    m1 = _USERSPACE_RE_S.search(text)
    if m1:
        return float(m1.group(1))
    return None


def collect_oc_debug(
    node_name: str,
    *,
    kubeconfig: str | None,
    raw_dir: Path,
    timeout_s: int = 150,
) -> dict[str, str]:
    """
    Run a single oc debug session on node_name to collect:
      - systemd-analyze (boot timing summary)
      - systemd-analyze blame (top 30 per-unit start times)
      - /var/log/cloud-init-output.log

    Saves raw output to raw_dir/nodes/<node-name>/.
    Returns metadata dict (e.g. {"boot_userspace_s": "47.3"}).
    Non-fatal: returns {} on any error.
    """
    node_raw_dir = raw_dir / "nodes" / node_name
    node_raw_dir.mkdir(parents=True, exist_ok=True)

    # Combine all commands in one debug session to minimise pod startup overhead.
    # oc debug spins up a privileged pod; one session is ~30-60s vs 3x 30-60s.
    debug_script = textwrap.dedent("""\
        echo '=== systemd-analyze ==='
        systemd-analyze 2>&1 || echo 'N/A'
        echo '=== systemd-analyze blame ==='
        systemd-analyze blame 2>&1 | head -30 || echo 'N/A'
        echo '=== cloud-init ==='
        cat /var/log/cloud-init-output.log 2>/dev/null || echo 'NOT_FOUND'
    """)

    env = os.environ.copy()
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    cmd = [
        "oc", "debug", f"node/{node_name}",
        "--", "chroot", "/host", "sh", "-c", debug_script,
    ]

    print(
        f"[node-telemetry] Running oc debug on {node_name} (timeout {timeout_s}s) ...",
        file=sys.stderr,
    )

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_s,
        )
        # oc debug often writes status to stderr; prefer stdout for actual output
        output = proc.stdout or proc.stderr or ""
    except subprocess.TimeoutExpired:
        print(
            f"[node-telemetry] WARNING: oc debug timed out after {timeout_s}s for {node_name}.",
            file=sys.stderr,
        )
        return {}
    except FileNotFoundError:
        print("[node-telemetry] WARNING: oc not found; skipping oc debug.", file=sys.stderr)
        return {}
    except Exception as exc:
        print(
            f"[node-telemetry] WARNING: oc debug failed for {node_name}: {exc}",
            file=sys.stderr,
        )
        return {}

    if not output.strip():
        print(
            f"[node-telemetry] WARNING: oc debug produced no output for {node_name}.",
            file=sys.stderr,
        )
        return {}

    sections = _split_debug_sections(output)
    analyze_text = sections.get("systemd-analyze", "")
    blame_text = sections.get("systemd-analyze blame", "")
    cloud_init_text = sections.get("cloud-init", "")

    if analyze_text:
        (node_raw_dir / "systemd-analyze.txt").write_text(analyze_text, encoding="utf-8")
    if blame_text:
        (node_raw_dir / "systemd-analyze-blame.txt").write_text(blame_text, encoding="utf-8")
    if cloud_init_text and "NOT_FOUND" not in cloud_init_text:
        (node_raw_dir / "cloud-init.txt").write_text(cloud_init_text, encoding="utf-8")

    meta: dict[str, str] = {}
    if analyze_text:
        userspace_s = _parse_userspace_s(analyze_text)
        if userspace_s is not None:
            meta["boot_userspace_s"] = f"{userspace_s:.1f}"
            print(
                f"[node-telemetry] {node_name}: boot userspace={userspace_s:.1f}s",
                file=sys.stderr,
            )

    print(
        f"[node-telemetry] oc debug output saved to {node_raw_dir}",
        file=sys.stderr,
    )
    return meta


# ── CLI ───────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Collect post-factum EC2 and in-cluster telemetry for newly provisioned nodes."
    )
    # Node selection — at least one of these must be provided
    node_group = p.add_mutually_exclusive_group()
    node_group.add_argument(
        "--nodes",
        nargs="+",
        metavar="NODE",
        default=[],
        help="Explicit node names (e.g. worker-abc-1 worker-abc-2)",
    )
    node_group.add_argument(
        "--node-selector",
        default="",
        help="Label selector to discover nodes (e.g. pool-type=standard)",
    )
    p.add_argument("--cluster", required=True, help="ROSA cluster name (for rosa CLI calls)")
    p.add_argument("--pool", default="", help="Pool/context name used for log messages only")
    p.add_argument("--run-id", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--raw-dir", required=True, help="Directory for raw output files")
    p.add_argument("--prefix", required=True, help="Event label prefix, e.g. pool.standard")
    p.add_argument("--cluster-type", default="classic")
    p.add_argument("--cluster-name", default="")
    p.add_argument(
        "--since-ms",
        type=int,
        default=0,
        help="Search window start (epoch ms). Defaults to 1 hour ago.",
    )
    p.add_argument("--kubeconfig", default="")
    p.add_argument(
        "--no-oc-debug",
        action="store_true",
        help="Skip the oc debug step (systemd-analyze / cloud-init collection)",
    )
    p.add_argument(
        "--oc-debug-timeout",
        type=int,
        default=150,
        help="Timeout in seconds for the oc debug session (default: 150)",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    if not args.nodes and not args.node_selector:
        print(
            "[node-telemetry] ERROR: provide --nodes or --node-selector.",
            file=sys.stderr,
        )
        sys.exit(1)

    kubeconfig = args.kubeconfig or None
    since_ms = args.since_ms or (now_ms() - 3600_000)
    since_dt = ms_to_dt(since_ms)
    until_dt = datetime.now(tz=UTC)
    cluster_name = args.cluster_name or args.cluster
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    context_label = args.pool or (args.nodes[0] if args.nodes else args.node_selector)
    print(
        f"[node-telemetry] Starting collection for '{context_label}' "
        f"(since {since_dt.isoformat()}) ...",
        file=sys.stderr,
    )

    emit_kwargs = dict(
        run_id=args.run_id,
        cluster_type=args.cluster_type,
        cluster_name=cluster_name,
    )

    # ── Step 1: Discover nodes ────────────────────────────────────────────────
    if args.nodes:
        nodes = get_nodes_by_names(args.nodes, kubeconfig=kubeconfig)
    else:
        nodes = get_nodes_by_selector(args.node_selector, kubeconfig=kubeconfig)

    if not nodes:
        print(
            "[node-telemetry] WARNING: no nodes found. "
            "Verify oc is logged in and nodes are Ready.",
            file=sys.stderr,
        )
        sys.exit(0)

    print(f"[node-telemetry] Found {len(nodes)} node(s).", file=sys.stderr)

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
                f"[node-telemetry] WARNING: could not parse instance ID from "
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
                "[node-telemetry] INFO: CloudTrail RunInstances not found "
                "(may still be propagating — retry in a few minutes if needed).",
                file=sys.stderr,
            )

    # ── Step 3: Node journal (ignition + kubelet) ─────────────────────────────
    # Collect journal milestones for the first node only (representative sample).
    if nodes:
        first_node = nodes[0].get("metadata", {}).get("name", "")
        journal_milestones = collect_node_journal_logs(
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
                f"[node-telemetry] INFO: No journal milestones extracted for node "
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

    # ── Step 5: Serial console output (raw save) ──────────────────────────────
    for iid in instance_ids:
        output = fetch_console_output(iid, region=args.region)
        node_for_iid = next((n for n, i in node_to_iid.items() if i == iid), iid)
        if output:
            # Save per-node under nodes/<name>/ if we have a name, else flat in raw_dir
            if node_for_iid != iid:
                node_raw_dir = raw_dir / "nodes" / node_for_iid
                node_raw_dir.mkdir(parents=True, exist_ok=True)
                console_path = node_raw_dir / "console.txt"
            else:
                console_path = raw_dir / f"console-{iid}.txt"
            console_path.write_text(output, encoding="utf-8")
            print(
                f"[node-telemetry] Console output saved: {console_path} ({len(output):,} bytes)",
                file=sys.stderr,
            )
        else:
            print(
                f"[node-telemetry] INFO: No console output available for {iid} yet.",
                file=sys.stderr,
            )

    # ── Step 6: oc debug — systemd-analyze + cloud-init ──────────────────────
    # Collect from the first node only to keep total runtime reasonable.
    if not args.no_oc_debug and nodes:
        first_node = nodes[0].get("metadata", {}).get("name", "")
        debug_meta = collect_oc_debug(
            first_node,
            kubeconfig=kubeconfig,
            raw_dir=raw_dir,
            timeout_s=args.oc_debug_timeout,
        )
        if debug_meta:
            _emit(
                f"{args.prefix}.oc_debug_collected",
                since_ms,
                now_ms(),
                meta={**debug_meta, "node": first_node},
                **emit_kwargs,
            )

    print(f"[node-telemetry] Collection complete for '{context_label}'.", file=sys.stderr)


if __name__ == "__main__":
    main()
