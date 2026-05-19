#!/usr/bin/env python3
"""
scripts/run-test-11-planned-surge.py

Benchmark: Planned Surge — proactive strategies for a known traffic peak (Test 11)

Simulates a retail "planned sale" scenario: you know traffic is coming, so you
prepare the cluster ahead of time. Measures how quickly all pods reach a Ready
(traffic-serving) state from the moment HPA detects the CPU surge.

Two preparation strategies are compared side-by-side:

  balloon-pods (default):
    Pre-deploy low-priority pause pods (balloon pods) that hold warm cluster
    capacity. When HPA fires, these pods are immediately evicted and cpu-burner
    pods schedule on the freed slots — no CAS/Karpenter wait for the first wave.
    CAS/Karpenter then restores the balloon pod headroom in the background.
    This shows that with careful design even CAS (slower provisioner) can serve
    the first response quickly.

  proactive-nodes:
    Pre-provision N extra nodes by deploying a placeholder workload that forces
    CAS/Karpenter to provision them. Once nodes are Ready, the placeholder keeps
    a minimal footprint so nodes aren't reclaimed. When HPA fires, the surge pods
    schedule immediately onto the pre-warmed nodes with no provisioning delay.
    This simulates "scale up the cluster 20 minutes before the sale starts."

Both strategies use real HPA: cpu-burner runs at 100% CPU (its normal rate),
HPA is applied at the surge moment and fires when metrics-server detects the
overutilization. The trigger-to-first-pod-Ready time captures the real
autoscaling chain including the metrics-server polling window.

Procedure (balloon-pods):
  1. Apply PriorityClass + surge-overprovisioner (N balloon pods). Wait Running.
  2. Deploy cpu-burner at 1 replica (burning CPU). Wait Ready. Do NOT apply HPA.
  3. t_surge = apply HPA → HPA now begins monitoring.
  4. Poll until HPA desiredReplicas > 1 (metrics-server window, ~15–30 s).
  5. Watch for balloon pod eviction events.
  6. Track readiness curve: first Ready, 50% Ready, all Ready.
  7. If pods needed new nodes (overflow), record scheduler decision + node Ready.

Procedure (proactive-nodes):
  1. Apply trigger workload (30 replicas) to force N new nodes. Wait nodes Ready.
  2. Deploy cpu-burner at 1 replica alongside the trigger. Wait Ready.
  3. t_surge = apply HPA → HPA begins monitoring.
  4. Poll until HPA desiredReplicas > 1.
  5. Track readiness curve (should be fast — nodes pre-provisioned).
  6. Scale trigger to 0 after cpu-burner pods are all Running.

Milestones (both strategies):
  - preparation_to_ready           (strategy setup cost)
  - surge_trigger_to_hpa_decision  (metrics-server window)
  - surge_trigger_to_first_pod_ready   ← key: first user served
  - surge_trigger_to_50pct_ready
  - surge_trigger_to_all_ready         ← full capacity restored

Additional for balloon-pods:
  - surge_trigger_to_preemption    (balloon pods evicted)

Additional for proactive-nodes:
  - preparation_to_first_node_ready (how long pre-provisioning took)

Cleanup: scale cpu-burner to 1, delete HPA, remove balloon/trigger pods.

Usage:
  python3 scripts/run-test-11-planned-surge.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--strategy balloon-pods|proactive-nodes] \\
      [--balloon-replicas 5] \\
      [--prewarm-nodes 2] \\
      [--nodepool-name autonode-bench]
"""

from __future__ import annotations

import sys
import time
from contextlib import suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib import oc as oc_lib
from scripts.lib.bench import (
    BenchmarkResult,
    checkpoint_complete,
    checkpoint_start,
    elapsed_human,
    fatal,
    handle_sigint,
    now_ms,
    resolve_kubeconfig,
    standard_args,
    verify_oc_login,
)

