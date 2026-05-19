#!/usr/bin/env python3
"""
scripts/run-test-12-sudden-spike.py

Benchmark: Sudden Spike - two-phase comparison showing the value of layered
autoscaling design (Test 12)

Simulates the retail "influencer spike": an unexpected 10x traffic surge with no
prior warning. Runs two back-to-back phases on the same cluster to produce a
direct comparison:

  Phase 1 - No preparation (straight CAS/Karpenter):
    The cluster is at production capacity (capacity-filler). HPA fires when
    cpu-burner pods spike CPU. New pods go Pending, waiting for CAS/Karpenter
    to provision nodes. The "degradation window" - time until all pods are Ready
    - is typically 8-12 min for CAS, 3-5 min for Karpenter.

  Phase 2 - Full three-layer stack (HPA + balloon pods + CAS/Karpenter):
    Balloon pods pre-reserve capacity with the cluster-overprovisioner priority
    class. When HPA fires, the first wave of cpu-burner pods immediately preempts
    the balloon pods (no node wait). CAS/Karpenter then restores balloon pod
    headroom in the background. The first-pod-Ready time drops to ~5-15 seconds.

The key message: with good autoscaling design, the choice between CAS and
Karpenter matters much less than the design itself. Both become adequate once
balloon pods absorb the initial spike. Karpenter still recovers headroom faster,
but neither autoscaler leaves users waiting minutes for the first relief.

Procedure (both phases):
  1. Set up the environment (capacity-filler OR balloon pods).
  2. Deploy cpu-burner at 1 replica. Wait Ready. Do NOT apply HPA.
  3. t_surge = apply HPA → this is the "spike arrives" moment.
  4. Poll until HPA desiredReplicas > 1 (metrics-server window, ~15-30 s).
  5. Track readiness curve: first Ready, 50%, all Ready; timed snapshots.
  6. Record CAS/Karpenter chain if new nodes were needed.
  7. Clean up between phases.

Milestones (prefixed phase1. and phase2.):
  - phase1.surge_trigger_to_hpa_decision
  - phase1.surge_trigger_to_first_pod_ready    ← first user served
  - phase1.surge_trigger_to_50pct_ready
  - phase1.surge_trigger_to_all_ready          ← degradation window closed

  - phase2.surge_trigger_to_hpa_decision
  - phase2.surge_trigger_to_preemption         ← balloon pods evicted instantly
  - phase2.surge_trigger_to_first_pod_ready
  - phase2.surge_trigger_to_50pct_ready
  - phase2.surge_trigger_to_all_ready

Comparison milestones (cross-phase deltas):
  - first_pod_improvement    (phase1.first_pod - phase2.first_pod)
  - full_recovery_improvement (phase1.all_ready - phase2.all_ready)

Cleanup: scale cpu-burner to 1, delete HPA, remove balloon/filler pods.

Usage:
  python3 scripts/run-test-12-sudden-spike.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--target-replicas 10] \\
      [--balloon-replicas 5] \\
      [--nodepool-name autonode-bench]
"""

from __future__ import annotations

import sys
import time
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

TEST_ID = "12-sudden-spike"
NAMESPACE = "benchmark"
MACHINE_API_NS = "openshift-machine-api"
CPU_BURNER = "cpu-burner"
CAPACITY_FILLER = "capacity-filler"
SURGE_OVERPROV = "surge-overprovisioner"
HPA_NAME = "cpu-burner-hpa"
LABEL_CPU_BURNER = "app=cpu-burner"
LABEL_SURGE_OVERPROV = "app=surge-overprovisioner"

_WORKLOADS = Path(__file__).parent.parent / "manifests" / "workloads"
_AUTOSCALING = Path(__file__).parent.parent / "manifests" / "autoscaling"
_OVERPROV = Path(__file__).parent.parent / "manifests" / "overprovisioning"

