#!/usr/bin/env python3
"""
scripts/run-test-04-autoscale-down.py

Benchmark: Scale-down — CAS (Classic/HCP) or Karpenter consolidation (hcp-autonode) (Test 04)

Procedure (CAS — classic|hcp):
  1. Record current node names (should include nodes added in test 03).
  2. Delete the cas-trigger deployment.
  3. Poll openshift-machine-api events for scale-down / cordon activity.
  4. Poll until a node is cordoned (SchedulingDisabled).
  5. Poll until node count returns to the pre-test-03 baseline.
  6. Emit milestone timings, capture Ready node name sets before delete vs after stable,
     and print JSON summary.

Note: CAS scale-down has mandatory cooldown periods:
  - scale-down-delay-after-add: 10 min (after any scale-up)
  - scale-down-unneeded-time: 10 min (node must be underutilised for this long)
  Total expected wait: 10–25 minutes after workload removal.

Procedure (AutoNode — hcp-autonode):
  1–2 same, but deletes the karpenter-trigger deployment.
  3. Poll for NodeClaim count to drop (Karpenter consolidation decision).
  4. Poll until node count drops to baseline.
  5. Compare Ready node names before delete vs after stable (proof which hostnames left).
  Karpenter consolidation is much faster (~30 s–2 min) with no mandatory cooldown.

Prerequisites: test 03 must have been run (extra nodes exist).

Usage:
  python3 scripts/run-test-04-autoscale-down.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--baseline-count <N>]  # expected node count after scale-down (default: auto-detect)
      [--nodepool-name autonode-bench]  # hcp-autonode only
      [--timeout 2400]
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
    handle_sigint,
    now_ms,
    resolve_kubeconfig,
    standard_args,
    verify_oc_login,
)

TEST_ID = "04-autoscale-down"
NAMESPACE = "benchmark"
MACHINE_API_NS = "openshift-machine-api"
DEPLOYMENT_CAS = "cas-trigger"
DEPLOYMENT_AUTONODE = "karpenter-trigger"


def _is_cordoned(node: dict) -> bool:
    """Return True if a node has SchedulingDisabled (cordoned)."""
    return node.get("spec", {}).get("unschedulable", False)


def _find_cordoned_node(kubeconfig: str | None) -> str | None:
    """Return the name of the first cordoned extra node, or None."""
    try:
        nodes = oc_lib.get_nodes(kubeconfig=kubeconfig)
        for node in nodes:
            if _is_cordoned(node):
                return node["metadata"]["name"]
    except oc_lib.OcError:
        pass
    return None


def _record_ready_node_diff(
    result: BenchmarkResult,
    before: set[str],
    after: set[str],
    *,
    prefix: str = "",
) -> None:
    """Emit sorted node-name sets and removed/added lists into result.extra (JSON reports)."""
    key = f"{prefix}_" if prefix else ""
    removed = sorted(before - after)
    added = sorted(after - before)
    result.extra[f"{key}ready_node_names_before"] = sorted(before)
    result.extra[f"{key}ready_node_names_after"] = sorted(after)
    result.extra[f"{key}ready_nodes_removed"] = removed
    result.extra[f"{key}ready_nodes_added"] = added


def main() -> None:
    parser = standard_args("Test 04 — Scale-down benchmark (CAS for classic/hcp, Karpenter consolidation for hcp-autonode).")
    parser.add_argument(
        "--baseline-count",
        type=int,
        default=0,
        help="Expected Ready node count after scale-down (0 = auto-detect as current minus added nodes).",
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help="Karpenter NodePool name to watch for NodeClaim count drop (hcp-autonode only).",
    )
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)
    timeout = args.timeout if args.timeout else 2400  # CAS scale-down can take 20+ min

    is_autonode = args.cluster_type == "hcp-autonode"
    deployment = DEPLOYMENT_AUTONODE if is_autonode else DEPLOYMENT_CAS

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    if is_autonode:
        result.extra["scale_down_policy"] = {
            "scheduler": "autonode",
            "mechanism": "karpenter_consolidation",
            "note": "Karpenter consolidation; no mandatory cooldown — typically 30 s–2 min",
        }
    else:
        # Record CAS policy values so reports can show the policy context alongside the timing.
        # These are the OpenShift defaults; a tuned cluster would override them.
        result.extra["scale_down_policy"] = {
            "scheduler": "cas",
            "scale_down_delay_after_add": "10m (default)",
            "scale_down_unneeded_time": "10m (default)",
            "note": "t_start = moment oc delete command is issued; t_end = node no longer in oc get nodes",
        }

    # No meaningful cleanup on SIGINT for scale-down (the workload is already gone)
    handle_sigint(lambda: None, run_id=args.run_id, test_id=TEST_ID, result=result)

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # ── Step 1 — Baseline (current state, post test-03) ───────────────────────
    print("[04] Recording current node state ...", file=sys.stderr)
    nodes_before = oc_lib.get_node_names(kubeconfig=kubeconfig)
    current_count = len(nodes_before)
    print(f"[04] Current: {current_count} Ready nodes.", file=sys.stderr)
    if is_autonode:
        current_nc_count = oc_lib.get_nodeclaim_count(
            nodepool_name=args.nodepool_name, kubeconfig=kubeconfig
        )
        print(f"[04] Current NodeClaims: {current_nc_count}", file=sys.stderr)
        result.extra["baseline_nodeclaim_count"] = current_nc_count

    # Determine target count for scale-down
    target_count = args.baseline_count
    if target_count <= 0:
        # Heuristic: assume 1 node was added; scale down to current - 1
        target_count = max(1, current_count - 1)
        print(
            f"[04] No --baseline-count given; targeting ≤ {target_count} nodes after scale-down.",
            file=sys.stderr,
        )

    # ── Step 2 — Delete the workload ─────────────────────────────────────────
    print(f"[04] Deleting deployment/{deployment} in {NAMESPACE} ...", file=sys.stderr)
    t_workload_removed = now_ms()
    if not args.dry_run:
        oc_lib.delete_resource("deployment", deployment, NAMESPACE, kubeconfig=kubeconfig)
    print(f"[04] {deployment} deleted at {t_workload_removed}.", file=sys.stderr)

    # ── Step 3 — Wait for scale-down decision ─────────────────────────────────
    # CAS:      wait for a node to be cordoned (SchedulingDisabled) — reliable proxy
    #           because cordoning precedes drain and takes ~10–20 min due to cooldown.
    # AutoNode: watch for NodeClaim count to drop (Karpenter consolidation decision)
    #           which happens in seconds to minutes with no mandatory cooldown.
    if is_autonode:
        print("[04] Waiting for Karpenter to consolidate (NodeClaim count to drop) ...", file=sys.stderr)
        target_nc = max(0, current_nc_count - 1)
        t_consolidation_start: int | None = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            nc_count = oc_lib.get_nodeclaim_count(
                nodepool_name=args.nodepool_name, kubeconfig=kubeconfig
            )
            if nc_count <= target_nc:
                t_consolidation_start = now_ms()
                result.milestone(
                    "workload_removed_to_consolidation_start",
                    t_workload_removed,
                    t_consolidation_start,
                    meta={"nodeclaim_count": str(nc_count), "scheduler": "autonode"},
                )
                print(
                    f"[04] NodeClaim count dropped to {nc_count} "
                    f"({elapsed_human(t_workload_removed, t_consolidation_start)}).",
                    file=sys.stderr,
                )
                break
            time.sleep(15)
        else:
            print(
                "[04] WARNING: NodeClaim count did not drop within timeout; "
                "continuing to watch for node removal ...",
                file=sys.stderr,
            )
            t_consolidation_start = now_ms()
    else:
        print(
            "[04] Waiting for CAS to cordon a node (cooldown: ~10–20 min) ...",
            file=sys.stderr,
        )
        t_consolidation_start = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cordoned = _find_cordoned_node(kubeconfig)
            if cordoned:
                t_consolidation_start = now_ms()
                result.milestone(
                    "workload_removed_to_first_cordon",
                    t_workload_removed,
                    t_consolidation_start,
                    meta={"cordoned_node": cordoned, "scheduler": "cas"},
                )
                print(
                    f"[04] First cordon: {cordoned} ({elapsed_human(t_workload_removed, t_consolidation_start)}).",
                    file=sys.stderr,
                )
                break
            time.sleep(30)
        else:
            print(
                "[04] WARNING: No cordoned node observed within timeout; "
                "continuing to watch for node removal ...",
                file=sys.stderr,
            )
            t_consolidation_start = now_ms()

    # ── Step 4 — Wait for node count to drop ─────────────────────────────────
    print(f"[04] Waiting for node count to drop to ≤ {target_count} ...", file=sys.stderr)
    try:
        final_count = oc_lib.wait_for_node_count_at_most(
            target_count,
            timeout_s=int(deadline - time.monotonic()),
            interval_s=30,
            kubeconfig=kubeconfig,
        )
        t_node_removed = now_ms()
        nodes_after = oc_lib.get_node_names(kubeconfig=kubeconfig)
        result.milestone(
            "consolidation_to_node_removed",
            t_consolidation_start,
            t_node_removed,
        )
        result.milestone(
            "workload_removed_to_stable",
            t_workload_removed,
            t_node_removed,
            meta={
                "final_node_count": str(final_count),
                "scheduler": "autonode" if is_autonode else "cas",
            },
        )
        _record_ready_node_diff(result, nodes_before, nodes_after)
        removed = sorted(nodes_before - nodes_after)
        if removed:
            print(
                "[04] Ready nodes removed since pre-delete snapshot: "
                f"{', '.join(removed)}.",
                file=sys.stderr,
            )
        print(
            f"[04] Cluster stable at {final_count} nodes "
            f"(total from removal: {elapsed_human(t_workload_removed, t_node_removed)}).",
            file=sys.stderr,
        )
        result.extra["final_node_count"] = final_count
        result.extra["initial_node_count"] = current_count
    except oc_lib.PollTimeout:
        remaining_count = oc_lib.get_node_count(kubeconfig=kubeconfig)
        nodes_after_partial = oc_lib.get_node_names(kubeconfig=kubeconfig)
        _record_ready_node_diff(result, nodes_before, nodes_after_partial, prefix="partial")
        result.milestone(
            "workload_removed_to_scale_down_partial",
            t_workload_removed,
            now_ms(),
            meta={"remaining_node_count": str(remaining_count)},
        )
        print(
            f"[04] WARNING: Timeout — cluster has {remaining_count} nodes (target was {target_count}). "
            + ("Karpenter may still be consolidating." if is_autonode else
               "CAS may still be cooling down. "
               "This is expected if the cluster recently completed a scale-up."),
            file=sys.stderr,
        )

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
