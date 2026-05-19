#!/usr/bin/env python3
"""
scripts/run-test-03-autoscale-up.py

Benchmark: Scale-up trigger — CAS (Classic/HCP) or Karpenter/AutoNode (hcp-autonode) (Test 03)

Procedure (CAS — classic|hcp):
  1. Record baseline node count and names.
  2. Apply manifests/workloads/cas-trigger.yaml (20 pause pods, 500m/512Mi each).
  3. Poll benchmark namespace events for FailedScheduling.
  4. Poll openshift-machine-api events for TriggeredScaleUp / ScaledUpGroup.
  5. Poll for a new Ready node beyond the baseline set.
  6. Poll until all cas-trigger pods are Running.
  7. Emit milestone timings, print JSON summary.

Procedure (AutoNode — hcp-autonode):
  Steps 1–3 are the same, using karpenter-trigger.yaml (same resource requests,
  nodeAffinity pins pods to the autonode-bench NodePool).
  4. Watch for a new NodeClaim in the autonode-bench NodePool (Karpenter decision).
  5–7 are the same.
  Milestones use the generic scheduler_triggered names so they align with
  test 08 and test 10 for cross-autoscaler comparison.

Cleanup (on success): scale trigger deployment to 0 (test 04 deletes it).
Cleanup (on SIGINT or failure): scale trigger deployment to 0 to avoid leaving
resources that would interfere with other tests.

Usage:
  python3 scripts/run-test-03-autoscale-up.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--nodepool-name autonode-bench]  # hcp-autonode only
      [--timeout 1800]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from scripts/lib/ when run directly
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

TEST_ID = "03-autoscale-up"
MANIFEST_CAS = Path(__file__).parent.parent / "manifests" / "workloads" / "cas-trigger.yaml"
MANIFEST_AUTONODE = Path(__file__).parent.parent / "manifests" / "workloads" / "karpenter-trigger.yaml"
NAMESPACE = "benchmark"
MACHINE_API_NS = "openshift-machine-api"
DEPLOYMENT_CAS = "cas-trigger"
DEPLOYMENT_AUTONODE = "karpenter-trigger"
LABEL_SELECTOR_CAS = "app=cas-trigger"
LABEL_SELECTOR_AUTONODE = "app=karpenter-trigger"


def cleanup(deployment: str, kubeconfig: str | None) -> None:
    """Scale the trigger deployment to 0. Idempotent — safe to call multiple times."""
    try:
        oc_lib.scale_deployment(deployment, 0, NAMESPACE, kubeconfig=kubeconfig)
        print(f"[cleanup] {deployment} scaled to 0.", file=sys.stderr)
    except Exception as exc:
        print(f"[cleanup] warning: {exc}", file=sys.stderr)


def main() -> None:
    parser = standard_args(
        "Test 03 — Scale-up benchmark (CAS for classic/hcp, Karpenter/AutoNode for hcp-autonode)."
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help="Karpenter NodePool name to watch for NodeClaims (hcp-autonode only).",
    )
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)

    is_autonode = args.cluster_type == "hcp-autonode"
    manifest = MANIFEST_AUTONODE if is_autonode else MANIFEST_CAS
    deployment = DEPLOYMENT_AUTONODE if is_autonode else DEPLOYMENT_CAS
    label_selector = LABEL_SELECTOR_AUTONODE if is_autonode else LABEL_SELECTOR_CAS

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )

    # Register SIGINT cleanup before touching the cluster
    handle_sigint(lambda: cleanup(deployment, kubeconfig), run_id=args.run_id, test_id=TEST_ID, result=result)

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # ── Step 1 — Baseline ─────────────────────────────────────────────────────
    print("[03] Recording baseline node state ...", file=sys.stderr)
    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    baseline_count = len(baseline_names)
    print(f"[03] Baseline: {baseline_count} Ready nodes: {sorted(baseline_names)}", file=sys.stderr)
    if is_autonode:
        baseline_nc_count = oc_lib.get_nodeclaim_count(
            nodepool_name=args.nodepool_name, kubeconfig=kubeconfig
        )
        print(f"[03] Baseline NodeClaims: {baseline_nc_count}", file=sys.stderr)
        result.extra["baseline_nodeclaim_count"] = baseline_nc_count

    # ── Step 2 — Apply workload ───────────────────────────────────────────────
    print(f"[03] Applying {manifest.name} ...", file=sys.stderr)
    t_workload_applied = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(manifest), kubeconfig=kubeconfig)
    print(f"[03] {deployment} applied at {t_workload_applied}.", file=sys.stderr)

    # ── Step 3 — Wait for FailedScheduling ───────────────────────────────────
    print("[03] Waiting for FailedScheduling event ...", file=sys.stderr)
    try:
        oc_lib.wait_for_event(
            NAMESPACE,
            "FailedScheduling",
            timeout_s=300,
            interval_s=10,
            kubeconfig=kubeconfig,
        )
        t_failed_scheduling = now_ms()
        result.milestone(
            "workload_applied_to_failed_scheduling",
            t_workload_applied,
            t_failed_scheduling,
        )
        print(f"[03] FailedScheduling observed ({elapsed_human(t_workload_applied, t_failed_scheduling)}).", file=sys.stderr)
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for FailedScheduling. "
            "Check that trigger replicas exceed available node capacity.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # ── Step 4 — Wait for scheduler decision ─────────────────────────────────
    # CAS:      TriggeredScaleUp or ScaledUpGroup in openshift-machine-api.
    # AutoNode: A new NodeClaim appears in the autonode-bench NodePool.
    t_scheduler_triggered = now_ms()  # default if the watch times out

    if is_autonode:
        print("[03] Waiting for Karpenter NodeClaim (provisioning decision) ...", file=sys.stderr)
        try:
            new_nc = oc_lib.wait_for_new_nodeclaim(
                baseline_nc_count,
                nodepool_name=args.nodepool_name,
                timeout_s=600,
                interval_s=10,
                kubeconfig=kubeconfig,
            )
            t_scheduler_triggered = now_ms()
            nc_name = new_nc.get("metadata", {}).get("name", "")
            result.milestone(
                "failed_scheduling_to_scheduler_triggered",
                t_failed_scheduling,
                t_scheduler_triggered,
                meta={"nodeclaim": nc_name, "scheduler": "autonode"},
            )
            print(
                f"[03] Karpenter NodeClaim {nc_name} created "
                f"({elapsed_human(t_failed_scheduling, t_scheduler_triggered)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print(
                "[03] WARNING: No new NodeClaim observed within 600s; "
                "continuing to watch for new node ...",
                file=sys.stderr,
            )
    else:
        # CAS: accept either event reason depending on OCP/CAS version.
        print("[03] Waiting for CAS scale-up decision event ...", file=sys.stderr)
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
                "failed_scheduling_to_cas_triggered",
                t_failed_scheduling,
                t_scheduler_triggered,
                meta={
                    "cas_event": cas_event.get("reason", ""),
                    "cas_message": cas_event.get("message", "")[:200],
                    "scheduler": "cas",
                },
            )
            print(
                f"[03] CAS {cas_event.get('reason')} observed "
                f"({elapsed_human(t_failed_scheduling, t_scheduler_triggered)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            # CAS events may appear in a different namespace depending on version;
            # record what we have and continue — node polling still captures timing.
            print(
                "[03] WARNING: No CAS scale-up event found in openshift-machine-api "
                "within 600s; continuing to watch for new node ...",
                file=sys.stderr,
            )

    # ── Step 5 — Wait for new node Ready ─────────────────────────────────────
    print("[03] Waiting for a new Ready node ...", file=sys.stderr)
    try:
        new_node = oc_lib.wait_for_new_ready_node(
            baseline_names,
            timeout_s=args.timeout,
            interval_s=20,
            kubeconfig=kubeconfig,
        )
        t_node_ready = now_ms()
        # AutoNode uses a generic name for cross-autoscaler comparison; CAS keeps its
        # historical name for backward compatibility with existing event data.
        node_milestone = "scheduler_triggered_to_node_ready" if is_autonode else "cas_triggered_to_node_ready"
        result.milestone(
            node_milestone,
            t_scheduler_triggered,
            t_node_ready,
            meta={
                "new_node": new_node,
                "scheduler": "autonode" if is_autonode else "cas",
            },
        )
        print(
            f"[03] New node Ready: {new_node} ({elapsed_human(t_scheduler_triggered, t_node_ready)}).",
            file=sys.stderr,
        )
        collect_node_telemetry(
            new_node,
            prefix=f"{TEST_ID}.new_node",
            since_ms=t_workload_applied,
            run_id=args.run_id,
            cluster_type=args.cluster_type,
            cluster_name=args.cluster_name,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            f"Timed out after {args.timeout}s waiting for a new Ready node. "
            "Check that machine pool autoscaling is enabled, quota, and instance limits.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # ── Step 6 — Wait for all pods Running ───────────────────────────────────
    print(f"[03] Waiting for all {deployment} pods to be Running ...", file=sys.stderr)
    try:
        running_pods = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            label_selector,
            timeout_s=600,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_pods_running = now_ms()
        result.milestone(
            "node_ready_to_pods_running",
            t_node_ready,
            t_pods_running,
            meta={"running_pod_count": str(len(running_pods))},
        )
        result.milestone(
            "workload_applied_to_pods_running",
            t_workload_applied,
            t_pods_running,
        )
        print(
            f"[03] {len(running_pods)} {deployment} pods Running "
            f"(total from apply: {elapsed_human(t_workload_applied, t_pods_running)}).",
            file=sys.stderr,
        )

        # Step 6b — Wait for pods Ready (readiness probes pass / traffic-serving state)
        print(f"[03] Waiting for all {deployment} pods to be Ready ...", file=sys.stderr)
        try:
            ready_pods = oc_lib.wait_for_all_pods_ready(
                NAMESPACE,
                label_selector,
                timeout_s=300,
                interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_pods_ready = now_ms()
            result.milestone("pods_running_to_pods_ready", t_pods_running, t_pods_ready,
                             meta={"ready_pod_count": str(len(ready_pods))})
            result.milestone("workload_applied_to_pods_ready", t_workload_applied, t_pods_ready)
            print(
                f"[03] {len(ready_pods)} pods Ready "
                f"(+{elapsed_human(t_pods_running, t_pods_ready)} after Running; "
                f"total: {elapsed_human(t_workload_applied, t_pods_ready)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[03] WARNING: pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        print(
            "[03] WARNING: not all pods reached Running within timeout; "
            "recording partial milestone.",
            file=sys.stderr,
        )
        result.milestone(
            "workload_applied_to_pods_running_partial",
            t_workload_applied,
            now_ms(),
        )

    # ── Step 7 — Capture node count ───────────────────────────────────────────
    final_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    result.extra["baseline_node_count"] = baseline_count
    result.extra["final_node_count"] = len(final_names)
    result.extra["new_nodes"] = sorted(final_names - baseline_names)
    result.extra["scheduler"] = "autonode" if is_autonode else "cas"

    # ── Cleanup ───────────────────────────────────────────────────────────────
    # Scale to 0 (do not delete — test 04 removes the deployment)
    cleanup(deployment, kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