MANIFEST_CPU_BURNER = _WORKLOADS / "cpu-burner.yaml"
MANIFEST_CPU_BURNER_KARPENTER = _WORKLOADS / "cpu-burner-karpenter.yaml"
MANIFEST_FILLER = _WORKLOADS / "capacity-filler.yaml"
MANIFEST_FILLER_KARPENTER = _WORKLOADS / "capacity-filler-karpenter.yaml"
MANIFEST_HPA = _AUTOSCALING / "hpa.yaml"
MANIFEST_PRIORITY_CLASS = _OVERPROV / "priority-class.yaml"
MANIFEST_SURGE_OVERPROV = _OVERPROV / "surge-overprovisioner.yaml"
MANIFEST_SURGE_OVERPROV_KARPENTER = _OVERPROV / "surge-overprovisioner-karpenter.yaml"

_SAMPLE_S = 10


def _get_hpa_desired(hpa: dict) -> int:
    return hpa.get("status", {}).get("desiredReplicas", 0)


def _get_hpa_current_cpu(hpa: dict) -> int | None:
    for m in hpa.get("status", {}).get("currentMetrics") or []:
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
    target_replicas: int,
    t_surge: int,
    result: BenchmarkResult,
    kubeconfig: str | None,
    timeout_s: int,
    pfx: str,
) -> None:
    """
    Poll cpu-burner pod readiness every _SAMPLE_S seconds, recording partial
    readiness milestones namespaced under pfx (e.g. "phase1." or "phase2.").
    """
    deadline = time.monotonic() + timeout_s
    snapshots_recorded: set[int] = set()
    first_reached = half_reached = all_reached = False
    half_threshold = (target_replicas + 1) // 2

    while time.monotonic() < deadline:
        time.sleep(_SAMPLE_S)
        try:
            pods = oc_lib.get_pods(NAMESPACE, LABEL_CPU_BURNER, kubeconfig=kubeconfig)
        except oc_lib.OcError as exc:
            print(f"[12] WARNING: pod sample failed: {exc}", file=sys.stderr)
            continue

        ts = now_ms()
        elapsed_s = (ts - t_surge) // 1000
        ready = sum(1 for p in pods if _is_pod_ready(p))
        running = sum(1 for p in pods if p.get("status", {}).get("phase") == "Running")
        pending = sum(1 for p in pods if p.get("status", {}).get("phase") == "Pending")

        for snap_s in (60, 120, 180):
            if snap_s not in snapshots_recorded and elapsed_s >= snap_s:
                snapshots_recorded.add(snap_s)
                result.extra[f"{pfx}snapshot_{snap_s}s_ready"] = ready
                result.extra[f"{pfx}snapshot_{snap_s}s_pending"] = pending
                print(
                    f"[12] {pfx}T+{snap_s}s: {ready} Ready, {running} Running, {pending} Pending.",
                    file=sys.stderr,
                )

        if not first_reached and ready >= 1:
            first_reached = True
            result.milestone(f"{pfx}surge_trigger_to_first_pod_ready", t_surge, ts,
                             meta={"elapsed_s": str(elapsed_s)})
            print(f"[12] {pfx}First pod Ready at T+{elapsed_s}s.", file=sys.stderr)

        if not half_reached and ready >= half_threshold:
            half_reached = True
            result.milestone(f"{pfx}surge_trigger_to_50pct_ready", t_surge, ts,
                             meta={"ready": str(ready), "target": str(target_replicas)})
            print(f"[12] {pfx}50% Ready ({ready}/{target_replicas}) at T+{elapsed_s}s.", file=sys.stderr)

        if not all_reached and ready >= target_replicas:
            all_reached = True
            result.milestone(f"{pfx}surge_trigger_to_all_ready", t_surge, ts,
                             meta={"pod_count": str(ready), "elapsed_s": str(elapsed_s)})
            print(
                f"[12] {pfx}All {ready} pods Ready at T+{elapsed_s}s — "
                "degradation window closed.",
                file=sys.stderr,
            )
            return

    print(f"[12] WARNING: not all pods reached Ready within {timeout_s}s.", file=sys.stderr)