TEST_ID = "11-planned-surge"
NAMESPACE = "benchmark"
MACHINE_API_NS = "openshift-machine-api"
CPU_BURNER = "cpu-burner"
SURGE_OVERPROV = "surge-overprovisioner"
HPA_NAME = "cpu-burner-hpa"
LABEL_CPU_BURNER = "app=cpu-burner"
LABEL_SURGE_OVERPROV = "app=surge-overprovisioner"
HPA_CPU_THRESHOLD = 50  # matches hpa.yaml target: 50%

_WORKLOADS = Path(__file__).parent.parent / "manifests" / "workloads"
_AUTOSCALING = Path(__file__).parent.parent / "manifests" / "autoscaling"
_OVERPROV = Path(__file__).parent.parent / "manifests" / "overprovisioning"

MANIFEST_CPU_BURNER = _WORKLOADS / "cpu-burner.yaml"
MANIFEST_CPU_BURNER_KARPENTER = _WORKLOADS / "cpu-burner-karpenter.yaml"
MANIFEST_HPA = _AUTOSCALING / "hpa.yaml"
MANIFEST_PRIORITY_CLASS = _OVERPROV / "priority-class.yaml"
MANIFEST_SURGE_OVERPROV = _OVERPROV / "surge-overprovisioner.yaml"
MANIFEST_SURGE_OVERPROV_KARPENTER = _OVERPROV / "surge-overprovisioner-karpenter.yaml"
MANIFEST_CAS_TRIGGER = _WORKLOADS / "cas-trigger.yaml"
MANIFEST_KARPENTER_TRIGGER = _WORKLOADS / "karpenter-trigger-100.yaml"

_SAMPLE_S = 10   # readiness curve poll interval


def _get_hpa_desired(hpa: dict) -> int:
    return hpa.get("status", {}).get("desiredReplicas", 0)


def _get_hpa_current_cpu(hpa: dict) -> int | None:
    for m in (hpa.get("status", {}).get("currentMetrics") or []):
        if m.get("type") == "Resource":
            v = m.get("resource", {}).get("current", {}).get("averageUtilization")
            if v is not None:
                return int(v)
    return None


def _is_pod_ready(pod: dict) -> bool:
    if pod.get("status", {}).get("phase") != "Running":
        return False
    for cond in pod.get("status", {}).get("conditions", []):
        if cond.get("type") == "Ready" and cond.get("status") == "True":
            return True
    return False


def _track_readiness_curve(
    label_selector: str,
    target_replicas: int,
    t_surge: int,
    result: BenchmarkResult,
    kubeconfig: str | None,
    timeout_s: int,
    phase_prefix: str = "",
) -> None:
    """
    Poll pod readiness every _SAMPLE_S seconds from t_surge, recording:
      - first pod Ready
      - 50% pods Ready
      - all pods Ready

    phase_prefix (e.g. "balloon_pods.") namespaces milestones when called
    from multi-phase tests.
    """
    deadline = time.monotonic() + timeout_s
    snapshots_recorded: set[int] = set()
    first_reached = half_reached = all_reached = False
    half_threshold = (target_replicas + 1) // 2
    pfx = phase_prefix

    while time.monotonic() < deadline:
        time.sleep(_SAMPLE_S)
        try:
            pods = oc_lib.get_pods(NAMESPACE, label_selector, kubeconfig=kubeconfig)
        except oc_lib.OcError as exc:
            print(f"[11] WARNING: pod sample failed: {exc}", file=sys.stderr)
            continue

        ts = now_ms()
        elapsed_s = (ts - t_surge) // 1000
        ready = sum(1 for p in pods if _is_pod_ready(p))
        running = sum(1 for p in pods if p.get("status", {}).get("phase") == "Running")
        pending = sum(1 for p in pods if p.get("status", {}).get("phase") == "Pending")

        # Timed snapshots at 60 s, 120 s, 180 s
        for snap_s in (60, 120, 180):
            if snap_s not in snapshots_recorded and elapsed_s >= snap_s:
                snapshots_recorded.add(snap_s)
                result.extra[f"{pfx}snapshot_{snap_s}s_ready"] = ready
                result.extra[f"{pfx}snapshot_{snap_s}s_pending"] = pending
                print(f"[11] T+{snap_s}s: {ready} Ready, {running} Running, {pending} Pending.", file=sys.stderr)

        if not first_reached and ready >= 1:
            first_reached = True
            result.milestone(f"{pfx}surge_trigger_to_first_pod_ready", t_surge, ts,
                             meta={"elapsed_s": str(elapsed_s)})
            print(f"[11] First pod Ready at T+{elapsed_s}s.", file=sys.stderr)

        if not half_reached and ready >= half_threshold:
            half_reached = True
            result.milestone(f"{pfx}surge_trigger_to_50pct_ready", t_surge, ts,
                             meta={"ready": str(ready), "target": str(target_replicas)})
            print(f"[11] 50% Ready ({ready}/{target_replicas}) at T+{elapsed_s}s.", file=sys.stderr)

        if not all_reached and ready >= target_replicas:
            all_reached = True
            result.milestone(f"{pfx}surge_trigger_to_all_ready", t_surge, ts,
                             meta={"pod_count": str(ready)})
            print(f"[11] All {ready} pods Ready at T+{elapsed_s}s — surge absorbed.", file=sys.stderr)
            return

    print(f"[11] WARNING: not all pods reached Ready within {timeout_s}s.", file=sys.stderr)


