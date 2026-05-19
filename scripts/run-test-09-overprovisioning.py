#!/usr/bin/env python3
"""
scripts/run-test-09-overprovisioning.py

Benchmark: Overprovisioning with pause pods (Test 09)

Demonstrates how low-priority placeholder pods pre-reserve cluster capacity so
HPA pods schedule immediately via preemption — without waiting for CAS to
provision new nodes. CAS then restores the headroom in the background.

Procedure (default): pause-first, then filler + steady workload — see SKILLS.

With **--saturated-pool-baseline**: wait for N benchmark workers, apply pause +
filler + cpu-burner + HPA together; **capacity-filler** replicas default to a
**live computed** value from pool CPU/memory (benchmark namespace excluded) so
`--max-slack-cpu-cores` is reachable. Override with **--capacity-filler-replicas**.
Then HPA burst and headroom restore.

**ROSA Classic:** unless ``--skip-classic-bench-machinepool-create`` is set, the
script creates the bench machine pool when missing, using the same labels as
``machine-pools/add-standard.sh`` (``benchmark=true,pool-type=standard``) so
manifests' ``pool-type: standard`` selectors match. OCM **HTTP 503** from
``rosa`` stops the run immediately (fix auth/API access; no in-script retry).

Usage:
  python3 scripts/run-test-09-overprovisioning.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--saturated-pool-baseline \\
        [--baseline-pool-ready-count 3] \\
        [--rosa-machinepool-min 3 --rosa-machinepool-max 12] \\
        [--capacity-filler-replicas <N>] \\
        [--require-saturated-before-balloons]] \\
      ...
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib import oc as oc_lib
from scripts.lib import overprovision_peak, overprovision_sizing
from scripts.lib.bench import (
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

TEST_ID = "09-overprovisioning"
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
PAUSE_MEMORY_MIB_PER_POD = 2048  # matches pause-deployment*.yaml requests
PREEMPT_REASONS = frozenset({"Preempted", "Evicted", "Preempting"})

MANIFEST_PRIORITY_CLASS = (
    Path(__file__).parent.parent / "manifests" / "overprovisioning" / "priority-class.yaml"
)
MANIFEST_PAUSE = (
    Path(__file__).parent.parent / "manifests" / "overprovisioning" / "pause-deployment.yaml"
)
MANIFEST_PAUSE_KARPENTER = (
    Path(__file__).parent.parent / "manifests" / "overprovisioning" / "pause-deployment-karpenter.yaml"
)
MANIFEST_CPU_BURNER = Path(__file__).parent.parent / "manifests" / "workloads" / "cpu-burner.yaml"
MANIFEST_CPU_BURNER_KARPENTER = (
    Path(__file__).parent.parent / "manifests" / "workloads" / "cpu-burner-karpenter.yaml"
)
MANIFEST_HPA = Path(__file__).parent.parent / "manifests" / "autoscaling" / "hpa.yaml"
MANIFEST_FILLER = Path(__file__).parent.parent / "manifests" / "workloads" / "capacity-filler.yaml"
MANIFEST_FILLER_KARPENTER = (
    Path(__file__).parent.parent / "manifests" / "workloads" / "capacity-filler-karpenter.yaml"
)

# Matches machine-pools/add-standard.sh — workload manifests use pool-type=standard.
CLASSIC_BENCH_MACHINEPOOL_LABELS = "benchmark=true,pool-type=standard"
CLASSIC_BENCH_INSTANCE_TYPE = "m5.xlarge"


class RosaOcm503(RuntimeError):
    """OCM returned HTTP 503 from `rosa`; fix auth or API access — do not retry in-script."""


def _raise_if_rosa_503(stdout: str, stderr: str) -> None:
    """If combined ROSA output indicates OCM HTTP 503, raise RosaOcm503 (no workaround)."""
    combined = f"{stderr or ''}\n{stdout or ''}"
    upper = combined.upper()
    if "503" not in upper:
        return
    if (
        "CLUSTERS-MGMT" in upper
        or "STATUS IS 503" in upper
        or "IDENTIFIER IS '503'" in upper
        or "SERVICE UNAVAILABLE" in upper
    ):
        raise RosaOcm503(
            "ROSA/OCM returned HTTP 503 (service unavailable). This benchmark does not retry that. "
            "Fix ROSA CLI authentication (`rosa login`, `rosa whoami`), refresh your OCM token if "
            "you use one, verify network access to api.openshift.com, then re-run."
        )


def _rosa_which() -> str:
    rosa = shutil.which("rosa")
    if not rosa:
        raise RuntimeError("rosa CLI not found on PATH")
    return rosa


def _rosa_list_machinepool_items(cluster_name: str) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [_rosa_which(), "list", "machinepools", "-c", cluster_name, "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        _raise_if_rosa_503(proc.stdout or "", proc.stderr or "")
        err = (proc.stderr or proc.stdout or "").strip()[:800]
        raise RuntimeError(f"rosa list machinepools failed (exit {proc.returncode}): {err}")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"rosa list machinepools: invalid JSON: {exc}") from exc
    if isinstance(data, list):
        return data
    items = data.get("items")
    if isinstance(items, list):
        return items
    return []


def _classic_machinepool_present(items: list[dict[str, Any]], pool_name: str) -> bool:
    return any(
        it.get("id") == pool_name or it.get("name") == pool_name for it in items
    )


def _rosa_describe_cluster_dict(cluster_name: str) -> dict[str, Any]:
    proc = subprocess.run(
        [_rosa_which(), "describe", "cluster", "-c", cluster_name, "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        _raise_if_rosa_503(proc.stdout or "", proc.stderr or "")
        err = (proc.stderr or proc.stdout or "").strip()[:800]
        raise RuntimeError(f"rosa describe cluster failed (exit {proc.returncode}): {err}")
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"rosa describe cluster: invalid JSON: {exc}") from exc


def _classic_adjust_autoscale_replicas_for_multi_az(
    min_r: int, max_r: int, *, multi_az: bool
) -> tuple[int, int]:
    if not multi_az:
        return min_r, max(max_r, min_r)
    min_r = max(min_r, 3)
    max_r = (max_r // 3) * 3
    if max_r < min_r:
        max_r = min_r
    return min_r, max_r


def _classic_create_min_max(
    *,
    saturated: bool,
    min_arg: int | None,
    max_arg: int | None,
    multi_az: bool,
) -> tuple[int, int]:
    if saturated:
        mn = min_arg if min_arg is not None else 3
        mx = max_arg if max_arg is not None else 12
    else:
        mn = min_arg if min_arg is not None else 1
        mx = max_arg if max_arg is not None else 10
    return _classic_adjust_autoscale_replicas_for_multi_az(mn, mx, multi_az=multi_az)


def _rosa_create_classic_bench_machinepool(
    *,
    cluster_name: str,
    pool_name: str,
    min_replicas: int,
    max_replicas: int,
    dry_run: bool,
) -> None:
    if dry_run:
        print(
            f"[09] dry-run: would `rosa create machinepool` name={pool_name!r} "
            f"instance-type={CLASSIC_BENCH_INSTANCE_TYPE!r} "
            f"labels={CLASSIC_BENCH_MACHINEPOOL_LABELS!r} {min_replicas}-{max_replicas}",
            file=sys.stderr,
        )
        return
    cmd = [
        _rosa_which(),
        "create",
        "machinepool",
        "-c",
        cluster_name,
        "--name",
        pool_name,
        "--instance-type",
        CLASSIC_BENCH_INSTANCE_TYPE,
        "--enable-autoscaling",
        f"--min-replicas={min_replicas}",
        f"--max-replicas={max_replicas}",
        "--labels",
        CLASSIC_BENCH_MACHINEPOOL_LABELS,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        _raise_if_rosa_503(proc.stdout or "", proc.stderr or "")
        err = (proc.stderr or proc.stdout or "").strip()[:800]
        raise RuntimeError(f"rosa create machinepool failed (exit {proc.returncode}): {err}")
    print(
        f"[09] Created machine pool {pool_name!r} (labels {CLASSIC_BENCH_MACHINEPOOL_LABELS}); "
        "nodes will reconcile asynchronously.",
        file=sys.stderr,
    )


def _ensure_classic_bench_machinepool_if_missing(
    *,
    cluster_name: str,
    pool_name: str,
    saturated: bool,
    min_replicas: int | None,
    max_replicas: int | None,
    dry_run: bool,
    skip_create: bool,
) -> None:
    """
    For ROSA Classic: ensure the benchmark machine pool exists with the same
    labels as ``machine-pools/add-standard.sh`` (``pool-type=standard`` for selectors).
    """
    if skip_create:
        return
    if dry_run:
        print(
            f"[09] dry-run: would ensure classic bench pool {pool_name!r} exists "
            f"({CLASSIC_BENCH_MACHINEPOOL_LABELS})",
            file=sys.stderr,
        )
        return
    items = _rosa_list_machinepool_items(cluster_name)
    if _classic_machinepool_present(items, pool_name):
        print(f"[09] Machine pool {pool_name!r} already exists.", file=sys.stderr)
        return
    cluster = _rosa_describe_cluster_dict(cluster_name)
    multi_az = bool(cluster.get("multi_az"))
    mn, mx = _classic_create_min_max(
        saturated=saturated,
        min_arg=min_replicas,
        max_arg=max_replicas,
        multi_az=multi_az,
    )
    print(
        f"[09] Creating benchmark machine pool {pool_name!r} ({mn}-{mx} nodes, multi_az={multi_az}) ...",
        file=sys.stderr,
    )
    _rosa_create_classic_bench_machinepool(
        cluster_name=cluster_name,
        pool_name=pool_name,
        min_replicas=mn,
        max_replicas=mx,
        dry_run=False,
    )


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
    """Return True if any overprovisioner pod is in Pending/Evicted/Failed state."""
    pods = oc_lib.get_pods(NAMESPACE, LABEL_OVERPROV, kubeconfig=kubeconfig)
    for pod in pods:
        phase = pod.get("status", {}).get("phase", "")
        if phase in ("Pending", "Failed"):
            return True
    return False


def _headroom_restored(kubeconfig: str | None, expected_count: int = 4) -> bool:
    """Return True when overprovisioner pods are all Running again."""
    pods = oc_lib.get_pods(NAMESPACE, LABEL_OVERPROV, kubeconfig=kubeconfig)
    running = [p for p in pods if p.get("status", {}).get("phase") == "Running"]
    return len(running) >= expected_count


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
    is_autonode: bool,
    machine_api_ns: str,
    kubeconfig: str | None,
    nodepool_name: str | None = None,
) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "label": label,
        "timestamp_ms": now_ms(),
        "node_names": sorted(oc_lib.get_node_names(kubeconfig=kubeconfig)),
        "node_count": oc_lib.get_node_count(kubeconfig=kubeconfig),
    }
    if is_autonode:
        if nodepool_name:
            snap["nodeclaim_count"] = oc_lib.get_nodeclaim_count(
                nodepool_name=nodepool_name, kubeconfig=kubeconfig
            )
        else:
            snap["nodeclaim_count"] = oc_lib.get_nodeclaim_count(kubeconfig=kubeconfig)
    else:
        snap["machineset_replicas"] = oc_lib.get_machineset_replica_counts(
            machine_api_ns, kubeconfig=kubeconfig
        )
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


def _post_restore_observe_scale_down_09(
    *,
    kubeconfig: str | None,
    is_autonode: bool,
    nodepool_name: str | None,
    baseline_sel_key: str,
    baseline_sel_val: str,
    append_snapshot: Callable[[str], dict[str, Any]],
    result: BenchmarkResult,
    scale_down_timeout_s: int,
    stable_polls: int,
    skip: bool,
    dry_run: bool,
) -> None:
    """
    Idle cpu-burner so HPA scales to minReplicas, then wait for fleet size to stabilize
    (NodeClaims on AutoNode; Ready nodes on the benchmark pool label for CAS).
    Restores the stress command before returning.
    """
    if skip or dry_run:
        return

    hpa_phase_s = max(60, scale_down_timeout_s // 2)
    fleet_phase_s = max(60, scale_down_timeout_s - hpa_phase_s)

    if is_autonode:
        np = nodepool_name or ""

        def fleet_size() -> int:
            return oc_lib.get_nodeclaim_count(nodepool_name=np, kubeconfig=kubeconfig)

        fleet_metric = "nodeclaim_count"
    else:

        def fleet_size() -> int:
            return oc_lib.get_ready_node_count_for_label(
                baseline_sel_key,
                baseline_sel_val,
                kubeconfig=kubeconfig,
            )

        fleet_metric = f"ready_nodes:{baseline_sel_key}={baseline_sel_val}"

    _ = append_snapshot("before_hpa_scale_down_burn")
    try:
        fleet_before = fleet_size()
    except oc_lib.OcError as exc:
        print(f"[09] WARNING: could not read fleet size before idle: {exc}", file=sys.stderr)
        fleet_before = -1

    t_idle_start = now_ms()
    print(
        "[09] Idling cpu-burner (sleep) so HPA can scale down; then watching fleet size stabilize ...",
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
        print(f"[09] WARNING: could not idle cpu-burner: {exc}", file=sys.stderr)
        result.extra["scale_down"] = {
            "skipped": True,
            "reason": f"idle_patch_failed: {exc}",
            "fleet_metric": fleet_metric,
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
            f"[09] WARNING: HPA did not reach min replicas within {hpa_phase_s}s. "
            "Skipping fleet stabilization.",
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
        fleet_after_size, fleet_ok = _poll_fleet_size_stable(
            fleet_size,
            stable_need=stable_polls,
            interval_s=30,
            timeout_s=fleet_phase_s,
            label="Fleet size stable",
        )
        if not fleet_ok:
            print(
                f"[09] WARNING: Fleet size not stable within {fleet_phase_s}s.",
                file=sys.stderr,
            )

    t_fleet_done = now_ms()
    if hpa_ok:
        result.milestone(
            "hpa_min_replicas_to_fleet_stable",
            t_hpa_min,
            t_fleet_done,
            meta={"fleet_ok": str(fleet_ok), "stable_polls": str(stable_polls)},
        )

    append_snapshot("after_fleet_scale_down")

    if fleet_after_size is not None:
        fleet_final = fleet_after_size
    else:
        try:
            fleet_final = fleet_size()
        except oc_lib.OcError:
            fleet_final = fleet_before if fleet_before >= 0 else 0

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
        print(f"[09] WARNING: could not restore cpu-burner stress command: {exc}", file=sys.stderr)

    result.extra["scale_down"] = {
        "fleet_metric": fleet_metric,
        "nodepool_name": nodepool_name if is_autonode else None,
        "baseline_pool": f"{baseline_sel_key}={baseline_sel_val}",
        "fleet_size_before_idle": fleet_before,
        "fleet_size_after_stable_or_snapshot": fleet_final,
        "hpa_at_min_replicas": hpa_ok,
        "fleet_size_stable": fleet_ok,
        "stable_polls_required": stable_polls,
        "timeout_budget_s": scale_down_timeout_s,
        "hpa_phase_timeout_s": hpa_phase_s,
        "fleet_phase_timeout_s": fleet_phase_s,
    }


def _measure_cpu_slack_kubeconfig(kubeconfig: str | None) -> tuple[float, int, int]:
    """Return (slack_cores, alloc_mc, req_mc)."""
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


def _rosa_edit_machinepool_autoscale(
    *,
    cluster_name: str,
    pool_name: str,
    min_replicas: int | None,
    max_replicas: int | None,
    dry_run: bool,
) -> None:
    if min_replicas is None and max_replicas is None:
        return
    if dry_run:
        print(
            f"[09] dry-run: would rosa edit machinepool {pool_name!r} "
            f"min={min_replicas} max={max_replicas}",
            file=sys.stderr,
        )
        return
    rosa = shutil.which("rosa")
    if not rosa:
        raise RuntimeError("rosa CLI not found on PATH (needed for --rosa-machinepool-min/max)")
    cmd = [
        rosa,
        "edit",
        "machinepool",
        "-c",
        cluster_name,
        "--enable-autoscaling",
    ]
    if min_replicas is not None:
        cmd.append(f"--min-replicas={min_replicas}")
    if max_replicas is not None:
        cmd.append(f"--max-replicas={max_replicas}")
    cmd.append(pool_name)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        _raise_if_rosa_503(proc.stdout or "", proc.stderr or "")
        err = (proc.stderr or proc.stdout or "").strip()[:500]
        raise RuntimeError(f"rosa edit machinepool failed (exit {proc.returncode}): {err}")


def main() -> None:
    parser = standard_args("Test 09 — Overprovisioning with pause pods benchmark.")
    parser.add_argument(
        "--cpu-burner-replicas",
        type=int,
        default=3,
        help="Number of cpu-burner replicas to request (default: 3).",
    )
    parser.add_argument(
        "--saturated-pool-baseline",
        action="store_true",
        help=(
            "Wait for N benchmark workers, apply pause+filler+cpu-burner+HPA together (then HPA burst). "
            "Use with --baseline-pool-ready-count and optional --capacity-filler-replicas "
            "(omit to auto-size filler from the pool). "
        ),
    )
    parser.add_argument(
        "--baseline-pool-ready-count",
        type=int,
        default=3,
        help="With --saturated-pool-baseline: wait for this many Ready nodes on the pool selector (default: 3).",
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
        help=(
            "After apply, scale capacity-filler to this many replicas. "
            "Omit with --saturated-pool-baseline to **compute** from live pool "
            "allocatable vs requests (benchmark namespace excluded). "
            "Legacy saturated fallback: manifest default until scaled."
        ),
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help=(
            "When cluster-type=hcp-autonode: karpenter.sh/nodepool label value for baseline counts "
            "and NodeClaim snapshots (default: autonode-bench)."
        ),
    )
    parser.add_argument(
        "--machinepool-name",
        default="bench-standard",
        help="Machine pool name for classic bench / --rosa-machinepool-min/max (default: bench-standard).",
    )
    parser.add_argument(
        "--skip-classic-bench-machinepool-create",
        action="store_true",
        help=(
            "ROSA Classic only: do not run `rosa create machinepool` when the bench pool is missing "
            "(default is to create it with labels benchmark=true,pool-type=standard)."
        ),
    )
    parser.add_argument(
        "--rosa-machinepool-min",
        type=int,
        default=None,
        help="If set (classic/hcp): `rosa edit machinepool` min replicas before baseline wait.",
    )
    parser.add_argument(
        "--rosa-machinepool-max",
        type=int,
        default=None,
        help="If set (classic/hcp): `rosa edit machinepool` max replicas (must allow +1 for balloon restore).",
    )
    parser.add_argument(
        "--require-saturated-before-balloons",
        action="store_true",
        help=(
            "Fail when measured allocatable CPU slack is at or above --max-slack-cpu-cores: "
            "before pause pods if default flow; after the workload bundle if --saturated-pool-baseline."
        ),
    )
    parser.add_argument(
        "--max-slack-cpu-cores",
        type=float,
        default=2.0,
        help="Slack threshold (cores) for --require-saturated-before-balloons (default: 2).",
    )
    parser.add_argument(
        "--expect-worker-count",
        type=int,
        default=None,
        help="If set, fail preflight when Ready node count does not match.",
    )
    parser.add_argument(
        "--skip-scale-down-observe",
        action="store_true",
        help=(
            "After headroom restore: do not idle cpu-burner for HPA scale-down or wait for fleet size "
            "to stabilize (CAS/Karpenter scale-down)."
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
                f"[09] Using run-id from tmp/cluster.{args.cluster_type}.json: {resolved}",
                file=sys.stderr,
            )
    if args.sustained_peak_duration_s > 0:
        min_recommended = args.sustained_peak_duration_s + 2400
        if args.timeout < min_recommended:
            print(
                f"[09] WARNING: --timeout {args.timeout}s may be too low for sustained peak "
                f"({args.sustained_peak_duration_s}s) plus headroom restore and optional observe. "
                f"Consider --timeout {min_recommended} or higher.",
                file=sys.stderr,
            )
    kubeconfig = resolve_kubeconfig(args)
    target_replicas: int = args.cpu_burner_replicas
    is_autonode = args.cluster_type == "hcp-autonode"
    nodepool_name: str = args.nodepool_name

    filler_replicas_effective: int | None = args.capacity_filler_replicas

    if is_autonode:
        baseline_sel_key = "karpenter.sh/nodepool"
        baseline_sel_val = nodepool_name
    else:
        baseline_sel_key = "pool-type"
        baseline_sel_val = "standard"

    manifest_pause = MANIFEST_PAUSE_KARPENTER if is_autonode else MANIFEST_PAUSE
    manifest_cpu_burner = MANIFEST_CPU_BURNER_KARPENTER if is_autonode else MANIFEST_CPU_BURNER
    manifest_filler = MANIFEST_FILLER_KARPENTER if is_autonode else MANIFEST_FILLER

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["fleet_snapshots"] = []

    handle_sigint(lambda: cleanup(kubeconfig), run_id=args.run_id, test_id=TEST_ID, result=result)

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    if args.cluster_type == "classic":
        try:
            _ensure_classic_bench_machinepool_if_missing(
                cluster_name=args.cluster_name,
                pool_name=args.machinepool_name,
                saturated=args.saturated_pool_baseline,
                min_replicas=args.rosa_machinepool_min,
                max_replicas=args.rosa_machinepool_max,
                dry_run=args.dry_run,
                skip_create=args.skip_classic_bench_machinepool_create,
            )
        except RosaOcm503 as exc:
            fatal(
                str(exc),
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )
        except RuntimeError as exc:
            fatal(
                f"Classic bench machine pool setup failed: {exc}",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )

    snapshots: list[dict[str, Any]] = result.extra["fleet_snapshots"]

    def append_snapshot(label: str) -> dict[str, Any]:
        snap = _snapshot_fleet(
            label,
            is_autonode=is_autonode,
            machine_api_ns=MACHINE_API_NS,
            kubeconfig=kubeconfig,
            nodepool_name=(nodepool_name if is_autonode else None),
        )
        snapshots.append(snap)
        return snap

    # ── Topology: saturated pool bundle vs pause-first (legacy) ───────────────
    pause_requested_cores = PAUSE_REPLICAS * PAUSE_CPU_PER_POD_CORES

    if args.saturated_pool_baseline:
        result.extra["topology_mode"] = "saturated_pool_baseline"
        result.extra["baseline_pool_selector"] = f"{baseline_sel_key}={baseline_sel_val}"

        if not is_autonode:
            try:
                _rosa_edit_machinepool_autoscale(
                    cluster_name=args.cluster_name,
                    pool_name=args.machinepool_name,
                    min_replicas=args.rosa_machinepool_min,
                    max_replicas=args.rosa_machinepool_max,
                    dry_run=args.dry_run,
                )
            except RosaOcm503 as exc:
                fatal(
                    str(exc),
                    run_id=args.run_id,
                    test_id=TEST_ID,
                    result=result,
                )
            except RuntimeError as exc:
                fatal(
                    f"ROSA machine pool adjustment failed: {exc}",
                    run_id=args.run_id,
                    test_id=TEST_ID,
                    result=result,
                )
        elif args.rosa_machinepool_min is not None or args.rosa_machinepool_max is not None:
            print(
                "[09] WARN: --rosa-machinepool-min/max ignored on hcp-autonode "
                "(set NodePool limits via Terraform or the console).",
                file=sys.stderr,
            )

        print(
            f"[09] Waiting for >= {args.baseline_pool_ready_count} Ready node(s) "
            f"with {baseline_sel_key}={baseline_sel_val!r} ...",
            file=sys.stderr,
        )

        def _pool_big_enough() -> bool:
            return (
                oc_lib.get_ready_node_count_for_label(
                    baseline_sel_key,
                    baseline_sel_val,
                    kubeconfig=kubeconfig,
                )
                >= args.baseline_pool_ready_count
            )

        try:
            if not args.dry_run:
                oc_lib.poll_until(
                    _pool_big_enough,
                    timeout_s=args.baseline_pool_wait_timeout_s,
                    interval_s=20,
                    label=f">= {args.baseline_pool_ready_count} ready pool nodes",
                )
        except oc_lib.PollTimeout:
            fatal(
                f"Timed out waiting for {args.baseline_pool_ready_count} Ready node(s) "
                f"with {baseline_sel_key}={baseline_sel_val}. "
                "The pool may still be reconciling (quota, capacity). "
                "Tune --rosa-machinepool-min/max, fix CAS, or remove "
                "--skip-classic-bench-machinepool-create if the pool was never created.",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )

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
                    f"[09] dry-run: placeholder capacity-filler replicas={filler_replicas_effective} "
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
                    f"[09] Computed capacity-filler replicas={filler_replicas_effective} "
                    f"({baseline_sel_key}={baseline_sel_val!r}; "
                    f"projected slack ≈{sizing_meta['projected_cpu_slack_cores_after_scale']} cores).",
                    file=sys.stderr,
                )

        snap_t0 = append_snapshot("t0_baseline")

        print(
            "[09] Applying PriorityClass, pause pods, capacity-filler, cpu-burner, HPA (bundled baseline) ...",
            file=sys.stderr,
        )
        if not args.dry_run:
            oc_lib.apply_manifest(str(MANIFEST_PRIORITY_CLASS), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(manifest_pause), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(manifest_filler), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(manifest_cpu_burner), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(MANIFEST_HPA), kubeconfig=kubeconfig)

        if filler_replicas_effective is not None:
            print(
                f"[09] Scaling capacity-filler to {filler_replicas_effective} replicas ...",
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
        print("[09] capacity-filler and cpu-burner Ready (bundled).", file=sys.stderr)

        print("[09] Waiting for overprovisioner pause pods to be Running ...", file=sys.stderr)
        t_start = now_ms()
        try:
            if not args.dry_run:
                oc_lib.wait_for_all_pods_running(
                    NAMESPACE,
                    LABEL_OVERPROV,
                    expected_count=PAUSE_REPLICAS,
                    timeout_s=1200,
                    interval_s=20,
                    kubeconfig=kubeconfig,
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
                    "Raise --capacity-filler-replicas or reduce pool size.",
                    run_id=args.run_id,
                    test_id=TEST_ID,
                    result=result,
                )
            elif slack_cores >= pause_requested_cores:
                print(
                    "[09] WARN: post-bundle slack ≥ pause-pod CPU requests; "
                    "HPA burst may still use spare capacity.",
                    file=sys.stderr,
                )

            result.milestone(
                "start_to_headroom_ready",
                t_start,
                t_headroom_ready,
                meta={
                    "new_nodes": str(len(new_for_balloons)),
                    "topology": "saturated_pool_baseline",
                },
            )
            print(
                f"[09] Pause pods Running ({elapsed_human(t_start, t_headroom_ready)}); "
                f"+{len(new_for_balloons)} new node name(s) vs t0; "
                f"pool slack={slack_cores:.2f} cores ({baseline_sel_key}={baseline_sel_val}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            fatal(
                "Pause pods did not reach Running within 20m.",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )

    else:
        result.extra["topology_mode"] = "pause_first_then_filler"
        # ── Step 0 — Baseline preflight (before pause pods) ──────────────────
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
                f"(threshold {args.max_slack_cpu_cores}). Cluster may absorb burst without new nodes. "
                "Re-run on a cleaner baseline, use --saturated-pool-baseline, or raise --max-slack-cpu-cores.",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )
        elif slack_cores >= pause_requested_cores:
            print(
                "[09] WARN: cluster slack ≥ pause-pod CPU requests; "
                "balloons may schedule without forcing new nodes.",
                file=sys.stderr,
            )

        snap_t0 = append_snapshot("t0_baseline")

        # ── Step 1 — Apply PriorityClass and pause pods ───────────────────────
        print("[09] Applying PriorityClass and pause-deployment ...", file=sys.stderr)
        if not args.dry_run:
            oc_lib.apply_manifest(str(MANIFEST_PRIORITY_CLASS), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(manifest_pause), kubeconfig=kubeconfig)

        # ── Step 2 — Wait for pause pods Running (CAS may provision nodes) ────
        print(
            "[09] Waiting for overprovisioner pause pods to be Running "
            "(CAS may need to provision capacity) ...",
            file=sys.stderr,
        )
        t_start = now_ms()
        try:
            if not args.dry_run:
                oc_lib.wait_for_all_pods_running(
                    NAMESPACE,
                    LABEL_OVERPROV,
                    expected_count=PAUSE_REPLICAS,
                    timeout_s=1200,
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
                meta={"new_nodes": str(len(new_for_balloons))},
            )
            print(
                f"[09] Pause pods Running — headroom reserved "
                f"({elapsed_human(t_start, t_headroom_ready)}); "
                f"+{len(new_for_balloons)} new node name(s) vs t0.",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            fatal(
                "Pause pods did not reach Running within 20m. "
                "Check machine pool autoscaling is enabled and quota allows additional nodes.",
                run_id=args.run_id,
                test_id=TEST_ID,
                result=result,
            )

        # ── Step 3 — Re-saturate with capacity-filler + cpu-burner + HPA ───────
        print("[09] Applying capacity-filler, cpu-burner, and HPA (same setup as test 08) ...", file=sys.stderr)
        if not args.dry_run:
            oc_lib.apply_manifest(str(manifest_filler), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(manifest_cpu_burner), kubeconfig=kubeconfig)
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
        print("[09] capacity-filler and cpu-burner Ready.", file=sys.stderr)

    # ── Step 4 — Trigger HPA (scale cpu-burner) ───────────────────────────────
    print(f"[09] Scaling cpu-burner to {target_replicas} replicas ...", file=sys.stderr)
    t_hpa_trigger = now_ms()
    if not args.dry_run:
        oc_lib.scale_deployment(CPU_BURNER, target_replicas, NAMESPACE, kubeconfig=kubeconfig)
    snap_hpa = append_snapshot("at_hpa_trigger")

    # ── Step 5 — Watch pause pods evicted (preemption — should be seconds) ────
    print("[09] Watching for pause pod eviction (preemption) ...", file=sys.stderr)
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
            f"[09] Pause pods preempted ({elapsed_human(t_hpa_trigger, t_preempted)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            "[09] WARNING: Pause pods not evicted within 2m — cluster may have had spare capacity "
            "even beyond the overprovisioner headroom.",
            file=sys.stderr,
        )
        t_preempted = now_ms()

    # ── Step 6 — Watch cpu-burner pods Running (key metric: should be fast) ──
    print("[09] Waiting for cpu-burner pods to be Running ...", file=sys.stderr)
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
            },
        )
        print(
            f"[09] {len(running_pods)} cpu-burner pods Running — {mechanism} "
            f"({elapsed_human(t_hpa_trigger, t_pods_running)}): {evidence}.",
            file=sys.stderr,
        )
        result.extra["hpa_to_running_ms"] = t_pods_running - t_hpa_trigger

        # Step 6b — Wait for pods Ready (readiness probes pass / traffic-serving state)
        print("[09] Waiting for cpu-burner pods to be Ready ...", file=sys.stderr)
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
                meta={"mechanism": mechanism, "pod_count": str(len(ready_pods))},
            )
            print(
                f"[09] {len(ready_pods)} pods Ready "
                f"(+{elapsed_human(t_pods_running, t_pods_ready)} after Running; "
                f"hpa→ready: {elapsed_human(t_hpa_trigger, t_pods_ready)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[09] WARNING: pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        t_pods_running = now_ms()
        print(
            "[09] WARNING: cpu-burner pods did not reach Running within 5m via preemption. "
            "The pause pods may not have been large enough to free sufficient capacity.",
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
            is_autonode=is_autonode,
            nodepool_name=nodepool_name if is_autonode else None,
            machine_api_ns=MACHINE_API_NS,
            result=result,
            log_prefix="[09]",
        )
    elif args.dry_run and args.sustained_peak_duration_s > 0 and snap_running is not None:
        print(
            f"[09] dry-run: would poll cluster every {args.sustained_peak_poll_interval_s}s for "
            f"{args.sustained_peak_duration_s}s during sustained peak.",
            file=sys.stderr,
        )

    # ── Step 8 — Watch CAS / Karpenter restore headroom ────────────────────────
    print(
        "[09] Waiting for autoscaler to provision new capacity and restore pause pods ...",
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
            f"[09] Headroom restored ({elapsed_human(t_pods_running, t_headroom_restored)} "
            "after pods were Running).",
            file=sys.stderr,
        )
        result.extra["headroom_restore_ms"] = t_headroom_restored - t_pods_running
        if snap_running is not None:
            result.extra["restore_fleet_delta"] = _compute_restore_delta(
                snap_running, snap_restore, is_autonode
            )
    except oc_lib.PollTimeout:
        print(
            "[09] WARNING: Headroom not restored within timeout. "
            "Autoscaler may still be provisioning.",
            file=sys.stderr,
        )
        snap_restore = append_snapshot("after_restore_poll_timeout")
        if snap_running is not None:
            result.extra["restore_fleet_delta"] = _compute_restore_delta(
                snap_running, snap_restore, is_autonode
            )

    _post_restore_observe_scale_down_09(
        kubeconfig=kubeconfig,
        is_autonode=is_autonode,
        nodepool_name=nodepool_name if is_autonode else None,
        baseline_sel_key=baseline_sel_key,
        baseline_sel_val=baseline_sel_val,
        append_snapshot=append_snapshot,
        result=result,
        scale_down_timeout_s=args.scale_down_timeout_s,
        stable_polls=args.scale_down_stable_polls,
        skip=args.skip_scale_down_observe,
        dry_run=args.dry_run,
    )

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cleanup(kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