def _apply_hpa_and_wait_for_decision(
    pfx: str,
    t_surge: int,
    result: BenchmarkResult,
    args,
    kubeconfig: str | None,
) -> int:
    """
    Apply HPA and wait for it to issue a scale decision.
    Returns the desired replica count HPA chose.
    """
    def _hpa_fired() -> bool:
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        desired = _get_hpa_desired(hpa)
        cpu = _get_hpa_current_cpu(hpa)
        if cpu is not None:
            print(f"[12] HPA: CPU={cpu}% desired={desired}", file=sys.stderr)
        return desired > 1

    try:
        oc_lib.poll_until(_hpa_fired, timeout_s=600, interval_s=15, label="HPA fires")
        t_hpa_fired = now_ms()
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        desired = _get_hpa_desired(hpa)
        result.milestone(f"{pfx}surge_trigger_to_hpa_decision", t_surge, t_hpa_fired,
                         meta={"desired_replicas": str(desired)})
        print(
            f"[12] {pfx}HPA decided {desired} replicas "
            f"({elapsed_human(t_surge, t_hpa_fired)} from trigger).",
            file=sys.stderr,
        )
        return desired
    except oc_lib.PollTimeout:
        fatal(
            "HPA did not fire within 10m. Check metrics-server availability.",
            run_id=args.run_id, test_id=TEST_ID, result=result,
        )


