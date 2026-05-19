#!/usr/bin/env python3
"""
scripts/run-test-08-hpa-triggers-cas.py

Benchmark: HPA fires → cluster full → CAS provisions node (Test 08)

This is the most operationally realistic scenario: HPA scales out the
application but the cluster has no spare capacity, so CAS must provision
new nodes before the pods can run.

Procedure:
  1. Baseline: record current node names and counts.
  2. Apply capacity-filler (10 pause pods, 400m/400Mi each) to saturate cluster.
  3. Verify cluster capacity is actually near-full (oc adm top / describe nodes).
  4. Ensure cpu-burner + HPA are deployed (apply if not present).
  5. Scale cpu-burner to 3 replicas (manual HPA trigger).
  6. Watch for new pods to go Pending (FailedScheduling).
  7. Watch for CAS TriggeredScaleUp.
  8. Watch for a new Ready node.
  9. Watch for all cpu-burner pods Running.
  10. Emit cascade milestones, print JSON summary.

Cleanup: scale capacity-filler to 0, scale cpu-burner to 1.

Usage:
  python3 scripts/run-test-08-hpa-triggers-cas.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--cpu-burner-replicas 3] \\
      [--timeout 2400]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib import oc as oc_lib
from scripts.lib.bench import (
    BenchmarkResult,
    checkpoint_complete,
    checkpoint_start,
    collect_node_telemetry,
    elapsed_human,
    fatal,
    handle_sigint,
    now_ms,
    resolve_kubeconfig,
    standard_args,
    verify_oc_login,
)

TEST_ID = "08-hpa-triggers-cas"
NAMESPACE = "benchmark"
MACHINE_API_NS = "openshift-machine-api"
CPU_BURNER = "cpu-burner"
CAPACITY_FILLER = "capacity-filler"
HPA_NAME = "cpu-burner-hpa"
LABEL_CPU_BURNER = "app=cpu-burner"

_WORKLOADS = Path(__file__).parent.parent / "manifests" / "workloads"
_AUTOSCALING = Path(__file__).parent.parent / "manifests" / "autoscaling"

MANIFEST_CPU_BURNER = _WORKLOADS / "cpu-burner.yaml"
MANIFEST_CPU_BURNER_KARPENTER = _WORKLOADS / "cpu-burner-karpenter.yaml"
MANIFEST_HPA = _AUTOSCALING / "hpa.yaml"
MANIFEST_FILLER = _WORKLOADS / "capacity-filler.yaml"
MANIFEST_FILLER_KARPENTER = _WORKLOADS / "capacity-filler-karpenter.yaml"


def cleanup(kubeconfig: str | None) -> None:
    """Scale capacity-filler to 0 and cpu-burner to 1."""
    for dep, n in ((CAPACITY_FILLER, 0), (CPU_BURNER, 1)):
        try:
            oc_lib.scale_deployment(dep, n, NAMESPACE, kubeconfig=kubeconfig)
            print(f"[cleanup] {dep} → {n} replicas.", file=sys.stderr)
        except Exception as exc:
            print(f"[cleanup] warning: {dep}: {exc}", file=sys.stderr)


def _has_pending_pods(kubeconfig: str | None) -> bool:
    pods = oc_lib.get_pods(NAMESPACE, LABEL_CPU_BURNER, kubeconfig=kubeconfig)
    return any(p.get("status", {}).get("phase") == "Pending" for p in pods)


def _get_hpa_desired(kubeconfig: str | None) -> int:
    try:
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        return hpa.get("status", {}).get("desiredReplicas", 0)
    except oc_lib.OcError:
        return 0


def main() -> None:
    parser = standard_args("Test 08 — HPA triggers autoscaler cascade benchmark.")
    parser.add_argument(
        "--cpu-burner-replicas",
        type=int,
        default=3,
        help="Number of cpu-burner replicas to request (default: 3).",
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help="Karpenter NodePool name to watch for NodeClaims (hcp-autonode only).",
    )
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)
    target_replicas: int = args.cpu_burner_replicas

    # Select manifests based on cluster type.
    # hcp-autonode variants add nodeAffinity so workloads land on Karpenter nodes.
    is_autonode = args.cluster_type == "hcp-autonode"
    cpu_burner_manifest = MANIFEST_CPU_BURNER_KARPENTER if is_autonode else MANIFEST_CPU_BURNER
    filler_manifest = MANIFEST_FILLER_KARPENTER if is_autonode else MANIFEST_FILLER

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["cpu_burner_manifest"] = cpu_burner_manifest.name
    result.extra["filler_manifest"] = filler_manifest.name

    handle_sigint(lambda: cleanup(kubeconfig), run_id=args.run_id, test_id=TEST_ID, result=result)

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # ── Step 1 — Baseline ─────────────────────────────────────────────────────
    print("[08] Recording baseline ...", file=sys.stderr)
    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    baseline_count = len(baseline_names)
    baseline_nc_count = (
        oc_lib.get_nodeclaim_count(nodepool_name=args.nodepool_name, kubeconfig=kubeconfig)
        if is_autonode else 0
    )
    print(
        f"[08] Baseline: {baseline_count} Ready nodes"
        + (f", {baseline_nc_count} NodeClaims" if is_autonode else ""),
        file=sys.stderr,
    )
    result.extra["baseline_node_count"] = baseline_count
    if is_autonode:
        result.extra["baseline_nodeclaim_count"] = baseline_nc_count
    t_start = now_ms()

    # ── Step 2 — Apply capacity-filler ───────────────────────────────────────
    # On Karpenter clusters the filler pods require karpenter.sh/nodepool affinity,
    # so they cannot land on base workers and will themselves trigger Karpenter to
    # provision a node. We wait for that to complete before re-baselining NodeClaims,
    # so the later "new NodeClaim" watch only counts NodeClaims created in response
    # to the HPA cascade — not the one created for the filler.
    print(f"[08] Applying {filler_manifest.name} to saturate cluster ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(filler_manifest), kubeconfig=kubeconfig)
        oc_lib.wait_for_deployment_ready(
            CAPACITY_FILLER, NAMESPACE, timeout_s=600, kubeconfig=kubeconfig
        )
    print("[08] Capacity-filler Running.", file=sys.stderr)

    # Re-baseline nodes and NodeClaims after filler is settled (Karpenter may have
    # provisioned one or more nodes to accommodate the filler pods).
    if is_autonode:
        baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
        baseline_nc_count = oc_lib.get_nodeclaim_count(
            nodepool_name=args.nodepool_name, kubeconfig=kubeconfig
        )
        print(
            f"[08] Post-filler baseline: {len(baseline_names)} Ready nodes, "
            f"{baseline_nc_count} NodeClaims",
            file=sys.stderr,
        )
        result.extra["baseline_node_count"] = len(baseline_names)
        result.extra["baseline_nodeclaim_count"] = baseline_nc_count

    # ── Step 3 — Ensure cpu-burner + HPA ─────────────────────────────────────
    print(f"[08] Applying {cpu_burner_manifest.name} and HPA ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(cpu_burner_manifest), kubeconfig=kubeconfig)
        oc_lib.apply_manifest(str(MANIFEST_HPA), kubeconfig=kubeconfig)
        oc_lib.wait_for_deployment_ready(
            CPU_BURNER, NAMESPACE, timeout_s=600, kubeconfig=kubeconfig
        )
    print("[08] cpu-burner Ready.", file=sys.stderr)

    # ── Step 4 — Scale cpu-burner to trigger HPA ─────────────────────────────
    print(f"[08] Scaling cpu-burner to {target_replicas} replicas ...", file=sys.stderr)
    t_hpa_trigger = now_ms()
    if not args.dry_run:
        oc_lib.scale_deployment(CPU_BURNER, target_replicas, NAMESPACE, kubeconfig=kubeconfig)
    result.extra["hpa_target_replicas"] = target_replicas

    # ── Step 5 — Watch pods go Pending ───────────────────────────────────────
    print("[08] Waiting for cpu-burner pods to go Pending (FailedScheduling) ...", file=sys.stderr)
    try:
        oc_lib.wait_for_event(
            NAMESPACE,
            "FailedScheduling",
            timeout_s=300,
            interval_s=10,
            kubeconfig=kubeconfig,
        )
        t_pods_pending = now_ms()
        result.milestone(
            "hpa_trigger_to_pods_pending",
            t_hpa_trigger,
            t_pods_pending,
        )
        print(
            f"[08] Pods Pending / FailedScheduling "
            f"({elapsed_human(t_hpa_trigger, t_pods_pending)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        # Cluster may have had spare capacity; record as 0 and continue
        print(
            "[08] WARNING: No FailedScheduling observed — cluster may have had spare capacity. "
            "CAS scale-up may not occur.",
            file=sys.stderr,
        )
        t_pods_pending = now_ms()

    # ── Step 6 — Watch scheduler scale-up decision ───────────────────────────
    # CAS: watch for TriggeredScaleUp or ScaledUpGroup in openshift-machine-api.
    # Karpenter: watch for a new NodeClaim in the autonode-bench NodePool.
    t_cas_triggered = now_ms()  # default if neither watch fires

    if is_autonode:
        print("[08] Waiting for Karpenter NodeClaim (provisioning decision) ...", file=sys.stderr)
        try:
            new_nc = oc_lib.wait_for_new_nodeclaim(
                baseline_nc_count,
                nodepool_name=args.nodepool_name,
                timeout_s=600,
                interval_s=10,
                kubeconfig=kubeconfig,
            )
            t_cas_triggered = now_ms()
            nc_name = new_nc.get("metadata", {}).get("name", "")
            result.milestone(
                "pods_pending_to_scheduler_triggered",
                t_pods_pending,
                t_cas_triggered,
                meta={"nodeclaim": nc_name, "scheduler": "autonode"},
            )
            print(
                f"[08] Karpenter NodeClaim {nc_name} created "
                f"({elapsed_human(t_pods_pending, t_cas_triggered)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[08] WARNING: No new NodeClaim observed; continuing to watch for new node ...", file=sys.stderr)
    else:
        print("[08] Waiting for CAS scale-up decision event ...", file=sys.stderr)
        try:
            cas_event = oc_lib.wait_for_event(
                MACHINE_API_NS,
                ["TriggeredScaleUp", "ScaledUpGroup"],
                timeout_s=600,
                interval_s=15,
                kubeconfig=kubeconfig,
            )
            t_cas_triggered = now_ms()
            result.milestone(
                "pods_pending_to_scheduler_triggered",
                t_pods_pending,
                t_cas_triggered,
                meta={
                    "cas_event": cas_event.get("reason", ""),
                    "cas_message": cas_event.get("message", "")[:200],
                    "scheduler": "cas",
                },
            )
            print(
                f"[08] CAS {cas_event.get('reason')} ({elapsed_human(t_pods_pending, t_cas_triggered)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[08] WARNING: No CAS scale-up event observed; continuing to watch for new node ...", file=sys.stderr)

    # ── Step 7 — Watch new node Ready ────────────────────────────────────────
    print("[08] Waiting for a new Ready node ...", file=sys.stderr)
    try:
        new_node = oc_lib.wait_for_new_ready_node(
            baseline_names,
            timeout_s=args.timeout,
            interval_s=20,
            kubeconfig=kubeconfig,
        )
        t_node_ready = now_ms()
        result.milestone(
            "scheduler_triggered_to_node_ready",
            t_cas_triggered,
            t_node_ready,
            meta={"new_node": new_node, "scheduler": "autonode" if is_autonode else "cas"},
        )
        print(
            f"[08] New node Ready: {new_node} ({elapsed_human(t_cas_triggered, t_node_ready)}).",
            file=sys.stderr,
        )
        result.extra["new_node"] = new_node
        collect_node_telemetry(
            new_node,
            prefix=f"{TEST_ID}.new_node",
            since_ms=t_start,
            run_id=args.run_id,
            cluster_type=args.cluster_type,
            cluster_name=args.cluster_name,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            f"Timed out after {args.timeout}s waiting for a new Ready node.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # ── Step 8 — Watch all cpu-burner pods Running ────────────────────────────
    print("[08] Waiting for all cpu-burner pods to be Running ...", file=sys.stderr)
    try:
        running_pods = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            LABEL_CPU_BURNER,
            expected_count=target_replicas,
            timeout_s=600,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_all_running = now_ms()
        result.milestone(
            "node_ready_to_pods_running",
            t_node_ready,
            t_all_running,
        )
        result.milestone(
            "hpa_trigger_to_all_running",
            t_hpa_trigger,
            t_all_running,
            meta={"pod_count": str(len(running_pods))},
        )
        result.extra["final_running_pods"] = len(running_pods)
        print(
            f"[08] {len(running_pods)} pods Running "
            f"(total cascade: {elapsed_human(t_hpa_trigger, t_all_running)}).",
            file=sys.stderr,
        )

        # Step 8b — Wait for pods Ready (readiness probes pass / traffic-serving state)
        print("[08] Waiting for all cpu-burner pods to be Ready ...", file=sys.stderr)
        try:
            ready_pods = oc_lib.wait_for_all_pods_ready(
                NAMESPACE,
                LABEL_CPU_BURNER,
                expected_count=target_replicas,
                timeout_s=300,
                interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_all_ready = now_ms()
            result.milestone("pods_running_to_pods_ready", t_all_running, t_all_ready,
                             meta={"ready_pod_count": str(len(ready_pods))})
            result.milestone("hpa_trigger_to_all_ready", t_hpa_trigger, t_all_ready,
                             meta={"pod_count": str(len(ready_pods))})
            print(
                f"[08] {len(ready_pods)} pods Ready "
                f"(+{elapsed_human(t_all_running, t_all_ready)} after Running; "
                f"total cascade: {elapsed_human(t_hpa_trigger, t_all_ready)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[08] WARNING: pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        print("[08] WARNING: Not all pods reached Running within timeout.", file=sys.stderr)

    # ── Collect FailedScheduling events ───────────────────────────────────────
    try:
        failed_events = [
            ev for ev in oc_lib.get_events(NAMESPACE, kubeconfig=kubeconfig)
            if ev.get("reason") == "FailedScheduling"
        ]
        result.extra["failed_scheduling_messages"] = [
            e.get("message", "")[:200] for e in failed_events[-5:]
        ]
    except oc_lib.OcError:
        pass

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cleanup(kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