def _run_balloon_pods_strategy(args, result: BenchmarkResult, kubeconfig: str | None) -> None:
    """
    Pre-deploy balloon pods → apply HPA as surge trigger → track readiness.
    """
    is_karpenter = args.cluster_type == "hcp-autonode"
    cpu_burner_manifest = MANIFEST_CPU_BURNER_KARPENTER if is_karpenter else MANIFEST_CPU_BURNER
    overprov_manifest = MANIFEST_SURGE_OVERPROV_KARPENTER if is_karpenter else MANIFEST_SURGE_OVERPROV
    balloon_replicas: int = args.balloon_replicas

    # ── Step 1 — Apply PriorityClass + balloon pods ───────────────────────────
    print(f"[11] Strategy: balloon-pods ({balloon_replicas} balloon pods).", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_PRIORITY_CLASS), kubeconfig=kubeconfig)
        oc_lib.apply_manifest(str(overprov_manifest), kubeconfig=kubeconfig)
        oc_lib.scale_deployment(SURGE_OVERPROV, balloon_replicas, NAMESPACE, kubeconfig=kubeconfig)

    t_prep_start = now_ms()
    print(f"[11] Waiting for {balloon_replicas} balloon pods to be Running ...", file=sys.stderr)
    try:
        oc_lib.wait_for_all_pods_running(
            NAMESPACE, LABEL_SURGE_OVERPROV,
            expected_count=balloon_replicas,
            timeout_s=600, interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_prep_done = now_ms()
        result.milestone("preparation_to_ready", t_prep_start, t_prep_done,
                         meta={"balloon_replicas": str(balloon_replicas), "strategy": "balloon-pods"})
        print(
            f"[11] {balloon_replicas} balloon pods Running "
            f"({elapsed_human(t_prep_start, t_prep_done)} preparation cost).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Balloon pods did not reach Running within 10m.",
            run_id=args.run_id, test_id=TEST_ID, result=result,
        )

    # ── Step 2 — Deploy cpu-burner at 1 replica (no HPA yet) ─────────────────
    print(f"[11] Deploying {cpu_burner_manifest.name} at 1 replica (no HPA) ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(cpu_burner_manifest), kubeconfig=kubeconfig)
        oc_lib.scale_deployment(CPU_BURNER, 1, NAMESPACE, kubeconfig=kubeconfig)
        oc_lib.wait_for_deployment_ready(CPU_BURNER, NAMESPACE, timeout_s=360, kubeconfig=kubeconfig)
    print("[11] cpu-burner at 1 replica, Ready.", file=sys.stderr)

    # ── Step 3 — Apply HPA = "the surge arrives" ─────────────────────────────
    hpa_target_replicas = balloon_replicas + 1  # HPA will want balloon_replicas+1 pods
    result.extra["hpa_max_replicas"] = hpa_target_replicas
    print(
        f"[11] Applying HPA — surge begins. HPA will scale to ~{hpa_target_replicas} replicas ...",
        file=sys.stderr,
    )
    t_surge = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_HPA), kubeconfig=kubeconfig)
    result.extra["surge_trigger_ms"] = t_surge

    # ── Step 4 — Wait for HPA scale decision (metrics-server window) ─────────
    print("[11] Waiting for HPA to fire (metrics-server detection) ...", file=sys.stderr)

    def _hpa_fired() -> bool:
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        desired = _get_hpa_desired(hpa)
        cpu = _get_hpa_current_cpu(hpa)
        if cpu is not None:
            print(f"[11] HPA: CPU={cpu}% desired={desired}", file=sys.stderr)
        return desired > 1

    try:
        oc_lib.poll_until(_hpa_fired, timeout_s=600, interval_s=15, label="HPA fires")
        t_hpa_fired = now_ms()
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        desired = _get_hpa_desired(hpa)
        result.milestone("surge_trigger_to_hpa_decision", t_surge, t_hpa_fired,
                         meta={"desired_replicas": str(desired)})
        print(
            f"[11] HPA decided {desired} replicas "
            f"({elapsed_human(t_surge, t_hpa_fired)} from trigger).",
            file=sys.stderr,
        )
        result.extra["hpa_desired_replicas"] = desired
    except oc_lib.PollTimeout:
        fatal(
            "HPA did not fire within 10m. Check metrics-server availability.",
            run_id=args.run_id, test_id=TEST_ID, result=result,
        )

    # ── Step 5 — Watch for balloon pod preemption ─────────────────────────────
    print("[11] Watching for balloon pod preemption ...", file=sys.stderr)
    try:
        oc_lib.wait_for_event(
            NAMESPACE, ["Preempted", "Preempting", "Evicted"],
            timeout_s=120, interval_s=5,
            kubeconfig=kubeconfig,
        )
        t_preempted = now_ms()
        result.milestone("surge_trigger_to_preemption", t_surge, t_preempted)
        print(f"[11] Balloon pods preempted ({elapsed_human(t_surge, t_preempted)}).", file=sys.stderr)
    except oc_lib.PollTimeout:
        print(
            "[11] No preemption events observed — balloon pods may not have needed evicting "
            "(cluster had spare capacity beyond balloon pod headroom).",
            file=sys.stderr,
        )

    # ── Step 6 — Track readiness curve ───────────────────────────────────────
    desired_replicas = result.extra.get("hpa_desired_replicas", hpa_target_replicas)
    remaining_s = max(300, args.timeout - ((now_ms() - t_surge) // 1000))
    _track_readiness_curve(
        LABEL_CPU_BURNER,
        int(desired_replicas),
        t_surge,
        result,
        kubeconfig,
        timeout_s=remaining_s,
    )


def _run_proactive_nodes_strategy(args, result: BenchmarkResult, kubeconfig: str | None) -> None:
    """
    Pre-provision N new nodes via placeholder trigger → apply HPA as surge
    trigger → pods land on pre-warmed nodes instantly.
    """
    is_karpenter = args.cluster_type == "hcp-autonode"
    cpu_burner_manifest = MANIFEST_CPU_BURNER_KARPENTER if is_karpenter else MANIFEST_CPU_BURNER
    trigger_manifest = MANIFEST_KARPENTER_TRIGGER if is_karpenter else MANIFEST_CAS_TRIGGER
    trigger_name = "karpenter-trigger" if is_karpenter else "cas-trigger"
    prewarm_nodes: int = args.prewarm_nodes

    # ── Step 1 — Apply trigger to force N new nodes ───────────────────────────
    print(
        f"[11] Strategy: proactive-nodes (pre-warming {prewarm_nodes} nodes).",
        file=sys.stderr,
    )
    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    t_prep_start = now_ms()

    # 30 replicas × 500m CPU saturates ~2 existing nodes and forces 2+ new nodes
    trigger_replicas = 30
    print(f"[11] Applying {trigger_manifest.name} at {trigger_replicas} replicas ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(trigger_manifest), kubeconfig=kubeconfig)
        oc_lib.scale_deployment(trigger_name, trigger_replicas, NAMESPACE, kubeconfig=kubeconfig)

    # ── Step 2 — Wait for N new nodes Ready ───────────────────────────────────
    print(f"[11] Waiting for {prewarm_nodes} new nodes to be Ready ...", file=sys.stderr)
    try:
        arrivals = oc_lib.watch_node_arrivals(
            baseline_names, prewarm_nodes,
            timeout_s=args.timeout, interval_s=20,
            kubeconfig=kubeconfig,
        )
        t_nodes_ready = arrivals[-1][1]
        result.milestone("preparation_to_first_node_ready", t_prep_start, arrivals[0][1])
        result.milestone("preparation_to_ready", t_prep_start, t_nodes_ready,
                         meta={"nodes_prewarmed": str(len(arrivals)), "strategy": "proactive-nodes"})
        print(
            f"[11] {len(arrivals)} nodes pre-warmed "
            f"({elapsed_human(t_prep_start, t_nodes_ready)} preparation cost).",
            file=sys.stderr,
        )
        result.extra["prewarmed_nodes"] = [n for n, _ in arrivals]
    except oc_lib.PollTimeout:
        fatal(
            f"Only {0}/{prewarm_nodes} new nodes Ready within timeout.",
            run_id=args.run_id, test_id=TEST_ID, result=result,
        )

    # ── Step 3 — Deploy cpu-burner at 1 replica alongside trigger ────────────
    print(f"[11] Deploying {cpu_burner_manifest.name} at 1 replica (no HPA) ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(cpu_burner_manifest), kubeconfig=kubeconfig)
        oc_lib.scale_deployment(CPU_BURNER, 1, NAMESPACE, kubeconfig=kubeconfig)
        oc_lib.wait_for_deployment_ready(CPU_BURNER, NAMESPACE, timeout_s=360, kubeconfig=kubeconfig)
    print("[11] cpu-burner at 1 replica, Ready.", file=sys.stderr)

    # ── Step 4 — Apply HPA = "the surge arrives" ─────────────────────────────
    print("[11] Applying HPA — surge begins ...", file=sys.stderr)
    t_surge = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_HPA), kubeconfig=kubeconfig)
    result.extra["surge_trigger_ms"] = t_surge

    # ── Step 5 — Wait for HPA scale decision ─────────────────────────────────
    def _hpa_fired() -> bool:
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        desired = _get_hpa_desired(hpa)
        cpu = _get_hpa_current_cpu(hpa)
        if cpu is not None:
            print(f"[11] HPA: CPU={cpu}% desired={desired}", file=sys.stderr)
        return desired > 1

    try:
        oc_lib.poll_until(_hpa_fired, timeout_s=600, interval_s=15, label="HPA fires")
        t_hpa_fired = now_ms()
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        desired = _get_hpa_desired(hpa)
        result.milestone("surge_trigger_to_hpa_decision", t_surge, t_hpa_fired,
                         meta={"desired_replicas": str(desired)})
        print(
            f"[11] HPA decided {desired} replicas "
            f"({elapsed_human(t_surge, t_hpa_fired)} from trigger).",
            file=sys.stderr,
        )
        result.extra["hpa_desired_replicas"] = desired
    except oc_lib.PollTimeout:
        fatal(
            "HPA did not fire within 10m.",
            run_id=args.run_id, test_id=TEST_ID, result=result,
        )

    # ── Step 6 — Scale trigger to 0 once cpu-burner pods are Running ─────────
    # Pods should land on pre-warmed nodes quickly; trigger then released.
    print("[11] Waiting for cpu-burner pods Running before releasing trigger ...", file=sys.stderr)
    desired_replicas = result.extra.get("hpa_desired_replicas", 6)
    with suppress(oc_lib.PollTimeout):
        oc_lib.wait_for_all_pods_running(
            NAMESPACE, LABEL_CPU_BURNER,
            expected_count=int(desired_replicas),
            timeout_s=300, interval_s=10,
            kubeconfig=kubeconfig,
        )

    if not args.dry_run:
        try:
            oc_lib.scale_deployment(trigger_name, 0, NAMESPACE, kubeconfig=kubeconfig)
            print(f"[11] Scaled {trigger_name} to 0 (nodes stay for scale-down delay).", file=sys.stderr)
        except Exception as exc:
            print(f"[11] WARNING: could not scale trigger to 0: {exc}", file=sys.stderr)

    # ── Step 7 — Track readiness curve ───────────────────────────────────────
    remaining_s = max(300, args.timeout - ((now_ms() - t_surge) // 1000))
    _track_readiness_curve(
        LABEL_CPU_BURNER,
        int(desired_replicas),
        t_surge,
        result,
        kubeconfig,
        timeout_s=remaining_s,
    )


def cleanup(strategy: str, is_karpenter: bool, kubeconfig: str | None) -> None:
    """Scale/delete workloads deployed by T11."""
    try:
        oc_lib.scale_deployment(CPU_BURNER, 1, NAMESPACE, kubeconfig=kubeconfig)
        print("[cleanup] cpu-burner → 1 replica.", file=sys.stderr)
    except Exception as exc:
        print(f"[cleanup] warning cpu-burner: {exc}", file=sys.stderr)
    try:
        oc_lib.delete_object("hpa", HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        print("[cleanup] HPA deleted.", file=sys.stderr)
    except Exception as exc:
        print(f"[cleanup] warning hpa: {exc}", file=sys.stderr)
    if strategy == "balloon-pods":
        try:
            oc_lib.scale_deployment(SURGE_OVERPROV, 0, NAMESPACE, kubeconfig=kubeconfig)
            print("[cleanup] surge-overprovisioner → 0.", file=sys.stderr)
        except Exception as exc:
            print(f"[cleanup] warning surge-overprovisioner: {exc}", file=sys.stderr)
    elif strategy == "proactive-nodes":
        trigger = "karpenter-trigger" if is_karpenter else "cas-trigger"
        try:
            oc_lib.scale_deployment(trigger, 0, NAMESPACE, kubeconfig=kubeconfig)
            print(f"[cleanup] {trigger} → 0.", file=sys.stderr)
        except Exception as exc:
            print(f"[cleanup] warning {trigger}: {exc}", file=sys.stderr)


def main() -> None:
    parser = standard_args("Test 11 — Planned surge: proactive strategies benchmark.")
    parser.add_argument(
        "--strategy",
        choices=["balloon-pods", "proactive-nodes"],
        default="balloon-pods",
        help=(
            "Preparation strategy: balloon-pods (pre-reserve capacity via low-priority pods) "
            "or proactive-nodes (pre-provision N extra nodes). Default: balloon-pods."
        ),
    )
    parser.add_argument(
        "--balloon-replicas",
        type=int,
        default=5,
        help=(
            "Number of balloon pods to pre-deploy (balloon-pods strategy). "
            "Set to expected_surge_replicas - 1. Default: 5."
        ),
    )
    parser.add_argument(
        "--prewarm-nodes",
        type=int,
        default=2,
        help="Number of extra nodes to pre-provision (proactive-nodes strategy). Default: 2.",
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help="Karpenter NodePool name (hcp-autonode only).",
    )
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)
    is_karpenter = args.cluster_type == "hcp-autonode"

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["strategy"] = args.strategy
    result.extra["scenario"] = "planned_surge"

    handle_sigint(
        lambda: cleanup(args.strategy, is_karpenter, kubeconfig),
        run_id=args.run_id,
        test_id=TEST_ID,
        result=result,
    )

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # ── Record baseline ───────────────────────────────────────────────────────
    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    print(f"[11] Baseline: {len(baseline_names)} Ready nodes.", file=sys.stderr)
    result.extra["baseline_node_count"] = len(baseline_names)

    # ── Run chosen strategy ───────────────────────────────────────────────────
    if args.strategy == "balloon-pods":
        _run_balloon_pods_strategy(args, result, kubeconfig)
    else:
        _run_proactive_nodes_strategy(args, result, kubeconfig)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cleanup(args.strategy, is_karpenter, kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
