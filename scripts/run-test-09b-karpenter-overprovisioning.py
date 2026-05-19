#!/usr/bin/env python3
"""
scripts/run-test-09b-karpenter-overprovisioning.py

Benchmark: Overprovisioning with pause pods on HCP AutoNode / Karpenter (Test 09b)

Mirrors run-test-09-overprovisioning.py, substituting Karpenter-aware manifests
(nodeAffinity: karpenter.sh/nodepool=autonode-bench) so balloon pods land on
Karpenter-managed nodes. Milestone names match Test 09 for side-by-side comparison.

Usage:
  python3 scripts/run-test-09b-karpenter-overprovisioning.py \\
      --cluster-name <name> \\
      --cluster-type hcp-autonode \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--nodepool-name autonode-bench] \\
      [--cpu-burner-replicas 3] \\
      [--require-saturated-before-balloons] \\
      [--max-slack-cpu-cores 2] \\
      [--karpenter-pack-max-rounds 15] \\
      [--karpenter-pack-settle-s 20] \\
      [--expect-worker-count N] \\
      [--skip-scale-down-observe] \\
      [--scale-down-timeout-s 2400] \\
      [--scale-down-stable-polls 3] \\
      [--timeout 2400]
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib import oc as oc_lib
from scripts.lib import overprovision_peak, overprovision_sizing
from scripts.lib.bench import (
    REPO_ROOT,
    BenchmarkResult,
    checkpoint_complete,
    checkpoint_start,
    elapsed_human,
    fatal,
    handle_sigint,
    now_ms,
    resolve_kubeconfig,
    resolve_run_id_from_cluster_json,
    standard_args,
    verify_oc_login,
)

TEST_ID = "09b-karpenter-overprovisioning"
NAMESPACE = "benchmark"
MACHINE_API_NS = "openshift-machine-api"
CPU_BURNER = "cpu-burner"
CAPACITY_FILLER = "capacity-filler"
OVERPROVISIONER = "cluster-overprovisioner"
LABEL_CPU_BURNER = "app=cpu-burner"
LABEL_OVERPROV = "app=cluster-overprovisioner"

HPA_CPU_BURNER = "cpu-burner-hpa"
CPU_BURNER_STRESS_CMD = ["/bin/bash", "-c", "yes > /dev/null"]
CPU_BURNER_IDLE_CMD = ["/bin/bash", "-c", "sleep infinity"]
CPU_BURNER_PATCH_INDEX = 0
PAUSE_REPLICAS = 4
PAUSE_CPU_PER_POD_CORES = 1.0
PAUSE_MEMORY_MIB_PER_POD = 2048
PREEMPT_REASONS = frozenset({"Preempted", "Evicted", "Preempting"})
IS_AUTONODE = True
# Must match manifests/workloads/capacity-filler-karpenter.yaml and
# overprovision_sizing defaults.
FILLER_CPU_REQUEST_MC = 400
FILLER_MEMORY_REQUEST_MIB = 400

_OVERPROVISIONING = REPO_ROOT / "manifests" / "overprovisioning"
_WORKLOADS = REPO_ROOT / "manifests" / "workloads"
_AUTOSCALING = REPO_ROOT / "manifests" / "autoscaling"

MANIFEST_PRIORITY_CLASS = _OVERPROVISIONING / "priority-class.yaml"
MANIFEST_PAUSE = _OVERPROVISIONING / "pause-deployment-karpenter.yaml"
MANIFEST_CPU_BURNER = _WORKLOADS / "cpu-burner-karpenter.yaml"
MANIFEST_HPA = _AUTOSCALING / "hpa.yaml"
MANIFEST_FILLER = _WORKLOADS / "capacity-filler-karpenter.yaml"
MANIFEST_BOOTSTRAP = _WORKLOADS / "karpenter-bench-bootstrap.yaml"
BOOTSTRAP_NS = "autonode-bootstrap"
BOOTSTRAP_DEP = "pool-warm"


def _apply_bootstrap_manifest_for_nodepool(np_name: str, kubeconfig: str | None) -> None:
    """Render bootstrap manifest with the requested NodePool affinity value and apply."""
    if not MANIFEST_BOOTSTRAP.is_file():
        msg = f"Bootstrap manifest missing: {MANIFEST_BOOTSTRAP}"
        raise FileNotFoundError(msg)
    text = MANIFEST_BOOTSTRAP.read_text(encoding="utf-8").replace("autonode-bench", np_name)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yaml",
        delete=False,
        encoding="utf-8",
    ) as tmp_f:
        tmp_f.write(text)
        tmp_path = tmp_f.name
    try:
        oc_lib.apply_manifest(tmp_path, kubeconfig=kubeconfig)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def cleanup(kubeconfig: str | None) -> None:
    """Remove overprovisioner and capacity-filler; scale cpu-burner to 1."""
    try:
        oc_lib.patch_deployment_container_command(
            CPU_BURNER,
            NAMESPACE,
            CPU_BURNER_PATCH_INDEX,
            CPU_BURNER_STRESS_CMD,
            kubeconfig=kubeconfig,
        )
        oc_lib.wait_deployment_rollout(
            CPU_BURNER,
            NAMESPACE,
            timeout_s=180,
            kubeconfig=kubeconfig,
        )
    except Exception as exc:
        print(f"[cleanup] warning restoring cpu-burner command: {exc}", file=sys.stderr)
    try:
        oc_lib.run_oc(
            ["delete", "namespace", BOOTSTRAP_NS, "--ignore-not-found"],
            json_output=False,
            kubeconfig=kubeconfig,
            capture_stderr=False,
        )
    except Exception as exc:
        print(f"[cleanup] warning deleting {BOOTSTRAP_NS}: {exc}", file=sys.stderr)
    for action in [
        lambda: oc_lib.scale_deployment(CAPACITY_FILLER, 0, NAMESPACE, kubeconfig=kubeconfig),
        lambda: oc_lib.scale_deployment(CPU_BURNER, 1, NAMESPACE, kubeconfig=kubeconfig),
        lambda: oc_lib.delete_resource("deployment", OVERPROVISIONER, NAMESPACE, kubeconfig=kubeconfig),
        lambda: oc_lib.run_oc(
            ["delete", "priorityclass", "cluster-overprovisioner", "--ignore-not-found"],
            json_output=False,
            kubeconfig=kubeconfig,
        ),
    ]:
        try:
            action()
        except Exception as exc:
            print(f"[cleanup] warning: {exc}", file=sys.stderr)
    print("[cleanup] overprovisioner removed; cpu-burner at 1 replica.", file=sys.stderr)


def _pause_pods_evicted(kubeconfig: str | None) -> bool:
    """Return True if any overprovisioner pod is in Pending/Failed state (preempted)."""
    pods = oc_lib.get_pods(NAMESPACE, LABEL_OVERPROV, kubeconfig=kubeconfig)
    for pod in pods:
        phase = pod.get("status", {}).get("phase", "")
        if phase in ("Pending", "Failed"):
            return True
    return False


def _headroom_restored(kubeconfig: str | None, expected_count: int = 4) -> bool:
    """Return True when overprovisioner pods are all Running again (Karpenter provisioned)."""
    pods = oc_lib.get_pods(NAMESPACE, LABEL_OVERPROV, kubeconfig=kubeconfig)
    running = [p for p in pods if p.get("status", {}).get("phase") == "Running"]
    return len(running) >= expected_count


def _load_test08_baseline(run_id: str) -> dict[str, int]:
    """Read Test 08 (hcp-autonode) timings from events.jsonl for comparison."""
    if not run_id:
        return {}
    events_path = REPO_ROOT / "results" / run_id / "events.jsonl"
    if not events_path.exists():
        return {}
    baseline: dict[str, int] = {}
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            label = event.get("label", "")
            if label in {
                "08-hpa-triggers-cas.hpa_trigger_to_all_running",
                "08-hpa-triggers-cas.scheduler_triggered_to_node_ready",
            }:
                baseline[label] = event.get("elapsed_ms", 0)
    except (OSError, json.JSONDecodeError):
        pass
    return baseline


def _event_ts_ms(ev: dict[str, Any]) -> int | None:
    for field in ("lastTimestamp", "eventTime", "firstTimestamp"):
        raw = ev.get(field)
        if raw:
            try:
                parsed = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                return int(parsed.timestamp() * 1000)
            except (ValueError, AttributeError, OSError):
                pass
    return None


def _snapshot_fleet(
    label: str,
    *,
    machine_api_ns: str,
    kubeconfig: str | None,
    nodepool_name: str,
) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "label": label,
        "timestamp_ms": now_ms(),
        "node_names": sorted(oc_lib.get_node_names(kubeconfig=kubeconfig)),
        "node_count": oc_lib.get_node_count(kubeconfig=kubeconfig),
        "nodepool_name": nodepool_name,
        "nodeclaim_count": oc_lib.get_nodeclaim_count(
            nodepool_name=nodepool_name, kubeconfig=kubeconfig
        ),
    }
    _ = machine_api_ns  # unused for AutoNode; kept for signature parity with test 09 helper
    return snap


def _collect_burst_preemption_events(
    namespace: str,
    not_before_ms: int,
    kubeconfig: str | None,
) -> list[dict[str, Any]]:
    raw = oc_lib.get_events(namespace, kubeconfig=kubeconfig)
    out: list[dict[str, Any]] = []
    for ev in raw:
        if ev.get("reason") not in PREEMPT_REASONS:
            continue
        ts = _event_ts_ms(ev)
        if ts is not None and ts < not_before_ms:
            continue
        out.append(ev)
    return out


def _summarize_preemption_events(events: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return [
        {
            "reason": e.get("reason"),
            "object": e.get("involvedObject", {}).get("name", ""),
            "message": (e.get("message") or "")[:200],
        }
        for e in events[-limit:]
    ]


def _classify_burst_path(
    preempt_events: list[dict[str, Any]],
    nodes_at_trigger: int,
    nodes_after_running: int,
) -> tuple[str, str]:
    has_preemption = len(preempt_events) > 0
    new_nodes = nodes_after_running - nodes_at_trigger
    npe = len(preempt_events)
    if has_preemption and new_nodes == 0:
        return "preemption", f"{npe} preemption event(s), 0 new nodes"
    if not has_preemption and new_nodes > 0:
        return "slack", f"no preemption events, {new_nodes} new node(s)"
    if has_preemption and new_nodes > 0:
        return "mixed", f"{npe} preemption event(s), {new_nodes} new node(s)"
    return "slack", "no preemption events, no new nodes (existing slack)"


def _compute_restore_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    is_autonode: bool,
) -> dict[str, Any]:
    node_delta = int(after.get("node_count", 0)) - int(before.get("node_count", 0))
    if is_autonode:
        nc_delta = int(after.get("nodeclaim_count", 0)) - int(before.get("nodeclaim_count", 0))
        if nc_delta > 0:
            return {"type": f"nodeclaim+{nc_delta}", "count": nc_delta}
    else:
        ms_before = before.get("machineset_replicas") or {}
        ms_after = after.get("machineset_replicas") or {}
        names = set(ms_before.keys()) | set(ms_after.keys())
        ms_delta = 0
        for n in names:
            d_after = (ms_after.get(n) or {}).get("desired", 0)
            d_before = (ms_before.get(n) or {}).get("desired", 0)
            ms_delta += int(d_after) - int(d_before)
        if ms_delta > 0:
            return {"type": f"machineset+{ms_delta}", "count": ms_delta}
    if node_delta > 0:
        return {"type": f"node+{node_delta}", "count": node_delta}
    return {"type": "none", "count": 0}


def _hpa_cpu_burner_at_min(
    kubeconfig: str | None,
    *,
    max_replicas: int = 1,
) -> bool:
    cur, des = oc_lib.hpa_replica_counts(
        HPA_CPU_BURNER,
        NAMESPACE,
        kubeconfig=kubeconfig,
    )
    if cur is None or des is None:
        return False
    return cur <= max_replicas and des <= max_replicas


def _poll_fleet_size_stable(
    size_fn: Callable[[], int],
    *,
    stable_need: int,
    interval_s: int,
    timeout_s: int,
    label: str,
) -> tuple[int | None, bool]:
    """
    Poll ``size_fn`` until it returns the same value ``stable_need`` times in a row.

    Returns ``(last_value, True)`` on success, or ``(last_value, False)`` on timeout.
    OcError from ``size_fn`` is retried without aborting the streak reset (treated as attempt failure).
    """
    deadline = time.monotonic() + timeout_s
    last: int | None = None
    streak = 0
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            cur = size_fn()
        except oc_lib.OcError as exc:
            print(f"[scale-down] {label} — oc error (attempt {attempt}): {exc}", file=sys.stderr)
            cur = None
        if cur is None:
            time.sleep(interval_s)
            continue
        if cur == last:
            streak += 1
        else:
            last = cur
            streak = 1
        if streak >= stable_need:
            return last, True
        time.sleep(min(interval_s, max(0.0, deadline - time.monotonic())))
    return last, False


def _post_restore_observe_scale_down_09b(
    *,
    kubeconfig: str | None,
    nodepool_name: str,
    append_snapshot: Callable[[str], dict[str, Any]],
    result: BenchmarkResult,
    scale_down_timeout_s: int,
    stable_polls: int,
    skip: bool,
    dry_run: bool,
) -> None:
    """
    Idle cpu-burner so HPA can scale to minReplicas, then wait for fleet (NodeClaim) size to stabilize.
    Restores the stress command before returning so cleanup matches manifest expectations.
    """
    if skip or dry_run:
        return

    hpa_phase_s = max(60, scale_down_timeout_s // 2)
    fleet_phase_s = max(60, scale_down_timeout_s - hpa_phase_s)

    snap_before = append_snapshot("before_hpa_scale_down_burn")
    fleet_before = int(snap_before.get("nodeclaim_count") or 0)

    t_idle_start = now_ms()
    print(
        "[09b] Idling cpu-burner (sleep) so HPA can scale down; then watching NodeClaims stabilize ...",
        file=sys.stderr,
    )
    try:
        oc_lib.patch_deployment_container_command(
            CPU_BURNER,
            NAMESPACE,
            CPU_BURNER_PATCH_INDEX,
            CPU_BURNER_IDLE_CMD,
            kubeconfig=kubeconfig,
        )
        oc_lib.wait_deployment_rollout(
            CPU_BURNER,
            NAMESPACE,
            timeout_s=300,
            kubeconfig=kubeconfig,
        )
    except oc_lib.OcError as exc:
        print(f"[09b] WARNING: could not idle cpu-burner: {exc}", file=sys.stderr)
        result.extra["scale_down"] = {
            "skipped": True,
            "reason": f"idle_patch_failed: {exc}",
            "fleet_metric": "nodeclaim_count",
            "nodepool_name": nodepool_name,
        }
        return

    hpa_ok = False
    try:
        oc_lib.poll_until(
            lambda: _hpa_cpu_burner_at_min(kubeconfig),
            timeout_s=hpa_phase_s,
            interval_s=15,
            label="HPA at minReplicas (cpu-burner)",
        )
        hpa_ok = True
    except oc_lib.PollTimeout:
        print(
            f"[09b] WARNING: HPA did not reach min replicas within {hpa_phase_s}s "
            "(scaleDown stabilization is 300s). Skipping fleet stabilization.",
            file=sys.stderr,
        )

    t_hpa_min = now_ms()
    if hpa_ok:
        result.milestone(
            "idle_cpu_burner_to_hpa_min_replicas",
            t_idle_start,
            t_hpa_min,
            meta={"hpa": HPA_CPU_BURNER},
        )

    fleet_ok = False
    fleet_after_size: int | None = None
    if hpa_ok:

        def _nodeclaim_count() -> int:
            return oc_lib.get_nodeclaim_count(
                nodepool_name=nodepool_name,
                kubeconfig=kubeconfig,
            )

        fleet_after_size, fleet_ok = _poll_fleet_size_stable(
            _nodeclaim_count,
            stable_need=stable_polls,
            interval_s=30,
            timeout_s=fleet_phase_s,
            label="NodeClaim count stable",
        )
        if not fleet_ok:
            print(
                f"[09b] WARNING: NodeClaim count not stable within {fleet_phase_s}s.",
                file=sys.stderr,
            )

    t_fleet_done = now_ms()
    if hpa_ok:
        result.milestone(
            "hpa_min_replicas_to_fleet_stable",
            t_hpa_min,
            t_fleet_done,
            meta={
                "fleet_ok": str(fleet_ok),
                "stable_polls": str(stable_polls),
            },
        )

    snap_after = append_snapshot("after_fleet_scale_down")

    try:
        oc_lib.patch_deployment_container_command(
            CPU_BURNER,
            NAMESPACE,
            CPU_BURNER_PATCH_INDEX,
            CPU_BURNER_STRESS_CMD,
            kubeconfig=kubeconfig,
        )
        oc_lib.wait_deployment_rollout(
            CPU_BURNER,
            NAMESPACE,
            timeout_s=300,
            kubeconfig=kubeconfig,
        )
    except oc_lib.OcError as exc:
        print(f"[09b] WARNING: could not restore cpu-burner stress command: {exc}", file=sys.stderr)

    result.extra["scale_down"] = {
        "fleet_metric": "nodeclaim_count",
        "nodepool_name": nodepool_name,
        "nodeclaim_count_before_idle": fleet_before,
        "nodeclaim_count_after_stable_or_snapshot": fleet_after_size
        if fleet_after_size is not None
        else int(snap_after.get("nodeclaim_count") or 0),
        "hpa_at_min_replicas": hpa_ok,
        "fleet_size_stable": fleet_ok,
        "stable_polls_required": stable_polls,
        "timeout_budget_s": scale_down_timeout_s,
        "hpa_phase_timeout_s": hpa_phase_s,
        "fleet_phase_timeout_s": fleet_phase_s,
    }


def _measure_cpu_slack_kubeconfig(kubeconfig: str | None) -> tuple[float, int, int]:
    alloc_mc = oc_lib.get_cluster_cpu_allocatable_millicores(kubeconfig=kubeconfig)
    req_mc = oc_lib.get_cluster_cpu_requests_all_namespaces(kubeconfig=kubeconfig)
    slack_cores = (alloc_mc - req_mc) / 1000.0
    return slack_cores, alloc_mc, req_mc


def _apply_preflight_to_extra(
    result: BenchmarkResult,
    *,
    pause_requested_cores: float,
    slack_cores: float,
    alloc_mc: int,
    req_mc: int,
    cpu_slack_scope: str | None = None,
) -> None:
    result.extra["preflight"] = {
        "slack_cpu_cores": round(slack_cores, 2),
        "pause_requested_cpu_cores": pause_requested_cores,
        "verdict": "saturated" if slack_cores < pause_requested_cores else "has_slack",
        "allocatable_cpu_millicores": alloc_mc,
        "requested_cpu_millicores": req_mc,
    }
    if cpu_slack_scope:
        result.extra["preflight"]["cpu_slack_scope"] = cpu_slack_scope


def main() -> None:
    parser = standard_args("Test 09b — Overprovisioning with pause pods on HCP AutoNode.")
    parser.add_argument(
        "--cpu-burner-replicas",
        type=int,
        default=3,
        help="Number of cpu-burner replicas to request (default: 3).",
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help="Karpenter NodePool name (must match nodeAffinity in manifests).",
    )
    parser.add_argument(
        "--saturated-pool-baseline",
        action="store_true",
        help=(
            "Wait for N Ready nodes on this NodePool, apply pause+filler+cpu-burner+HPA together, "
            "then HPA burst (see --baseline-pool-ready-count, --capacity-filler-replicas)."
        ),
    )
    parser.add_argument(
        "--baseline-pool-ready-count",
        type=int,
        default=3,
        help="With --saturated-pool-baseline: min Ready nodes with karpenter.sh/nodepool=<name> (default: 3).",
    )
    parser.add_argument(
        "--baseline-pool-wait-timeout-s",
        type=int,
        default=2400,
        help="Timeout for --baseline-pool-ready-count (default: 2400).",
    )
    parser.add_argument(
        "--capacity-filler-replicas",
        type=int,
        default=None,
        help="Scale capacity-filler after apply; omit with --saturated-pool-baseline to compute from live pool metrics (benchmark NS excluded).",
    )
    parser.add_argument(
        "--require-saturated-before-balloons",
        action="store_true",
        help=(
            "Fail when CPU slack ≥ --max-slack-cpu-cores before pause pods (legacy) "
            "or after the bundle (with --saturated-pool-baseline).",
        ),
    )
    parser.add_argument(
        "--max-slack-cpu-cores",
        type=float,
        default=2.0,
        help="Slack threshold (cores) for --require-saturated-before-balloons (default: 2).",
    )
    parser.add_argument(
        "--karpenter-pack-max-rounds",
        type=int,
        default=15,
        help=(
            "After the saturated bundle is up, repeatedly add capacity-filler replicas until "
            "pool CPU slack falls below --max-slack-cpu-cores (Karpenter may grow the pool "
            "after the first sizing snapshot). Default: 15."
        ),
    )
    parser.add_argument(
        "--karpenter-pack-settle-s",
        type=int,
        default=20,
        help="Seconds to sleep before each post-bundle slack sample (default: 20).",
    )
    parser.add_argument(
        "--skip-scale-down-observe",
        action="store_true",
        help=(
            "After headroom restore: do not idle cpu-burner for HPA scale-down or wait for fleet size "
            "to stabilize (Karpenter/CAS consolidation)."
        ),
    )
    parser.add_argument(
        "--scale-down-timeout-s",
        type=int,
        default=2400,
        help=(
            "Max seconds for HPA desired→min and fleet stabilization after idling cpu-burner "
            "(default: 2400). Uses ~half each phase internally."
        ),
    )
    parser.add_argument(
        "--scale-down-stable-polls",
        type=int,
        default=3,
        help="Consecutive identical fleet-size polls required for stabilization (default: 3).",
    )
    parser.add_argument(
        "--expect-worker-count",
        type=int,
        default=None,
        help="If set, fail preflight when Ready node count does not match.",
    )
    parser.add_argument(
        "--sustained-peak-duration-s",
        type=int,
        default=1200,
        help=(
            "After burst cpu-burner pods are Ready: keep load at the HPA target this many seconds while "
            "polling nodes/pods/HPA (default: 1200 = 20m). Use 0 to skip."
        ),
    )
    parser.add_argument(
        "--sustained-peak-poll-interval-s",
        type=int,
        default=60,
        help="Seconds between polls during sustained peak (default: 60).",
    )
    args = parser.parse_args()
    if not (args.run_id or "").strip():
        resolved = resolve_run_id_from_cluster_json(args.cluster_type, args.cluster_name)
        if resolved:
            args.run_id = resolved
            print(
                f"[09b] Using run-id from tmp/cluster.{args.cluster_type}.json: {resolved}",
                file=sys.stderr,
            )
    if args.sustained_peak_duration_s > 0:
        min_recommended = args.sustained_peak_duration_s + 2400
        if args.timeout < min_recommended:
            print(
                f"[09b] WARNING: --timeout {args.timeout}s may be too low for sustained peak "
                f"({args.sustained_peak_duration_s}s) plus headroom restore and optional observe. "
                f"Consider --timeout {min_recommended} or higher.",
                file=sys.stderr,
            )
    kubeconfig = resolve_kubeconfig(args)
    target_replicas: int = args.cpu_burner_replicas
    nodepool_name: str = args.nodepool_name

    filler_replicas_effective: int | None = args.capacity_filler_replicas

    baseline_sel_key = "karpenter.sh/nodepool"
    baseline_sel_val = nodepool_name

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["nodepool_name"] = nodepool_name
    result.extra["test08_baseline_ms"] = _load_test08_baseline(args.run_id)
    result.extra["fleet_snapshots"] = []

    handle_sigint(lambda: cleanup(kubeconfig), run_id=args.run_id, test_id=TEST_ID, result=result)

    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    snapshots: list[dict[str, Any]] = result.extra["fleet_snapshots"]

    def append_snapshot(label: str) -> dict[str, Any]:
        snap = _snapshot_fleet(
            label,
            machine_api_ns=MACHINE_API_NS,
            kubeconfig=kubeconfig,
            nodepool_name=nodepool_name,
        )
        snapshots.append(snap)
        return snap

    pause_requested_cores = PAUSE_REPLICAS * PAUSE_CPU_PER_POD_CORES

    if args.saturated_pool_baseline:
        result.extra["topology_mode"] = "saturated_pool_baseline"
        result.extra["baseline_pool_selector"] = f"{baseline_sel_key}={baseline_sel_val}"

        print(
            f"[09b] Waiting for >= {args.baseline_pool_ready_count} Ready node(s) "
            f"with {baseline_sel_key}={baseline_sel_val!r}. "
            "An empty pool is warmed with a transient workload first.",
            file=sys.stderr,
        )

        def _pool_ready_now() -> int:
            return oc_lib.get_ready_node_count_for_label(
                baseline_sel_key,
                baseline_sel_val,
                kubeconfig=kubeconfig,
            )

        def _pool_big_enough() -> bool:
            return _pool_ready_now() >= args.baseline_pool_ready_count

        bootstrap_used = False
        if not args.dry_run and _pool_ready_now() < args.baseline_pool_ready_count:
            print(
                "[09b] NodePool has fewer Ready nodes than baseline; "
                "applying transient autonode-bootstrap / pool-warm ...",
                file=sys.stderr,
            )
            try:
                _apply_bootstrap_manifest_for_nodepool(nodepool_name, kubeconfig)
            except FileNotFoundError as exc:
                fatal(
                    str(exc),
                    run_id=args.run_id,
                    test_id=TEST_ID,
                    result=result,
                )
            oc_lib.scale_deployment(
                BOOTSTRAP_DEP,
                args.baseline_pool_ready_count,
                BOOTSTRAP_NS,
                kubeconfig=kubeconfig,
            )
            oc_lib.wait_for_deployment_ready(
                BOOTSTRAP_DEP,
                BOOTSTRAP_NS,
                timeout_s=900,
                kubeconfig=kubeconfig,
            )
            bootstrap_used = True
            result.extra["pool_bootstrap"] = {
                "used": True,
                "replicas": args.baseline_pool_ready_count,
            }

        try:
            if not args.dry_run:
                oc_lib.poll_until(
                    _pool_big_enough,
                    timeout_s=args.baseline_pool_wait_timeout_s,
                    interval_s=20,
                    label=f">= {args.baseline_pool_ready_count} ready NodePool nodes",
                )
        except oc_lib.PollTimeout:
            fatal(
                f"Timed out waiting for {args.baseline_pool_ready_count} Ready node(s) "
                f"with {baseline_sel_key}={baseline_sel_val}. "
                "Check Karpenter / NodePool / EC2NodeClass; increase --baseline-pool-wait-timeout-s.",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )

        if bootstrap_used and not args.dry_run:
            print(
                "[09b] Scaling pool-warm to 0 so sizing ignores bootstrap requests ...",
                file=sys.stderr,
            )
            oc_lib.scale_deployment(
                BOOTSTRAP_DEP,
                0,
                BOOTSTRAP_NS,
                kubeconfig=kubeconfig,
            )
            oc_lib.wait_for_deployment_ready(
                BOOTSTRAP_DEP,
                BOOTSTRAP_NS,
                timeout_s=600,
                kubeconfig=kubeconfig,
            )
            time.sleep(15)

        if not bootstrap_used:
            result.extra.setdefault("pool_bootstrap", {"used": False})

        if args.expect_worker_count is not None:
            n_all = oc_lib.get_node_count(kubeconfig=kubeconfig)
            result.extra.setdefault("preflight", {})
            result.extra["preflight"]["expect_worker_count"] = args.expect_worker_count
            result.extra["preflight"]["observed_ready_node_count"] = n_all
            if n_all != args.expect_worker_count:
                fatal(
                    f"Preflight: expected {args.expect_worker_count} Ready nodes (all roles), found {n_all}.",
                    run_id=args.run_id,
                    test_id=TEST_ID,
                    result=result,
                )

        if args.saturated_pool_baseline and filler_replicas_effective is None:
            if args.dry_run:
                filler_replicas_effective = 5
                print(
                    f"[09b] dry-run: placeholder capacity-filler replicas={filler_replicas_effective} "
                    "(live pool sizing skipped)",
                    file=sys.stderr,
                )
            else:
                try:
                    filler_replicas_effective, sizing_meta = (
                        overprovision_sizing.compute_saturated_capacity_filler_replicas(
                            baseline_sel_key,
                            baseline_sel_val,
                            kubeconfig=kubeconfig,
                            max_slack_cpu_cores=args.max_slack_cpu_cores,
                            pause_replicas=PAUSE_REPLICAS,
                            pause_cpu_millicores=int(PAUSE_CPU_PER_POD_CORES * 1000),
                            pause_memory_mib=PAUSE_MEMORY_MIB_PER_POD,
                        )
                    )
                except ValueError as exc:
                    fatal(
                        str(exc),
                        run_id=args.run_id,
                        test_id=TEST_ID,
                        result=result,
                    )
                result.extra["capacity_filler_sizing"] = sizing_meta
                print(
                    f"[09b] Computed capacity-filler replicas={filler_replicas_effective} "
                    f"projected slack ≈{sizing_meta['projected_cpu_slack_cores_after_scale']} cores.",
                    file=sys.stderr,
                )

        snap_t0 = append_snapshot("t0_baseline")

        print(
            "[09b] Applying PriorityClass, pause-karpenter, capacity-filler, cpu-burner, HPA (bundled baseline) ...",
            file=sys.stderr,
        )
        if not args.dry_run:
            oc_lib.ensure_namespace(NAMESPACE)
            oc_lib.apply_manifest(str(MANIFEST_PRIORITY_CLASS), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(MANIFEST_PAUSE), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(MANIFEST_FILLER), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(MANIFEST_CPU_BURNER), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(MANIFEST_HPA), kubeconfig=kubeconfig)

        if filler_replicas_effective is not None:
            print(
                f"[09b] Scaling capacity-filler to {filler_replicas_effective} replicas ...",
                file=sys.stderr,
            )
            if not args.dry_run:
                oc_lib.scale_deployment(
                    CAPACITY_FILLER,
                    filler_replicas_effective,
                    NAMESPACE,
                    kubeconfig=kubeconfig,
                )

        if not args.dry_run:
            oc_lib.wait_for_deployment_ready(
                CAPACITY_FILLER, NAMESPACE, timeout_s=600, kubeconfig=kubeconfig
            )
            oc_lib.wait_for_deployment_ready(CPU_BURNER, NAMESPACE, timeout_s=180, kubeconfig=kubeconfig)
        print("[09b] capacity-filler and cpu-burner Ready (bundled).", file=sys.stderr)

        print("[09b] Waiting for overprovisioner pause pods to be Running ...", file=sys.stderr)
        t_start = now_ms()
        try:
            if not args.dry_run:
                oc_lib.wait_for_all_pods_running(
                    NAMESPACE,
                    LABEL_OVERPROV,
                    expected_count=PAUSE_REPLICAS,
                    timeout_s=900,
                    interval_s=20,
                    kubeconfig=kubeconfig,
                )

            pack_rounds: list[dict[str, Any]] = []
            result.extra["capacity_filler_pack_rounds"] = pack_rounds
            pack_exhausted = False

            if not args.dry_run and filler_replicas_effective is not None:
                for pack_round in range(args.karpenter_pack_max_rounds):
                    time.sleep(max(0, args.karpenter_pack_settle_s))
                    try:
                        (
                            slack_cores_m,
                            slack_mib,
                            _alloc_mc_m,
                            _alloc_mi_m,
                            _req_mc_m,
                            _req_mi_m,
                            _rn,
                        ) = oc_lib.measure_cpu_memory_slack_for_node_label(
                            baseline_sel_key,
                            baseline_sel_val,
                            kubeconfig=kubeconfig,
                        )
                    except oc_lib.OcError as exc:
                        fatal(
                            f"Post-bundle pack: could not read allocatable/requests: {exc}",
                            run_id=args.run_id,
                            test_id=TEST_ID,
                            result=result,
                        )

                    if slack_cores_m < args.max_slack_cpu_cores:
                        if pack_round > 0:
                            print(
                                f"[09b] Karpenter pack: CPU slack {slack_cores_m:.2f} cores "
                                f"≤ threshold {args.max_slack_cpu_cores} after {pack_round} extra round(s).",
                                file=sys.stderr,
                            )
                        break

                    delta_cores = slack_cores_m - args.max_slack_cpu_cores
                    delta_mc = max(0.0, delta_cores * 1000.0)
                    add_cpu = max(1, math.ceil(delta_mc / FILLER_CPU_REQUEST_MC))
                    add_mem = max(0, int(slack_mib)) // FILLER_MEMORY_REQUEST_MIB
                    add = min(add_cpu, add_mem)
                    if add <= 0:
                        fatal(
                            f"[09b] Karpenter pack: CPU slack {slack_cores_m:.2f} cores exceeds "
                            f"{args.max_slack_cpu_cores}, but memory slack is only {slack_mib:.0f} MiB "
                            f"(cannot add {FILLER_MEMORY_REQUEST_MIB} MiB filler pods).",
                            run_id=args.run_id,
                            test_id=TEST_ID,
                            result=result,
                        )

                    prev = filler_replicas_effective
                    filler_replicas_effective = prev + add
                    print(
                        f"[09b] Karpenter pack round {pack_round + 1}: slack {slack_cores_m:.2f} cores → "
                        f"scaling capacity-filler {prev} → {filler_replicas_effective} (+{add}).",
                        file=sys.stderr,
                    )
                    pack_rounds.append(
                        {
                            "round": pack_round + 1,
                            "slack_cpu_cores_before": round(slack_cores_m, 3),
                            "slack_memory_mib_before": round(slack_mib, 1),
                            "replicas_added": add,
                            "filler_replicas_after": filler_replicas_effective,
                        }
                    )
                    oc_lib.scale_deployment(
                        CAPACITY_FILLER,
                        filler_replicas_effective,
                        NAMESPACE,
                        kubeconfig=kubeconfig,
                    )
                    oc_lib.wait_for_deployment_ready(
                        CAPACITY_FILLER, NAMESPACE, timeout_s=600, kubeconfig=kubeconfig
                    )
                    oc_lib.wait_for_all_pods_running(
                        NAMESPACE,
                        LABEL_OVERPROV,
                        expected_count=PAUSE_REPLICAS,
                        timeout_s=900,
                        interval_s=20,
                        kubeconfig=kubeconfig,
                    )
                else:
                    pack_exhausted = True
                if isinstance(result.extra.get("capacity_filler_sizing"), dict):
                    result.extra["capacity_filler_sizing"]["replicas_after_pack"] = (
                        filler_replicas_effective
                    )

            t_headroom_ready = now_ms()
            snap_after_headroom = append_snapshot("after_headroom")
            new_for_balloons = set(snap_after_headroom["node_names"]) - set(snap_t0["node_names"])
            try:
                slack_cores, alloc_mc, req_mc = oc_lib.measure_cpu_slack_for_node_label(
                    baseline_sel_key,
                    baseline_sel_val,
                    kubeconfig=kubeconfig,
                )
            except oc_lib.OcError as exc:
                fatal(
                    f"Post-bundle preflight could not read allocatable/requests: {exc}",
                    run_id=args.run_id,
                    test_id=TEST_ID,
                    result=result,
                )
            if pack_exhausted and slack_cores >= args.max_slack_cpu_cores:
                fatal(
                    f"Post-bundle: Karpenter pack did not drive CPU slack below "
                    f"{args.max_slack_cpu_cores} after {args.karpenter_pack_max_rounds} round(s) "
                    f"(still {slack_cores:.2f} cores on {baseline_sel_key}={baseline_sel_val}). "
                    "Raise --karpenter-pack-max-rounds or --capacity-filler-replicas.",
                    run_id=args.run_id,
                    test_id=TEST_ID,
                    result=result,
                )
            _apply_preflight_to_extra(
                result,
                pause_requested_cores=pause_requested_cores,
                slack_cores=slack_cores,
                alloc_mc=alloc_mc,
                req_mc=req_mc,
                cpu_slack_scope=f"nodes[{baseline_sel_key}={baseline_sel_val}]",
            )
            result.extra["preflight"]["new_nodes_for_balloons"] = len(new_for_balloons)
            result.extra["preflight"]["topology_mode"] = "saturated_pool_baseline"
            result.extra["preflight"]["filler_replicas_effective"] = filler_replicas_effective

            if args.require_saturated_before_balloons and slack_cores >= args.max_slack_cpu_cores:
                fatal(
                    f"Post-bundle: CPU slack on pool nodes ({baseline_sel_key}={baseline_sel_val}) "
                    f"is {slack_cores:.2f} cores (threshold {args.max_slack_cpu_cores}). "
                    "Raise --capacity-filler-replicas.",
                    run_id=args.run_id,
                    test_id=TEST_ID,
                    result=result,
                )
            elif slack_cores >= pause_requested_cores:
                print(
                    "[09b] WARN: post-bundle slack ≥ pause-pod CPU requests.",
                    file=sys.stderr,
                )

            result.milestone(
                "start_to_headroom_ready",
                t_start,
                t_headroom_ready,
                meta={
                    "new_nodes": str(len(new_for_balloons)),
                    "topology": "saturated_pool_baseline",
                    "scheduler": "karpenter",
                },
            )
            print(
                f"[09b] Pause pods Running ({elapsed_human(t_start, t_headroom_ready)}); "
                f"+{len(new_for_balloons)} new node name(s) vs t0; "
                f"pool slack={slack_cores:.2f} cores ({baseline_sel_key}={baseline_sel_val}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            fatal(
                "Pause pods did not reach Running within 15m.",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )

    else:
        result.extra["topology_mode"] = "pause_first_then_filler"
        try:
            slack_cores, alloc_mc, req_mc = _measure_cpu_slack_kubeconfig(kubeconfig)
        except oc_lib.OcError as exc:
            fatal(
                f"Preflight could not read cluster CPU allocatable/requests: {exc}",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )

        _apply_preflight_to_extra(
            result,
            pause_requested_cores=pause_requested_cores,
            slack_cores=slack_cores,
            alloc_mc=alloc_mc,
            req_mc=req_mc,
            cpu_slack_scope="cluster",
        )

        if args.expect_worker_count is not None:
            n_ready = oc_lib.get_node_count(kubeconfig=kubeconfig)
            result.extra["preflight"]["expect_worker_count"] = args.expect_worker_count
            result.extra["preflight"]["observed_ready_node_count"] = n_ready
            if n_ready != args.expect_worker_count:
                fatal(
                    f"Preflight: expected {args.expect_worker_count} Ready nodes, found {n_ready}.",
                    run_id=args.run_id,
                    test_id=TEST_ID,
                    result=result,
                )

        if args.require_saturated_before_balloons and slack_cores >= args.max_slack_cpu_cores:
            fatal(
                f"Preflight: allocatable CPU slack is {slack_cores:.2f} cores "
                f"(threshold {args.max_slack_cpu_cores}). "
                "Try --saturated-pool-baseline or raise --max-slack-cpu-cores.",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )
        elif slack_cores >= pause_requested_cores:
            print(
                "[09b] WARN: cluster slack ≥ pause-pod CPU requests; "
                "balloons may schedule without forcing new nodes.",
                file=sys.stderr,
            )

        snap_t0 = append_snapshot("t0_baseline")

        print("[09b] Applying PriorityClass and pause-deployment-karpenter.yaml ...", file=sys.stderr)
        if not args.dry_run:
            oc_lib.apply_manifest(str(MANIFEST_PRIORITY_CLASS), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(MANIFEST_PAUSE), kubeconfig=kubeconfig)

        print(
            "[09b] Waiting for overprovisioner pause pods to be Running "
            "(Karpenter will provision headroom nodes — expected ~4–5 min) ...",
            file=sys.stderr,
        )
        t_start = now_ms()
        try:
            if not args.dry_run:
                oc_lib.wait_for_all_pods_running(
                    NAMESPACE,
                    LABEL_OVERPROV,
                    expected_count=PAUSE_REPLICAS,
                    timeout_s=900,
                    interval_s=20,
                    kubeconfig=kubeconfig,
                )
            t_headroom_ready = now_ms()
            snap_after_headroom = append_snapshot("after_headroom")
            new_for_balloons = set(snap_after_headroom["node_names"]) - set(snap_t0["node_names"])
            result.extra["preflight"]["new_nodes_for_balloons"] = len(new_for_balloons)
            result.milestone(
                "start_to_headroom_ready",
                t_start,
                t_headroom_ready,
                meta={"new_nodes": str(len(new_for_balloons)), "scheduler": "karpenter"},
            )
            print(
                f"[09b] Pause pods Running — headroom reserved "
                f"({elapsed_human(t_start, t_headroom_ready)}); "
                f"+{len(new_for_balloons)} new node name(s) vs t0.",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            fatal(
                "Pause pods did not reach Running within 15m. "
                "Check that Karpenter is enabled, ec2nodeclass/default is Ready, "
                "and the nodepool-name matches the nodeAffinity in pause-deployment-karpenter.yaml.",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )

        print(
            "[09b] Applying capacity-filler-karpenter.yaml, cpu-burner-karpenter.yaml, HPA ...",
            file=sys.stderr,
        )
        if not args.dry_run:
            oc_lib.apply_manifest(str(MANIFEST_FILLER), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(MANIFEST_CPU_BURNER), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(MANIFEST_HPA), kubeconfig=kubeconfig)
            if filler_replicas_effective is not None:
                oc_lib.scale_deployment(
                    CAPACITY_FILLER,
                    filler_replicas_effective,
                    NAMESPACE,
                    kubeconfig=kubeconfig,
                )
            oc_lib.wait_for_deployment_ready(CAPACITY_FILLER, NAMESPACE, timeout_s=300, kubeconfig=kubeconfig)
            oc_lib.wait_for_deployment_ready(CPU_BURNER, NAMESPACE, timeout_s=180, kubeconfig=kubeconfig)
        print("[09b] capacity-filler and cpu-burner Ready.", file=sys.stderr)

    print(f"[09b] Scaling cpu-burner to {target_replicas} replicas ...", file=sys.stderr)
    t_hpa_trigger = now_ms()
    if not args.dry_run:
        oc_lib.scale_deployment(CPU_BURNER, target_replicas, NAMESPACE, kubeconfig=kubeconfig)
    snap_hpa = append_snapshot("at_hpa_trigger")

    print("[09b] Watching for pause pod eviction (preemption — should be seconds) ...", file=sys.stderr)
    t_preempted = t_hpa_trigger
    try:
        oc_lib.poll_until(
            lambda: _pause_pods_evicted(kubeconfig),
            timeout_s=120,
            interval_s=5,
            label="pause pod preemption",
        )
        t_preempted = now_ms()
        result.milestone("hpa_trigger_to_preemption", t_hpa_trigger, t_preempted)
        result.milestone("hpa_trigger_to_first_pause_preempted", t_hpa_trigger, t_preempted)
        print(
            f"[09b] Pause pods preempted ({elapsed_human(t_hpa_trigger, t_preempted)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            "[09b] WARNING: Pause pods not evicted within 2m — cluster may have had spare capacity "
            "beyond the overprovisioner headroom.",
            file=sys.stderr,
        )
        t_preempted = now_ms()

    print(
        "[09b] Waiting for cpu-burner pods to be Running (should be fast via preemption) ...",
        file=sys.stderr,
    )
    t_pods_running = t_hpa_trigger
    snap_running: dict[str, Any] | None = None
    mechanism = "slack"
    evidence = "classification pending"
    try:
        running_pods = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            LABEL_CPU_BURNER,
            expected_count=target_replicas,
            timeout_s=300,
            interval_s=5,
            kubeconfig=kubeconfig,
        )
        t_pods_running = now_ms()
        snap_running = append_snapshot("after_workload_running")

        burst_ev = _collect_burst_preemption_events(NAMESPACE, t_hpa_trigger, kubeconfig)
        mechanism, evidence = _classify_burst_path(
            burst_ev,
            int(snap_hpa["node_count"]),
            int(snap_running["node_count"]),
        )
        result.extra["burst_absorption_mechanism"] = mechanism
        result.extra["burst_absorption_evidence"] = evidence
        result.extra["preemption_events"] = _summarize_preemption_events(burst_ev)

        result.milestone(
            "hpa_trigger_to_pods_running",
            t_hpa_trigger,
            t_pods_running,
            meta={
                "mechanism": mechanism,
                "pod_count": str(len(running_pods)),
                "scheduler": "karpenter",
            },
        )
        print(
            f"[09b] {len(running_pods)} cpu-burner pods Running — {mechanism} "
            f"({elapsed_human(t_hpa_trigger, t_pods_running)}): {evidence}.",
            file=sys.stderr,
        )
        result.extra["hpa_to_running_ms"] = t_pods_running - t_hpa_trigger

        print("[09b] Waiting for cpu-burner pods to be Ready ...", file=sys.stderr)
        try:
            ready_pods = oc_lib.wait_for_all_pods_ready(
                NAMESPACE,
                LABEL_CPU_BURNER,
                expected_count=target_replicas,
                timeout_s=300,
                interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_pods_ready = now_ms()
            result.milestone(
                "pods_running_to_pods_ready",
                t_pods_running,
                t_pods_ready,
                meta={"ready_pod_count": str(len(ready_pods))},
            )
            result.milestone(
                "hpa_trigger_to_pods_ready",
                t_hpa_trigger,
                t_pods_ready,
                meta={
                    "mechanism": mechanism,
                    "scheduler": "karpenter",
                    "pod_count": str(len(ready_pods)),
                },
            )
            print(
                f"[09b] {len(ready_pods)} pods Ready "
                f"(+{elapsed_human(t_pods_running, t_pods_ready)} after Running; "
                f"hpa→ready: {elapsed_human(t_hpa_trigger, t_pods_ready)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[09b] WARNING: pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        t_pods_running = now_ms()
        print(
            "[09b] WARNING: cpu-burner pods did not reach Running within 5m via preemption.",
            file=sys.stderr,
        )
        try:
            burst_ev = _collect_burst_preemption_events(NAMESPACE, t_hpa_trigger, kubeconfig)
            mechanism, evidence = _classify_burst_path(
                burst_ev,
                int(snap_hpa["node_count"]),
                int(snap_hpa["node_count"]),
            )
            result.extra["burst_absorption_mechanism"] = mechanism
            result.extra["burst_absorption_evidence"] = evidence
            result.extra["preemption_events"] = _summarize_preemption_events(burst_ev)
        except oc_lib.OcError:
            result.extra["burst_absorption_mechanism"] = "slack"
            result.extra["burst_absorption_evidence"] = "pods did not reach Running; partial data"

    if "burst_absorption_mechanism" not in result.extra:
        result.extra["burst_absorption_mechanism"] = mechanism
        result.extra["burst_absorption_evidence"] = evidence

    if snap_running is not None and args.sustained_peak_duration_s > 0 and not args.dry_run:
        overprovision_peak.run_sustained_peak_observation(
            duration_s=args.sustained_peak_duration_s,
            poll_interval_s=args.sustained_peak_poll_interval_s,
            kubeconfig=kubeconfig,
            namespace=NAMESPACE,
            label_overprov=LABEL_OVERPROV,
            label_cpu_burner=LABEL_CPU_BURNER,
            hpa_name=HPA_CPU_BURNER,
            baseline_sel_key=baseline_sel_key,
            baseline_sel_val=baseline_sel_val,
            is_autonode=IS_AUTONODE,
            nodepool_name=nodepool_name,
            machine_api_ns=MACHINE_API_NS,
            result=result,
            log_prefix="[09b]",
        )
    elif args.dry_run and args.sustained_peak_duration_s > 0 and snap_running is not None:
        print(
            f"[09b] dry-run: would poll cluster every {args.sustained_peak_poll_interval_s}s for "
            f"{args.sustained_peak_duration_s}s during sustained peak.",
            file=sys.stderr,
        )

    print(
        "[09b] Waiting for Karpenter to provision new capacity and restore pause pods "
        "(expected ~4–5 min) ...",
        file=sys.stderr,
    )
    try:
        oc_lib.poll_until(
            lambda: _headroom_restored(kubeconfig),
            timeout_s=args.timeout,
            interval_s=30,
            label="headroom restored",
        )
        t_headroom_restored = now_ms()
        snap_restore = append_snapshot("after_restore")
        result.milestone(
            "pods_running_to_headroom_restored",
            t_pods_running,
            t_headroom_restored,
        )
        print(
            f"[09b] Headroom restored by Karpenter "
            f"({elapsed_human(t_pods_running, t_headroom_restored)} after pods were Running).",
            file=sys.stderr,
        )
        result.extra["headroom_restore_ms"] = t_headroom_restored - t_pods_running
        if snap_running is not None:
            result.extra["restore_fleet_delta"] = _compute_restore_delta(
                snap_running,
                snap_restore,
                is_autonode=IS_AUTONODE,
            )
    except oc_lib.PollTimeout:
        print(
            "[09b] WARNING: Headroom not restored within timeout. "
            "Karpenter may still be provisioning.",
            file=sys.stderr,
        )
        snap_restore = append_snapshot("after_restore_poll_timeout")
        if snap_running is not None:
            result.extra["restore_fleet_delta"] = _compute_restore_delta(
                snap_running,
                snap_restore,
                is_autonode=IS_AUTONODE,
            )

    _post_restore_observe_scale_down_09b(
        kubeconfig=kubeconfig,
        nodepool_name=nodepool_name,
        append_snapshot=append_snapshot,
        result=result,
        scale_down_timeout_s=args.scale_down_timeout_s,
        stable_polls=args.scale_down_stable_polls,
        skip=args.skip_scale_down_observe,
        dry_run=args.dry_run,
    )

    cleanup(kubeconfig)

    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
