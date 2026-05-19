#!/usr/bin/env python3
"""
scripts/run-test-05b-dynamic-instance.py

Benchmark: Dynamic instance selection contrast (Test 05b)

Demonstrates the fundamental difference between CAS and Karpenter when a
workload exceeds the capacity of the configured instance type:

  CAS path (classic | hcp):
    - Apply large-workload-cas-unschedulable.yaml (28 CPU / 200 GiB)
    - CAS evaluates the m5.xlarge bench-standard machine pool
    - m5.xlarge (4 vCPU / 16 GiB) cannot satisfy the request
    - CAS emits NotTriggerScaleUp — it cannot change instance types
    - Node count is unchanged

  AutoNode path (hcp-autonode):
    - Apply the same workload manifest
    - Apply manifests/autonode/nodepool-flexible.yaml (allows r5.8xlarge+)
    - Karpenter evaluates all allowed instance types in the NodePool
    - Selects r5.8xlarge (32 vCPU / 256 GiB) — smallest that fits
    - Creates a NodeClaim, provisions the node, pod becomes Running
    - Record: time from pod Pending → NodeClaim created → node Ready → pod Running

This contrast makes the core thesis visible:
  CAS machine pools are static instance contracts.
  Karpenter is a demand-driven instance broker.

Usage:
  python3 scripts/run-test-05b-dynamic-instance.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--nodepool-name autonode-flexible] \\
      [--timeout 1800]
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

TEST_ID = "05b-dynamic-instance"
MANIFEST = (
    Path(__file__).parent.parent
    / "manifests"
    / "workloads"
    / "large-workload-cas-unschedulable.yaml"
)
NODEPOOL_MANIFEST = (
    Path(__file__).parent.parent / "manifests" / "autonode" / "nodepool-flexible.yaml"
)
NAMESPACE = "benchmark"
MACHINE_API_NS = "openshift-machine-api"
POD_NAME = "large-workload"

# Workload sizing constants (documented here for Canvas reporting)
WORKLOAD_CPU = "28"
WORKLOAD_MEMORY = "200Gi"
M5_XLARGE_CPU = "4"
M5_XLARGE_MEMORY = "16Gi"
TARGET_INSTANCE = "r5.8xlarge"
TARGET_INSTANCE_CPU = "32"
TARGET_INSTANCE_MEMORY = "256Gi"


def cleanup(kubeconfig: str | None, *, nodepool_name: str) -> None:
    """Remove the large-workload pod and the flexible NodePool (idempotent)."""
    try:
        oc_lib.delete_resource(
            "pod", POD_NAME, NAMESPACE, kubeconfig=kubeconfig, ignore_not_found=True
        )
    except Exception as exc:
        print(f"[cleanup] warning deleting pod: {exc}", file=sys.stderr)

    try:
        oc_lib.run_oc(
            ["delete", "nodepool", nodepool_name, "--ignore-not-found"],
            json_output=False,
            kubeconfig=kubeconfig,
        )
    except Exception as exc:
        print(f"[cleanup] warning deleting NodePool {nodepool_name}: {exc}", file=sys.stderr)

    print(f"[cleanup] large-workload pod and NodePool {nodepool_name} deleted.", file=sys.stderr)


def _find_not_trigger_event(kubeconfig: str | None) -> dict | None:
    """Search both machine-api and kube-system for NotTriggerScaleUp events."""
    for ns in (MACHINE_API_NS, "kube-system", NAMESPACE):
        try:
            events = oc_lib.get_events(ns, kubeconfig=kubeconfig)
            for ev in events:
                if "NotTriggerScaleUp" in ev.get("reason", "") or (
                    "not trigger scale up" in ev.get("message", "").lower()
                ):
                    return ev
        except oc_lib.OcError:
            pass
    return None


def _get_pod_phase(pod_name: str, namespace: str, kubeconfig: str | None) -> str | None:
    """Return the pod's current phase, or None if the pod doesn't exist yet."""
    try:
        pods = oc_lib.get_pods(namespace, f"app={pod_name}", kubeconfig=kubeconfig)
        for pod in pods:
            if pod.get("metadata", {}).get("name") == pod_name:
                return pod.get("status", {}).get("phase")
    except oc_lib.OcError:
        pass
    return None


def _wait_for_pod_phase(
    pod_name: str,
    namespace: str,
    target_phase: str,
    *,
    timeout_s: int = 1800,
    interval_s: int = 10,
    kubeconfig: str | None = None,
) -> None:
    """Poll until the named pod reaches target_phase. Raises PollTimeout on timeout."""

    def _check() -> bool:
        return _get_pod_phase(pod_name, namespace, kubeconfig) == target_phase

    oc_lib.poll_until(
        _check,
        timeout_s=timeout_s,
        interval_s=interval_s,
        label=f"pod/{pod_name} phase={target_phase}",
    )


def _get_nodeclaim_instance_type(nc: dict) -> str:
    """Extract the EC2 instance type from a NodeClaim, best-effort."""
    # Karpenter stores the resolved instance type in the node labels once
    # the node is registered; in the NodeClaim itself it lives in spec.requirements
    # or status.nodeName annotations.
    for req in nc.get("spec", {}).get("requirements", []):
        if req.get("key") == "node.kubernetes.io/instance-type":
            vals = req.get("values", [])
            if vals:
                return vals[0]
    return "unknown"


def run_cas_path(args, kubeconfig: str, result: BenchmarkResult) -> None:
    """CAS branch: apply workload, expect NotTriggerScaleUp, confirm no scaling."""
    # ── Baseline ────────────────────────────────────────────────────────────────
    baseline_count = oc_lib.get_node_count(kubeconfig=kubeconfig)
    result.extra["baseline_node_count"] = baseline_count
    print(f"[05b] CAS path. Baseline node count: {baseline_count}", file=sys.stderr)

    # ── Apply workload ───────────────────────────────────────────────────────────
    print(f"[05b] Applying {MANIFEST} ...", file=sys.stderr)
    t_applied = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST), kubeconfig=kubeconfig)

    # ── Wait for FailedScheduling ────────────────────────────────────────────────
    print("[05b] Waiting for FailedScheduling on large-workload ...", file=sys.stderr)
    try:
        fs_event = oc_lib.wait_for_event(
            NAMESPACE,
            "FailedScheduling",
            timeout_s=300,
            interval_s=10,
            kubeconfig=kubeconfig,
            object_name=POD_NAME,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for FailedScheduling. "
            "Is the bench-standard machine pool using m5.xlarge? "
            "The workload requests 28 CPU / 200 GiB — too large for m5.xlarge (4 vCPU / 16 GiB).",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    t_failed_scheduling = now_ms()
    result.milestone(
        "pod_applied_to_failed_scheduling",
        t_applied,
        t_failed_scheduling,
        meta={"fs_message": fs_event.get("message", "")[:300]},
    )
    print(
        f"[05b] FailedScheduling: {fs_event.get('message','')[:100]} "
        f"({elapsed_human(t_applied, t_failed_scheduling)})",
        file=sys.stderr,
    )

    # ── Wait for NotTriggerScaleUp ───────────────────────────────────────────────
    print("[05b] Waiting for CAS NotTriggerScaleUp event ...", file=sys.stderr)
    not_trigger_event: dict | None = None
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        not_trigger_event = _find_not_trigger_event(kubeconfig)
        if not_trigger_event:
            break
        time.sleep(15)

    t_not_trigger = now_ms()
    if not_trigger_event:
        result.milestone(
            "failed_scheduling_to_not_trigger_scale_up",
            t_failed_scheduling,
            t_not_trigger,
            meta={
                "cas_message": not_trigger_event.get("message", "")[:300],
                "scheduler": "cas",
                "reason": "instance_type_too_small",
            },
        )
        result.extra["not_trigger_message"] = not_trigger_event.get("message", "")
        print(
            f"[05b] NotTriggerScaleUp: {not_trigger_event.get('message','')[:100]}",
            file=sys.stderr,
        )
    else:
        print(
            "[05b] WARNING: NotTriggerScaleUp event not found within 5 minutes. "
            "CAS may use different event wording. Confirming node count is still unchanged.",
            file=sys.stderr,
        )

    # ── Confirm node count unchanged ────────────────────────────────────────────
    print("[05b] Waiting 5 min to confirm node count is unchanged ...", file=sys.stderr)
    time.sleep(300)
    final_count = oc_lib.get_node_count(kubeconfig=kubeconfig)
    result.extra["final_node_count"] = final_count
    result.extra["node_count_unchanged"] = final_count == baseline_count
    if final_count != baseline_count:
        print(
            f"[05b] WARNING: Node count changed from {baseline_count} to {final_count}.",
            file=sys.stderr,
        )
    else:
        print(f"[05b] Confirmed: node count unchanged at {final_count}.", file=sys.stderr)

    result.extra.update(
        {
            "scheduler": "cas",
            "workload_cpu": WORKLOAD_CPU,
            "workload_memory": WORKLOAD_MEMORY,
            "machine_pool_instance": "m5.xlarge",
            "machine_pool_cpu": M5_XLARGE_CPU,
            "machine_pool_memory": M5_XLARGE_MEMORY,
            "outcome": "not_scheduled",
        }
    )


def run_autonode_path(args, kubeconfig: str, result: BenchmarkResult) -> None:
    """AutoNode branch: apply flexible NodePool + workload, watch Karpenter provision."""
    nodepool_name = args.nodepool_name

    # ── Baseline ────────────────────────────────────────────────────────────────
    baseline_nc_count = oc_lib.get_nodeclaim_count(
        nodepool_name=nodepool_name, kubeconfig=kubeconfig
    )
    baseline_node_count = oc_lib.get_node_count(kubeconfig=kubeconfig)
    result.extra["baseline_nodeclaim_count"] = baseline_nc_count
    result.extra["baseline_node_count"] = baseline_node_count
    print(
        f"[05b] AutoNode path. Baseline: {baseline_node_count} nodes, "
        f"{baseline_nc_count} NodeClaims in pool '{nodepool_name}'",
        file=sys.stderr,
    )

    # ── Apply flexible NodePool ──────────────────────────────────────────────────
    print(f"[05b] Applying {NODEPOOL_MANIFEST} ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(NODEPOOL_MANIFEST), kubeconfig=kubeconfig)
        # Wait briefly for the NodePool to be accepted
        try:
            oc_lib.wait_for_nodepool_ready(nodepool_name, timeout_s=120, kubeconfig=kubeconfig)
        except oc_lib.PollTimeout:
            print(
                f"[05b] NodePool {nodepool_name} not yet Ready after 120s — "
                "proceeding anyway; it may become ready after the NodeClaim is created.",
                file=sys.stderr,
            )

    # ── Apply workload ───────────────────────────────────────────────────────────
    print(f"[05b] Applying {MANIFEST} ...", file=sys.stderr)
    t_pod_applied = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST), kubeconfig=kubeconfig)

    # ── Wait for FailedScheduling (pod goes Pending first) ──────────────────────
    print("[05b] Waiting for FailedScheduling on large-workload ...", file=sys.stderr)
    try:
        fs_event = oc_lib.wait_for_event(
            NAMESPACE,
            "FailedScheduling",
            timeout_s=120,
            interval_s=10,
            kubeconfig=kubeconfig,
            object_name=POD_NAME,
        )
        t_failed_scheduling = now_ms()
        result.milestone(
            "pod_applied_to_failed_scheduling",
            t_pod_applied,
            t_failed_scheduling,
            meta={"fs_message": fs_event.get("message", "")[:300]},
        )
        print(
            f"[05b] FailedScheduling at {elapsed_human(t_pod_applied, t_failed_scheduling)}",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        # Pod may have been scheduled immediately onto an existing compatible node
        t_failed_scheduling = t_pod_applied
        print(
            "[05b] No FailedScheduling event — pod may have been scheduled directly.",
            file=sys.stderr,
        )

    # ── Wait for NodeClaim ───────────────────────────────────────────────────────
    print(
        f"[05b] Waiting for new NodeClaim in NodePool '{nodepool_name}' ...", file=sys.stderr
    )
    try:
        new_nc = oc_lib.wait_for_new_nodeclaim(
            baseline_nc_count,
            nodepool_name=nodepool_name,
            timeout_s=300,
            interval_s=10,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            f"Timed out waiting for a NodeClaim in NodePool '{nodepool_name}'. "
            "Check that the NodePool READY=True and the workload has a "
            "nodeAffinity/tolerations targeting the flexible pool.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    t_nodeclaim = now_ms()
    instance_type = _get_nodeclaim_instance_type(new_nc)
    nc_name = new_nc.get("metadata", {}).get("name", "unknown")
    result.milestone(
        "failed_scheduling_to_nodeclaim",
        t_failed_scheduling,
        t_nodeclaim,
        meta={
            "nodeclaim_name": nc_name,
            "instance_type": instance_type,
            "nodepool": nodepool_name,
        },
    )
    print(
        f"[05b] NodeClaim {nc_name} created ({instance_type}) "
        f"at {elapsed_human(t_pod_applied, t_nodeclaim)}",
        file=sys.stderr,
    )

    # ── Wait for new node Ready ──────────────────────────────────────────────────
    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    print("[05b] Waiting for new node to become Ready ...", file=sys.stderr)
    try:
        new_node = oc_lib.wait_for_new_ready_node(
            baseline_names,
            timeout_s=args.timeout,
            interval_s=20,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for new node to become Ready. "
            "Check: oc get nodeclaim, oc get nodes, oc get events -n kube-system",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    t_node_ready = now_ms()
    result.milestone(
        "nodeclaim_to_node_ready",
        t_nodeclaim,
        t_node_ready,
        meta={"node_name": new_node},
    )
    print(
        f"[05b] Node {new_node} Ready at {elapsed_human(t_pod_applied, t_node_ready)}",
        file=sys.stderr,
    )

    # ── Wait for pod Running ─────────────────────────────────────────────────────
    print("[05b] Waiting for large-workload pod to be Running ...", file=sys.stderr)
    try:
        _wait_for_pod_phase(
            POD_NAME,
            NAMESPACE,
            "Running",
            timeout_s=args.timeout,
            interval_s=10,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for large-workload pod to be Running after node Ready. "
            "Check: oc describe pod large-workload -n benchmark",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    t_pod_running = now_ms()
    result.milestone(
        "node_ready_to_pod_running",
        t_node_ready,
        t_pod_running,
    )
    result.milestone(
        "pod_applied_to_pod_running",
        t_pod_applied,
        t_pod_running,
        meta={
            "instance_type_selected": instance_type,
            "node_name": new_node,
            "nodepool": nodepool_name,
        },
    )
    print(
        f"[05b] Pod Running! Total: {elapsed_human(t_pod_applied, t_pod_running)}",
        file=sys.stderr,
    )

    result.extra.update(
        {
            "scheduler": "karpenter",
            "workload_cpu": WORKLOAD_CPU,
            "workload_memory": WORKLOAD_MEMORY,
            "nodepool": nodepool_name,
            "instance_type_selected": instance_type,
            "nodeclaim_name": nc_name,
            "node_name": new_node,
            "outcome": "scheduled",
        }
    )


def main() -> None:
    parser = standard_args(
        "Test 05b — Dynamic instance selection: CAS refuses (NotTriggerScaleUp) "
        "vs Karpenter succeeds (selects r5.8xlarge)."
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-flexible",
        help="Karpenter NodePool name to create for the AutoNode path.",
    )
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)

    is_autonode = args.cluster_type == "hcp-autonode"

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )

    handle_sigint(
        lambda: cleanup(kubeconfig, nodepool_name=args.nodepool_name),
        run_id=args.run_id,
        test_id=TEST_ID,
        result=result,
    )

    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    if is_autonode:
        run_autonode_path(args, kubeconfig, result)
    else:
        run_cas_path(args, kubeconfig, result)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cleanup(kubeconfig, nodepool_name=args.nodepool_name)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
