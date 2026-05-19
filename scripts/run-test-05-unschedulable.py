#!/usr/bin/env python3
"""
scripts/run-test-05-unschedulable.py

Benchmark: Unschedulable oversize workload — autoscaler refuses to provision (Test 05)

Procedure (CAS — classic|hcp):
  1. Record baseline node count.
  2. Apply the oversize-workload Pod from manifests/workloads/memory-hog.yaml.
  3. Poll benchmark events for FailedScheduling.
  4. Poll openshift-machine-api events for NotTriggerScaleUp.
  5. Confirm node count has not changed after 5 minutes.
  6. Record findings, emit JSON summary.
  7. Cleanup: delete the oversize-workload pod.

Procedure (AutoNode — hcp-autonode):
  Steps 1–3 are the same.
  4. Confirm no new NodeClaim was created in the autonode-bench NodePool
     (Karpenter skips provisioning when the request exceeds all NodePool constraints).
  5–7 are the same.

The oversize-workload requests 200 CPU / 1 TiB memory — more than any single
m5.xlarge node (4 vCPU / 16 GiB). CAS emits NotTriggerScaleUp; Karpenter
creates no NodeClaim because no NodePool can satisfy the request.

Usage:
  python3 scripts/run-test-05-unschedulable.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--nodepool-name autonode-bench]  # hcp-autonode only
      [--timeout 600]
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

TEST_ID = "05-unschedulable"
MANIFEST = Path(__file__).parent.parent / "manifests" / "workloads" / "memory-hog.yaml"
NAMESPACE = "benchmark"
MACHINE_API_NS = "openshift-machine-api"
POD_NAME = "oversize-workload"
# Also clean up the normal memory-hog pod that lives in the same manifest
MEMORY_HOG_POD = "memory-hog"


def cleanup(kubeconfig: str | None) -> None:
    """Delete the oversize-workload pod. Idempotent."""
    for pod in (POD_NAME, MEMORY_HOG_POD):
        try:
            oc_lib.delete_resource("pod", pod, NAMESPACE, kubeconfig=kubeconfig)
        except Exception as exc:
            print(f"[cleanup] warning deleting {pod}: {exc}", file=sys.stderr)
    print("[cleanup] oversize-workload deleted.", file=sys.stderr)


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


def main() -> None:
    parser = standard_args("Test 05 — Unschedulable oversize workload (autoscaler refuses to provision).")
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help="Karpenter NodePool name to check for unexpected NodeClaims (hcp-autonode only).",
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

    handle_sigint(lambda: cleanup(kubeconfig), run_id=args.run_id, test_id=TEST_ID, result=result)

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # ── Step 1 — Baseline ─────────────────────────────────────────────────────
    baseline_count = oc_lib.get_node_count(kubeconfig=kubeconfig)
    print(f"[05] Baseline node count: {baseline_count}", file=sys.stderr)
    if is_autonode:
        baseline_nc_count = oc_lib.get_nodeclaim_count(
            nodepool_name=args.nodepool_name, kubeconfig=kubeconfig
        )
        print(f"[05] Baseline NodeClaims: {baseline_nc_count}", file=sys.stderr)
        result.extra["baseline_nodeclaim_count"] = baseline_nc_count

    # ── Step 2 — Apply oversize pod ───────────────────────────────────────────
    print(f"[05] Applying {MANIFEST} (oversize-workload) ...", file=sys.stderr)
    t_pod_applied = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST), kubeconfig=kubeconfig)
        # The manifest also creates memory-hog; remove it so it doesn't compete
        oc_lib.delete_resource(
            "pod", MEMORY_HOG_POD, NAMESPACE,
            kubeconfig=kubeconfig, ignore_not_found=True,
        )

    # ── Step 3 — Wait for FailedScheduling ───────────────────────────────────
    print("[05] Waiting for FailedScheduling on oversize-workload ...", file=sys.stderr)
    try:
        fs_event = oc_lib.wait_for_event(
            NAMESPACE,
            "FailedScheduling",
            timeout_s=300,
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
            f"[05] FailedScheduling: {fs_event.get('message','')[:120]} "
            f"({elapsed_human(t_pod_applied, t_failed_scheduling)})",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for FailedScheduling. "
            "Is the pod's resource request actually larger than available node capacity?",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # ── Step 4 — Confirm autoscaler did not provision ─────────────────────────
    # CAS:      poll for NotTriggerScaleUp event from openshift-machine-api.
    # AutoNode: confirm no new NodeClaim appears in the NodePool within 5 min.
    if is_autonode:
        print("[05] Waiting 5 min then confirming no new NodeClaim was created ...", file=sys.stderr)
        time.sleep(300)
        final_nc_count = oc_lib.get_nodeclaim_count(
            nodepool_name=args.nodepool_name, kubeconfig=kubeconfig
        )
        t_no_provision = now_ms()
        # A decrease means Karpenter consolidated unrelated nodes — that's expected.
        # Only flag an INCREASE, which would indicate Karpenter tried to provision for the oversize pod.
        nc_increased = (final_nc_count > baseline_nc_count)
        nc_decreased = (final_nc_count < baseline_nc_count)
        result.extra["final_nodeclaim_count"] = final_nc_count
        result.extra["nodeclaim_count_unchanged"] = not nc_increased
        if not nc_increased:
            result.milestone(
                "failed_scheduling_to_no_provision",
                t_failed_scheduling,
                t_no_provision,
                meta={
                    "scheduler": "autonode",
                    "verdict": "no_nodeclaim_created",
                    "nodeclaim_count": str(final_nc_count),
                },
            )
            note = " (count decreased due to unrelated consolidation)" if nc_decreased else ""
            print(
                f"[05] Confirmed: Karpenter created no NodeClaim for the oversize pod{note} "
                f"({elapsed_human(t_failed_scheduling, t_no_provision)}).",
                file=sys.stderr,
            )
        else:
            print(
                f"[05] WARNING: NodeClaim count INCREASED from {baseline_nc_count} to {final_nc_count}. "
                "Karpenter may have provisioned for a different workload — verify no other workloads are pending.",
                file=sys.stderr,
            )
    else:
        print("[05] Waiting for CAS NotTriggerScaleUp event ...", file=sys.stderr)
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
                },
            )
            print(
                f"[05] NotTriggerScaleUp: {not_trigger_event.get('message','')[:120]}",
                file=sys.stderr,
            )
            result.extra["not_trigger_message"] = not_trigger_event.get("message", "")
            result.extra["not_trigger_reason"] = not_trigger_event.get("reason", "")
        else:
            print(
                "[05] WARNING: NotTriggerScaleUp event not found. "
                "CAS may use different event wording in this version. "
                "Proceeding to confirm node count is unchanged.",
                file=sys.stderr,
            )

    # ── Step 5 — Confirm node count unchanged ────────────────────────────────
    # AutoNode: already waited 5 min above; just record the check.
    # CAS: wait 5 min then verify no scale-up occurred.
    if not is_autonode:
        print("[05] Waiting 5 min then confirming node count is unchanged ...", file=sys.stderr)
        time.sleep(300)
    final_count = oc_lib.get_node_count(kubeconfig=kubeconfig)
    result.extra["baseline_node_count"] = baseline_count
    result.extra["final_node_count"] = final_count
    result.extra["node_count_unchanged"] = (final_count == baseline_count)

    if final_count != baseline_count:
        print(
            f"[05] WARNING: Node count changed from {baseline_count} to {final_count}. "
            "CAS may have scaled for a different workload.",
            file=sys.stderr,
        )
    else:
        print(f"[05] Confirmed: node count unchanged at {final_count}.", file=sys.stderr)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cleanup(kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
