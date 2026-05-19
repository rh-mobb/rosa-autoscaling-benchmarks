#!/usr/bin/env python3
"""
scripts/run-test-13-parallel-nodes.py

Benchmark: Multi-Node Parallel Provisioning (Test 13)

Answers the key architectural question: when the cluster needs N new nodes,
does CAS or Karpenter provision them in parallel or one at a time?

CAS interacts with AWS Auto Scaling Groups via Machine API, which can batch
EC2 launch requests. Karpenter calls EC2 Fleet directly, often issuing all
launch requests in a single API call (sub-second "batch").

The "stagger" metric (t_last_node_ready − t_first_node_ready) captures this:
  - Near-zero stagger → effectively parallel provisioning
  - ~4-minute stagger → strictly serial (one node per CAS polling loop)

Procedure:
  1. Apply capacity-filler to saturate all existing nodes (zero headroom).
  2. Apply trigger workload (cas-trigger / karpenter-trigger, 100 replicas).
  3. Watch FailedScheduling → scheduler decision.
  4. Record each new node's Ready timestamp using watch_node_arrivals().
  5. Wait for all pods Running and Ready.
  6. Emit per-node timing and stagger milestones.

Milestones:
  - trigger_to_failed_scheduling
  - failed_scheduling_to_scheduler_triggered
  - trigger_to_node_1_ready / trigger_to_node_2_ready / trigger_to_node_3_ready
  - first_node_to_last_node_stagger         ← parallelism metric (key insight)
  - trigger_to_all_nodes_ready
  - trigger_to_all_pods_running
  - pods_running_to_pods_ready
  - trigger_to_all_pods_ready

Cleanup: scale capacity-filler to 0, scale trigger to 0.

Usage:
  python3 scripts/run-test-13-parallel-nodes.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--node-count 3] \\
      [--nodepool-name autonode-bench]
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
    elapsed_human,
    fatal,
    handle_sigint,
    now_ms,
    resolve_kubeconfig,
    standard_args,
    verify_oc_login,
)

TEST_ID = "13-parallel-nodes"
NAMESPACE = "benchmark"
NAMESPACE_TRIGGER = "benchmark"  # trigger workload lives in same ns
MACHINE_API_NS = "openshift-machine-api"
CAPACITY_FILLER = "capacity-filler"

_WORKLOADS = Path(__file__).parent.parent / "manifests" / "workloads"
_AUTOSCALING = Path(__file__).parent.parent / "manifests" / "autoscaling"

MANIFEST_FILLER = _WORKLOADS / "capacity-filler.yaml"
MANIFEST_FILLER_KARPENTER = _WORKLOADS / "capacity-filler-karpenter.yaml"
# Trigger workloads: 100 replicas × 500m CPU forces many nodes.
# Scale to 0 after test to release capacity.
MANIFEST_CAS_TRIGGER = _WORKLOADS / "cas-trigger.yaml"
MANIFEST_KARPENTER_TRIGGER = _WORKLOADS / "karpenter-trigger-100.yaml"
TRIGGER_NAME_CLASSIC = "cas-trigger"
TRIGGER_NAME_KARPENTER = "karpenter-trigger"
LABEL_CAS_TRIGGER = "app=cas-trigger"
LABEL_KARPENTER_TRIGGER = "app=karpenter-trigger"


def cleanup(trigger_name: str, kubeconfig: str | None) -> None:
    for dep, n in ((CAPACITY_FILLER, 0), (trigger_name, 0)):
        try:
            oc_lib.scale_deployment(dep, n, NAMESPACE, kubeconfig=kubeconfig)
            print(f"[cleanup] {dep} → {n} replicas.", file=sys.stderr)
        except Exception as exc:
            print(f"[cleanup] warning: {dep}: {exc}", file=sys.stderr)


def main() -> None:
    parser = standard_args("Test 13 — Multi-node parallel provisioning benchmark.")
    parser.add_argument(
        "--node-count",
        type=int,
        default=3,
        help="Number of new nodes to watch for (default: 3).",
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help="Karpenter NodePool name to watch for NodeClaims (hcp-autonode only).",
    )
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)
    node_count: int = args.node_count
    is_karpenter = args.cluster_type == "hcp-autonode"

    trigger_manifest = MANIFEST_KARPENTER_TRIGGER if is_karpenter else MANIFEST_CAS_TRIGGER
    trigger_name = TRIGGER_NAME_KARPENTER if is_karpenter else TRIGGER_NAME_CLASSIC
    trigger_label = LABEL_KARPENTER_TRIGGER if is_karpenter else LABEL_CAS_TRIGGER
    filler_manifest = MANIFEST_FILLER_KARPENTER if is_karpenter else MANIFEST_FILLER

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["node_count_target"] = node_count
    result.extra["scheduler"] = "karpenter" if is_karpenter else "cas"

    handle_sigint(
        lambda: cleanup(trigger_name, kubeconfig),
        run_id=args.run_id,
        test_id=TEST_ID,
        result=result,
    )

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # ── Step 1 — Baseline ─────────────────────────────────────────────────────
    print("[13] Recording baseline ...", file=sys.stderr)
    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    baseline_nc_count = (
        oc_lib.get_nodeclaim_count(nodepool_name=args.nodepool_name, kubeconfig=kubeconfig)
        if is_karpenter else 0
    )
    print(
        f"[13] Baseline: {len(baseline_names)} Ready nodes"
        + (f", {baseline_nc_count} NodeClaims" if is_karpenter else ""),
        file=sys.stderr,
    )
    result.extra["baseline_node_count"] = len(baseline_names)

    # ── Step 2 — Saturate cluster ─────────────────────────────────────────────
    print(f"[13] Applying {filler_manifest.name} to saturate all existing nodes ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(filler_manifest), kubeconfig=kubeconfig)
        oc_lib.wait_for_deployment_ready(
            CAPACITY_FILLER, NAMESPACE, timeout_s=300, kubeconfig=kubeconfig
        )
    print("[13] Capacity-filler Running — zero headroom on existing nodes.", file=sys.stderr)

    # ── Step 3 — Apply trigger workload ───────────────────────────────────────
    print(
        f"[13] Applying {trigger_manifest.name} (100 replicas × 500m CPU) to force "
        f"{node_count}+ new nodes ...",
        file=sys.stderr,
    )
    t_trigger = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(trigger_manifest), kubeconfig=kubeconfig)
    result.extra["trigger_ms"] = t_trigger

    # ── Step 4 — Watch FailedScheduling ──────────────────────────────────────
    print("[13] Waiting for FailedScheduling ...", file=sys.stderr)
    try:
        oc_lib.wait_for_event(
            NAMESPACE,
            "FailedScheduling",
            timeout_s=300,
            interval_s=10,
            kubeconfig=kubeconfig,
        )
        t_failed_scheduling = now_ms()
        result.milestone("trigger_to_failed_scheduling", t_trigger, t_failed_scheduling)
        print(
            f"[13] FailedScheduling — trigger pods queued "
            f"({elapsed_human(t_trigger, t_failed_scheduling)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print("[13] WARNING: No FailedScheduling observed.", file=sys.stderr)
        t_failed_scheduling = now_ms()

    # ── Step 5 — Watch scheduler decision ────────────────────────────────────
    t_scheduler_triggered = t_failed_scheduling
    if is_karpenter:
        print("[13] Waiting for first Karpenter NodeClaim ...", file=sys.stderr)
        try:
            nc = oc_lib.wait_for_new_nodeclaim(
                baseline_nc_count,
                nodepool_name=args.nodepool_name,
                timeout_s=600,
                interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_scheduler_triggered = now_ms()
            nc_name = nc.get("metadata", {}).get("name", "")
            result.milestone(
                "failed_scheduling_to_scheduler_triggered",
                t_failed_scheduling,
                t_scheduler_triggered,
                meta={"first_nodeclaim": nc_name, "scheduler": "karpenter"},
            )
            print(
                f"[13] First Karpenter NodeClaim: {nc_name} "
                f"({elapsed_human(t_failed_scheduling, t_scheduler_triggered)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[13] WARNING: no NodeClaim observed; continuing ...", file=sys.stderr)
    else:
        print("[13] Waiting for CAS scale-up decision ...", file=sys.stderr)
        try:
            cas_event = oc_lib.wait_for_event(
                MACHINE_API_NS,
                ["TriggeredScaleUp", "ScaledUpGroup"],
                timeout_s=600,
                interval_s=15,
                kubeconfig=kubeconfig,
            )
            t_scheduler_triggered = now_ms()
            result.milestone(
                "failed_scheduling_to_scheduler_triggered",
                t_failed_scheduling,
                t_scheduler_triggered,
                meta={
                    "cas_event": cas_event.get("reason", ""),
                    "cas_message": cas_event.get("message", "")[:200],
                    "scheduler": "cas",
                },
            )
            print(
                f"[13] CAS {cas_event.get('reason')} "
                f"({elapsed_human(t_failed_scheduling, t_scheduler_triggered)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[13] WARNING: no CAS event observed; continuing ...", file=sys.stderr)

    # ── Step 6 — Watch N new nodes, recording each arrival independently ──────
    # This is the core measurement: did nodes arrive all at once or one by one?
    print(
        f"[13] Watching for {node_count} new Ready nodes (recording each arrival) ...",
        file=sys.stderr,
    )
    arrivals: list[tuple[str, int]] = []

    def _on_arrival(name: str, ts_ms: int) -> None:
        idx = len(arrivals) + 1  # 1-based before appending
        result.milestone(
            f"trigger_to_node_{idx}_ready",
            t_trigger,
            ts_ms,
            meta={"node_name": name, "node_index": str(idx)},
        )
        arrivals.append((name, ts_ms))
        print(
            f"[13] Node {idx}/{node_count} Ready: {name} "
            f"({elapsed_human(t_trigger, ts_ms)} from trigger).",
            file=sys.stderr,
        )

    try:
        arrivals = oc_lib.watch_node_arrivals(
            baseline_names,
            node_count,
            timeout_s=args.timeout,
            interval_s=15,
            kubeconfig=kubeconfig,
            on_arrival=_on_arrival,
        )
    except oc_lib.PollTimeout:
        fatal(
            f"Timed out waiting for {node_count} new Ready nodes "
            f"(only {len(arrivals)} arrived).",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Stagger = last node Ready − first node Ready
    t_first_node = arrivals[0][1]
    t_last_node = arrivals[-1][1]
    result.milestone(
        "trigger_to_all_nodes_ready",
        t_trigger,
        t_last_node,
        meta={"nodes_ready": str(len(arrivals))},
    )
    result.milestone(
        "first_node_to_last_node_stagger",
        t_first_node,
        t_last_node,
        meta={
            "node_count": str(len(arrivals)),
            "interpretation": (
                "near-zero = parallel provisioning; "
                ">180s = serial provisioning"
            ),
        },
    )
    stagger_s = (t_last_node - t_first_node) // 1000
    print(
        f"[13] All {node_count} nodes Ready. "
        f"Stagger (last − first): {stagger_s}s "
        f"({'parallel' if stagger_s < 60 else 'serial-ish'} provisioning).",
        file=sys.stderr,
    )
    result.extra["stagger_s"] = stagger_s
    result.extra["node_arrivals"] = [
        {"name": n, "elapsed_s": (ts - t_trigger) // 1000}
        for n, ts in arrivals
    ]

    # ── Step 7 — Wait for all pods Running ────────────────────────────────────
    print("[13] Waiting for trigger pods to be Running ...", file=sys.stderr)
    try:
        running_pods = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            trigger_label,
            timeout_s=600,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_all_running = now_ms()
        result.milestone(
            "trigger_to_all_pods_running",
            t_trigger,
            t_all_running,
            meta={"running_pods": str(len(running_pods))},
        )
        print(
            f"[13] {len(running_pods)} trigger pods Running "
            f"({elapsed_human(t_trigger, t_all_running)} from trigger).",
            file=sys.stderr,
        )

        # Step 7b — Wait for pods Ready
        print("[13] Waiting for trigger pods to be Ready ...", file=sys.stderr)
        try:
            ready_pods = oc_lib.wait_for_all_pods_ready(
                NAMESPACE,
                trigger_label,
                timeout_s=300,
                interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_all_ready = now_ms()
            result.milestone(
                "pods_running_to_pods_ready",
                t_all_running,
                t_all_ready,
                meta={"ready_pods": str(len(ready_pods))},
            )
            result.milestone(
                "trigger_to_all_pods_ready",
                t_trigger,
                t_all_ready,
                meta={"pod_count": str(len(ready_pods))},
            )
            print(
                f"[13] {len(ready_pods)} trigger pods Ready "
                f"({elapsed_human(t_trigger, t_all_ready)} from trigger).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[13] WARNING: not all pods reached Ready within timeout.", file=sys.stderr)
    except oc_lib.PollTimeout:
        print("[13] WARNING: not all pods reached Running within timeout.", file=sys.stderr)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cleanup(trigger_name, kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