def _run_phase(
    pfx: str,
    phase_label: str,
    setup_fn,
    target_replicas: int,
    args,
    result: BenchmarkResult,
    kubeconfig: str | None,
    is_karpenter: bool,
) -> int | None:
    """
    Run a single phase of T12.

    setup_fn() is called to prepare the environment (filler or balloon pods).
    Returns t_all_ready (ms) or None on timeout.
    """
    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    result.extra[f"{pfx}baseline_node_count"] = len(baseline_names)

    # ── Environment setup ─────────────────────────────────────────────────────
    setup_fn()

    # Capture NodeClaim baseline AFTER setup so "new NodeClaim" means one
    # provisioned for the spike — not a NodeClaim created by capacity-filler or
    # balloon pods during setup_fn().
    baseline_nc_count = (
        oc_lib.get_nodeclaim_count(nodepool_name=args.nodepool_name, kubeconfig=kubeconfig)
        if is_karpenter else 0
    )
    # Also refresh node baseline to include any nodes provisioned during setup.
    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)

    # ── Deploy cpu-burner at 1 replica (no HPA) ───────────────────────────────
    cpu_burner_manifest = MANIFEST_CPU_BURNER_KARPENTER if is_karpenter else MANIFEST_CPU_BURNER
    print(f"[12] {phase_label}: deploying cpu-burner at 1 replica (no HPA) ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(cpu_burner_manifest), kubeconfig=kubeconfig)
        oc_lib.scale_deployment(CPU_BURNER, 1, NAMESPACE, kubeconfig=kubeconfig)
        oc_lib.wait_for_deployment_ready(CPU_BURNER, NAMESPACE, timeout_s=360, kubeconfig=kubeconfig)
    print(f"[12] {phase_label}: cpu-burner at 1 replica, Ready.", file=sys.stderr)

    # ── Apply HPA = spike arrives ─────────────────────────────────────────────
    print(f"[12] {phase_label}: applying HPA — SPIKE ARRIVES ...", file=sys.stderr)
    t_surge = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_HPA), kubeconfig=kubeconfig)
    result.extra[f"{pfx}surge_trigger_ms"] = t_surge

    # ── Wait for HPA decision ─────────────────────────────────────────────────
    desired = _apply_hpa_and_wait_for_decision(pfx, t_surge, result, args, kubeconfig)
    result.extra[f"{pfx}hpa_desired_replicas"] = desired

    # ── Phase 2 only: watch for balloon pod preemption ────────────────────────
    if pfx == "phase2.":
        try:
            oc_lib.wait_for_event(
                NAMESPACE, ["Preempted", "Preempting", "Evicted"],
                timeout_s=120, interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_preempted = now_ms()
            result.milestone(f"{pfx}surge_trigger_to_preemption", t_surge, t_preempted)
            print(
                f"[12] {phase_label}: balloon pods preempted "
                f"({elapsed_human(t_surge, t_preempted)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print(
                f"[12] {phase_label}: no preemption events — balloon pods may not have been needed.",
                file=sys.stderr,
            )

    # ── Phase 1 only: watch for CAS/Karpenter chain ───────────────────────────
    if pfx == "phase1.":
        print(f"[12] {phase_label}: watching for FailedScheduling ...", file=sys.stderr)
        try:
            oc_lib.wait_for_event(NAMESPACE, "FailedScheduling", timeout_s=300, interval_s=10,
                                  kubeconfig=kubeconfig)
            t_pending = now_ms()
            result.milestone(f"{pfx}surge_trigger_to_pods_pending", t_surge, t_pending)
            print(f"[12] {phase_label}: FailedScheduling at T+{(t_pending-t_surge)//1000}s.", file=sys.stderr)
        except oc_lib.PollTimeout:
            print(f"[12] {phase_label}: no FailedScheduling — cluster had spare capacity.", file=sys.stderr)

        # Watch scheduler decision
        if is_karpenter:
            try:
                nc = oc_lib.wait_for_new_nodeclaim(
                    baseline_nc_count, nodepool_name=args.nodepool_name,
                    timeout_s=600, interval_s=10, kubeconfig=kubeconfig,
                )
                t_nc = now_ms()
                result.milestone(f"{pfx}pods_pending_to_nodeclaim", t_surge, t_nc,
                                 meta={"nodeclaim": nc.get("metadata", {}).get("name", "")})
                print(f"[12] {phase_label}: NodeClaim at T+{(t_nc-t_surge)//1000}s.", file=sys.stderr)
            except oc_lib.PollTimeout:
                pass
        else:
            try:
                cas_ev = oc_lib.wait_for_event(
                    MACHINE_API_NS, ["TriggeredScaleUp", "ScaledUpGroup"],
                    timeout_s=600, interval_s=15, kubeconfig=kubeconfig,
                )
                t_cas = now_ms()
                result.milestone(f"{pfx}pods_pending_to_cas_triggered", t_surge, t_cas,
                                 meta={"cas_event": cas_ev.get("reason", "")})
                print(f"[12] {phase_label}: CAS {cas_ev.get('reason')} at T+{(t_cas-t_surge)//1000}s.", file=sys.stderr)
            except oc_lib.PollTimeout:
                pass

        # Watch first new node
        try:
            new_node = oc_lib.wait_for_new_ready_node(
                baseline_names, timeout_s=args.timeout, interval_s=20, kubeconfig=kubeconfig,
            )
            t_node = now_ms()
            result.milestone(f"{pfx}surge_trigger_to_first_node_ready", t_surge, t_node,
                             meta={"new_node": new_node})
            print(f"[12] {phase_label}: first new node Ready at T+{(t_node-t_surge)//1000}s.", file=sys.stderr)
        except oc_lib.PollTimeout:
            print(f"[12] {phase_label}: WARNING — no new node Ready within timeout.", file=sys.stderr)

    # ── Track readiness curve ─────────────────────────────────────────────────
    remaining_s = max(300, args.timeout - ((now_ms() - t_surge) // 1000))
    _track_readiness_curve(desired, t_surge, result, kubeconfig, timeout_s=remaining_s, pfx=pfx)

    return t_surge


def _between_phases_cleanup(is_karpenter: bool, kubeconfig: str | None) -> None:
    """Reset cluster state between Phase 1 and Phase 2."""
    print("[12] Between-phase cleanup ...", file=sys.stderr)
    for dep, n in ((CPU_BURNER, 1), (CAPACITY_FILLER, 0)):
        try:
            oc_lib.scale_deployment(dep, n, NAMESPACE, kubeconfig=kubeconfig)
            print(f"[12] {dep} → {n} replicas.", file=sys.stderr)
        except Exception as exc:
            print(f"[12] warning {dep}: {exc}", file=sys.stderr)
    try:
        oc_lib.delete_object("hpa", HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        print("[12] HPA deleted.", file=sys.stderr)
    except Exception as exc:
        print(f"[12] warning HPA: {exc}", file=sys.stderr)
    # Allow cluster to settle
    print("[12] Waiting 60 s for cluster to settle before Phase 2 ...", file=sys.stderr)
    time.sleep(60)


def cleanup(is_karpenter: bool, kubeconfig: str | None) -> None:
    """Final cleanup after both phases."""
    import contextlib
    for dep, n in ((CPU_BURNER, 1), (CAPACITY_FILLER, 0), (SURGE_OVERPROV, 0)):
        with contextlib.suppress(Exception):
            oc_lib.scale_deployment(dep, n, NAMESPACE, kubeconfig=kubeconfig)
    with contextlib.suppress(Exception):
        oc_lib.delete_object("hpa", HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)


def main() -> None:
    parser = standard_args("Test 12 — Sudden spike: two-phase comparison benchmark.")
    parser.add_argument(
        "--target-replicas",
        type=int,
        default=10,
        help="Target cpu-burner replicas for the spike (default: 10). HPA will drive to this.",
    )
    parser.add_argument(
        "--balloon-replicas",
        type=int,
        default=5,
        help="Balloon pods for Phase 2 (default: 5). Should be target_replicas - 1.",
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help="Karpenter NodePool name (hcp-autonode only).",
    )
    parser.add_argument(
        "--filler-replicas",
        type=int,
        default=0,
        help=(
            "Override capacity-filler replica count for Phase 1. "
            "Default 0 = use the manifest default (5). "
            "Set higher (e.g. 40) when the cluster has more bench-standard nodes "
            "than the manifest was designed for, so the filler actually saturates capacity."
        ),
    )
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)
    is_karpenter = args.cluster_type == "hcp-autonode"
    filler_manifest = MANIFEST_FILLER_KARPENTER if is_karpenter else MANIFEST_FILLER
    overprov_manifest = MANIFEST_SURGE_OVERPROV_KARPENTER if is_karpenter else MANIFEST_SURGE_OVERPROV
    target_replicas: int = args.target_replicas
    balloon_replicas: int = args.balloon_replicas
    filler_replicas: int = args.filler_replicas

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["target_replicas"] = target_replicas
    result.extra["balloon_replicas"] = balloon_replicas
    result.extra["filler_replicas"] = filler_replicas if filler_replicas > 0 else "manifest_default"
    result.extra["scenario"] = "sudden_spike_two_phase"

    handle_sigint(
        lambda: cleanup(is_karpenter, kubeconfig),
        run_id=args.run_id,
        test_id=TEST_ID,
        result=result,
    )

    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # ── Pre-run cleanup — remove any HPA and scale workloads to neutral state ──
    # Previous benchmark tests (06-hpa, 08-hpa-triggers-cas, 10-autonode-scale)
    # may leave a cpu-burner-hpa active. With HPA present, scaling cpu-burner
    # to 1 is immediately reverted, which contaminates Phase 1 measurements.
    print("[12] Pre-run cleanup: removing any stale HPA and workloads ...", file=sys.stderr)
    if not args.dry_run:
        import contextlib
        oc_lib.delete_object("hpa", HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        for dep in (CPU_BURNER, CAPACITY_FILLER, SURGE_OVERPROV):
            with contextlib.suppress(Exception):
                oc_lib.scale_deployment(dep, 0, NAMESPACE, kubeconfig=kubeconfig)
    print("[12] Pre-run cleanup complete.", file=sys.stderr)

    # ── PHASE 1 — No preparation: straight CAS/Karpenter ─────────────────────
    print(
        "\n" + "="*60,
        "\n[12] PHASE 1 — No preparation (straight CAS/Karpenter)",
        "\n" + "="*60,
        file=sys.stderr,
    )

    def _setup_phase1() -> None:
        print("[12] Phase 1 setup: applying capacity-filler ...", file=sys.stderr)
        if not args.dry_run:
            oc_lib.apply_manifest(str(filler_manifest), kubeconfig=kubeconfig)
            if filler_replicas > 0:
                print(
                    f"[12] Scaling capacity-filler to {filler_replicas} replicas "
                    f"(--filler-replicas override) ...",
                    file=sys.stderr,
                )
                oc_lib.scale_deployment(
                    CAPACITY_FILLER, filler_replicas, NAMESPACE, kubeconfig=kubeconfig
                )
            oc_lib.wait_for_deployment_ready(
                CAPACITY_FILLER, NAMESPACE, timeout_s=600, kubeconfig=kubeconfig
            )
        print("[12] Capacity-filler Running — cluster at production capacity.", file=sys.stderr)

    _run_phase(
        pfx="phase1.",
        phase_label="Phase 1 (no-prep)",
        setup_fn=_setup_phase1,
        target_replicas=target_replicas,
        args=args,
        result=result,
        kubeconfig=kubeconfig,
        is_karpenter=is_karpenter,
    )

    # ── BETWEEN PHASES — Reset cluster ────────────────────────────────────────
    _between_phases_cleanup(is_karpenter, kubeconfig)

    # ── PHASE 2 — Balloon pods + HPA + CAS/Karpenter ─────────────────────────
    print(
        "\n" + "="*60,
        "\n[12] PHASE 2 — Balloon pods + HPA + CAS/Karpenter",
        "\n" + "="*60,
        file=sys.stderr,
    )

    def _setup_phase2() -> None:
        print(
            f"[12] Phase 2 setup: applying PriorityClass + {balloon_replicas} balloon pods ...",
            file=sys.stderr,
        )
        if not args.dry_run:
            oc_lib.apply_manifest(str(MANIFEST_PRIORITY_CLASS), kubeconfig=kubeconfig)
            oc_lib.apply_manifest(str(overprov_manifest), kubeconfig=kubeconfig)
            oc_lib.scale_deployment(
                SURGE_OVERPROV, balloon_replicas, NAMESPACE, kubeconfig=kubeconfig
            )
            oc_lib.wait_for_all_pods_running(
                NAMESPACE, LABEL_SURGE_OVERPROV,
                expected_count=balloon_replicas,
                timeout_s=600, interval_s=15,
                kubeconfig=kubeconfig,
            )
        print(f"[12] {balloon_replicas} balloon pods Running — headroom reserved.", file=sys.stderr)

    _run_phase(
        pfx="phase2.",
        phase_label="Phase 2 (balloon+HPA)",
        setup_fn=_setup_phase2,
        target_replicas=target_replicas,
        args=args,
        result=result,
        kubeconfig=kubeconfig,
        is_karpenter=is_karpenter,
    )

    # ── Cross-phase comparison milestones ─────────────────────────────────────
    # Emit explicit delta milestones so the comparison report can highlight them.
    p1_first = next(
        (m["elapsed_ms"] for m in result.milestones
         if m["label"].endswith("phase1.surge_trigger_to_first_pod_ready")),
        None,
    )
    p2_first = next(
        (m["elapsed_ms"] for m in result.milestones
         if m["label"].endswith("phase2.surge_trigger_to_first_pod_ready")),
        None,
    )
    p1_all = next(
        (m["elapsed_ms"] for m in result.milestones
         if m["label"].endswith("phase1.surge_trigger_to_all_ready")),
        None,
    )
    p2_all = next(
        (m["elapsed_ms"] for m in result.milestones
         if m["label"].endswith("phase2.surge_trigger_to_all_ready")),
        None,
    )

    if p1_first is not None and p2_first is not None:
        improvement_first_ms = p1_first - p2_first
        result.extra["first_pod_improvement_ms"] = improvement_first_ms
        result.extra["first_pod_improvement_pct"] = round(improvement_first_ms / p1_first * 100)
        print(
            f"\n[12] First-pod improvement: {improvement_first_ms//1000}s "
            f"({result.extra['first_pod_improvement_pct']}% faster with balloon pods).",
            file=sys.stderr,
        )

    if p1_all is not None and p2_all is not None:
        improvement_all_ms = p1_all - p2_all
        result.extra["full_recovery_improvement_ms"] = improvement_all_ms
        result.extra["full_recovery_improvement_pct"] = round(improvement_all_ms / p1_all * 100)
        print(
            f"[12] Full-recovery improvement: {improvement_all_ms//1000}s "
            f"({result.extra['full_recovery_improvement_pct']}% faster with balloon pods).",
            file=sys.stderr,
        )

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cleanup(is_karpenter, kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
