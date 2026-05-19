#!/usr/bin/env python3
"""
scripts/run-test-15-spot-instances.py

Benchmark: Spot instance autoscaling (Test 15)

Measures the end-to-end latency for autoscaling onto EC2 Spot instances,
from workload deployment to pods Running.  Compares spot provisioning speed
against the equivalent on-demand run (tests 03/10/14) when that data is
available in events.jsonl for the same RUN_ID.

Supported cluster types:
  classic      — creates a bench-spot machine pool via ROSA CLI with
                 --use-spot-instances, then applies spot-trigger-classic.yaml.
                 The pool starts with min-replicas=0 so scale-up is entirely
                 driven by CAS responding to FailedScheduling events.

  hcp-autonode — creates the autonode-spot NodePool
                 (manifests/autonode/nodepool-spot.yaml) with
                 karpenter.sh/capacity-type=spot, then applies
                 spot-trigger-autonode.yaml and measures the Karpenter
                 NodeClaim → EC2 spot launch → node Ready → pods Running chain.

  hcp          — SKIP: standard ROSA HCP does not support spot instances on
                 machine pools (neither via ROSA CLI nor Karpenter without
                 AutoNode enabled).

Measurement chain (both cluster types):

  t_workload_applied
      ↓ workload_applied_to_failed_scheduling
  t_failed_scheduling
      ↓ failed_scheduling_to_scheduler_triggered  (CAS TriggeredScaleUp / NodeClaim)
  t_scheduler_triggered
      ↓ scheduler_triggered_to_node_ready
  t_node_ready
      ↓ node_ready_to_pods_running
  t_pods_running
  ─────────────
  workload_applied_to_pods_running   (total)

  Classic only:
    pool_submitted_to_first_node_ready — rosa create machinepool → first Ready node
    (pool starts at min=0 so this only fires if min≥1 or the pool was pre-created)

  AutoNode only:
    failed_scheduling_to_nodeclaim    — FailedScheduling → Karpenter NodeClaim
    nodeclaim_to_node_ready           — NodeClaim → node Ready

Comparison:
  When a RUN_ID is provided, the script loads on-demand milestones from
  events.jsonl (test 03 for Classic, test 10 for AutoNode) and writes them into
  result.extra["on_demand_baseline_ms"] for Canvas comparison.

Usage
-----
  python3 scripts/run-test-15-spot-instances.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--nodepool-name autonode-spot]     # hcp-autonode only
      [--spot-max-price 0.20]             # classic only; omit to use on-demand price
      [--timeout 1800]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.lib import oc as oc_lib
from scripts.lib.bench import (
    REPO_ROOT,
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

TEST_ID = "15-spot-instances"
NAMESPACE = "spot-test"
MACHINE_API_NS = "openshift-machine-api"
DEPLOYMENT = "spot-trigger"
LABEL_SELECTOR = "app=spot-trigger"
POOL_NAME_CLASSIC = "bench-spot"

MANIFEST_CLASSIC = REPO_ROOT / "manifests" / "workloads" / "spot-trigger-classic.yaml"
MANIFEST_AUTONODE = REPO_ROOT / "manifests" / "workloads" / "spot-trigger-autonode.yaml"
MANIFEST_NODEPOOL = REPO_ROOT / "manifests" / "autonode" / "nodepool-spot.yaml"

PROVISION_TIMEOUT_S = 900    # 15 min — spot can occasionally take longer to find capacity
POOL_CREATE_TIMEOUT_S = 600  # 10 min for rosa create machinepool to complete
WAIT_INTERVAL_S = 15


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_on_demand_baseline(run_id: str, cluster_type: str) -> dict[str, Any]:
    """
    Read on-demand provisioning milestones from events.jsonl for the same run.

    For classic: loads test 03 milestones.
    For hcp-autonode: loads test 10 milestones.

    Returns an empty dict if events.jsonl is absent or has no relevant entries.
    """
    if not run_id:
        return {}
    events_path = REPO_ROOT / "results" / run_id / "events.jsonl"
    if not events_path.exists():
        return {}

    if cluster_type == "hcp-autonode":
        labels_of_interest = {
            "10-autonode-scale.initial.pending_to_pods_running",
            "10-autonode-scale.initial.nodeclaim_to_node_ready",
            "10-autonode-scale.initial.failed_scheduling_to_nodeclaim",
        }
    else:
        labels_of_interest = {
            "03-autoscale-up.workload_applied_to_pods_running",
            "03-autoscale-up.cas_triggered_to_node_ready",
            "03-autoscale-up.workload_applied_to_failed_scheduling",
        }

    baseline: dict[str, Any] = {}
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            label = event.get("label", "")
            if label in labels_of_interest:
                baseline[label] = event.get("elapsed_ms", 0)
    except (OSError, json.JSONDecodeError):
        pass
    return baseline


def _create_classic_spot_pool(
    cluster_name: str,
    spot_max_price: str | None,
    kubeconfig: str | None,
) -> int:
    """
    Create the bench-spot machine pool on a Classic cluster.

    Returns t_pool_submitted (ms).  The pool starts at min-replicas=0 so
    no nodes are provisioned until the workload triggers CAS scale-up.
    """
    print("[15] Creating bench-spot machine pool (spot instances, min=0) ...", file=sys.stderr)

    rosa_cmd = [
        "rosa", "create", "machinepool",
        "--cluster", cluster_name,
        "--name", POOL_NAME_CLASSIC,
        "--instance-type", "m5.xlarge",
        "--use-spot-instances",
        "--enable-autoscaling",
        "--min-replicas", "0",
        "--max-replicas", "5",
        "--labels", "benchmark=true,pool-type=spot",
        "--yes",
    ]
    if spot_max_price:
        rosa_cmd.extend(["--spot-max-price", spot_max_price])

    t_submitted = now_ms()
    result = subprocess.run(rosa_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(
            f"[15] FATAL: rosa create machinepool failed:\n{result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        f"[15] bench-spot pool submitted to OCM "
        f"({elapsed_human(t_submitted, now_ms())} to accept).",
        file=sys.stderr,
    )
    return t_submitted


def _delete_classic_spot_pool(cluster_name: str) -> None:
    """Remove the bench-spot machine pool (fire-and-forget on failure)."""
    try:
        subprocess.run(
            ["rosa", "delete", "machinepool",
             "--cluster", cluster_name,
             "--machinepool", POOL_NAME_CLASSIC,
             "--yes"],
            check=True,
            capture_output=True,
        )
        print("[15] bench-spot machine pool deleted.", file=sys.stderr)
    except subprocess.CalledProcessError as exc:
        print(f"[15] WARNING: could not delete bench-spot pool: {exc.stderr}", file=sys.stderr)


def _verify_autonode_ready(kubeconfig: str | None) -> None:
    """Confirm ec2nodeclass/default is READY=True before starting."""
    print("[15] Checking ec2nodeclass/default is Ready ...", file=sys.stderr)
    try:
        ec2nc = oc_lib.run_oc(["get", "ec2nodeclass", "default"], kubeconfig=kubeconfig)
        conditions = ec2nc.get("status", {}).get("conditions", [])
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in conditions
        )
        if not ready:
            print(
                "[15] FATAL: ec2nodeclass/default is not Ready. "
                "Ensure AutoNode is enabled: rosa edit cluster --autonode=enabled.",
                file=sys.stderr,
            )
            sys.exit(1)
        print("[15] ec2nodeclass/default is Ready.", file=sys.stderr)
    except oc_lib.OcError as exc:
        print(
            f"[15] FATAL: could not read ec2nodeclass/default — {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def cleanup_classic(cluster_name: str, kubeconfig: str | None) -> None:
    """Remove the spot-test namespace and bench-spot machine pool."""
    try:
        oc_lib.run_oc(
            ["delete", "namespace", NAMESPACE, "--ignore-not-found"],
            json_output=False, kubeconfig=kubeconfig, capture_stderr=False,
        )
        print(f"[cleanup] namespace {NAMESPACE} removed.", file=sys.stderr)
    except Exception as exc:
        print(f"[cleanup] warning removing namespace: {exc}", file=sys.stderr)
    _delete_classic_spot_pool(cluster_name)


def cleanup_autonode(nodepool_name: str, kubeconfig: str | None) -> None:
    """Remove the spot-test namespace and autonode-spot NodePool."""
    try:
        oc_lib.run_oc(
            ["delete", "namespace", NAMESPACE, "--ignore-not-found"],
            json_output=False, kubeconfig=kubeconfig, capture_stderr=False,
        )
        print(f"[cleanup] namespace {NAMESPACE} removed.", file=sys.stderr)
    except Exception as exc:
        print(f"[cleanup] warning removing namespace: {exc}", file=sys.stderr)

    try:
        oc_lib.run_oc(
            ["delete", "nodepool", nodepool_name, "--ignore-not-found"],
            json_output=False, kubeconfig=kubeconfig, capture_stderr=False,
        )
        print(f"[cleanup] NodePool {nodepool_name} removed.", file=sys.stderr)
    except Exception as exc:
        print(f"[cleanup] warning removing NodePool: {exc}", file=sys.stderr)


# ── Classic path ──────────────────────────────────────────────────────────────


def _run_classic(
    args: argparse.Namespace,
    kubeconfig: str | None,
    result: BenchmarkResult,
) -> None:
    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    baseline_count = len(baseline_names)
    print(f"[15] Baseline: {baseline_count} Ready nodes.", file=sys.stderr)
    result.extra["baseline_node_count"] = baseline_count

    # ── Phase 1 — Create spot machine pool ────────────────────────────────────
    t_pool_submitted: int | None = None
    if not args.dry_run:
        t_pool_submitted = _create_classic_spot_pool(
            args.cluster_name,
            getattr(args, "spot_max_price", None) or None,
            kubeconfig,
        )
        result.extra["pool_submitted_ms"] = t_pool_submitted

    # ── Phase 2 — Apply workload and wait for scale-up ─────────────────────
    print("[15] Applying spot-trigger-classic.yaml ...", file=sys.stderr)
    t_workload_applied = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_CLASSIC), kubeconfig=kubeconfig)
    print(f"[15] spot-trigger applied at {t_workload_applied}.", file=sys.stderr)

    # Wait for FailedScheduling
    print("[15] Waiting for FailedScheduling event ...", file=sys.stderr)
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
        print(
            f"[15] FailedScheduling observed ({elapsed_human(t_workload_applied, t_failed_scheduling)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for FailedScheduling. "
            "Check that the spot pool has autoscaling enabled and CAS is running.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for CAS scale-up decision
    t_scheduler_triggered = now_ms()
    print("[15] Waiting for CAS scale-up decision event ...", file=sys.stderr)
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
                "capacity_type": "spot",
            },
        )
        print(
            f"[15] CAS {cas_event.get('reason')} observed "
            f"({elapsed_human(t_failed_scheduling, t_scheduler_triggered)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            "[15] WARNING: No CAS scale-up event found in openshift-machine-api "
            "within 600s; continuing to watch for new node ...",
            file=sys.stderr,
        )

    # Wait for new spot node Ready
    print("[15] Waiting for new spot node to be Ready ...", file=sys.stderr)
    try:
        new_node = oc_lib.wait_for_new_ready_node(
            baseline_names,
            timeout_s=PROVISION_TIMEOUT_S,
            interval_s=WAIT_INTERVAL_S,
            kubeconfig=kubeconfig,
        )
        t_node_ready = now_ms()
        result.milestone(
            "scheduler_triggered_to_node_ready",
            t_scheduler_triggered,
            t_node_ready,
            meta={"new_node": new_node, "capacity_type": "spot"},
        )
        result.milestone(
            "workload_applied_to_node_ready",
            t_workload_applied,
            t_node_ready,
        )
        if t_pool_submitted is not None:
            result.milestone(
                "pool_submitted_to_first_node_ready",
                t_pool_submitted,
                t_node_ready,
                meta={"new_node": new_node, "capacity_type": "spot"},
            )
        result.extra["first_spot_node"] = new_node
        print(
            f"[15] Spot node Ready: {new_node} "
            f"({elapsed_human(t_scheduler_triggered, t_node_ready)} from CAS trigger).",
            file=sys.stderr,
        )
        collect_node_telemetry(
            new_node,
            prefix=f"{TEST_ID}.new_node",
            since_ms=t_workload_applied,
            run_id=result.run_id,
            cluster_type=result.cluster_type,
            cluster_name=result.cluster_name,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            f"Timed out after {PROVISION_TIMEOUT_S}s waiting for a new spot node. "
            "Spot capacity may be unavailable; try a different AZ or instance type.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for pods Running
    print(f"[15] Waiting for {DEPLOYMENT} pods to be Running ...", file=sys.stderr)
    try:
        running_pods = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            LABEL_SELECTOR,
            timeout_s=600,
            interval_s=WAIT_INTERVAL_S,
            kubeconfig=kubeconfig,
        )
        t_pods_running = now_ms()
        result.milestone(
            "node_ready_to_pods_running",
            t_node_ready,
            t_pods_running,
            meta={"running_pods": str(len(running_pods))},
        )
        result.milestone(
            "workload_applied_to_pods_running",
            t_workload_applied,
            t_pods_running,
        )
        print(
            f"[15] {len(running_pods)} pods Running "
            f"(total: {elapsed_human(t_workload_applied, t_pods_running)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            "[15] WARNING: not all pods reached Running within timeout.",
            file=sys.stderr,
        )
        result.milestone(
            "workload_applied_to_pods_running_partial",
            t_workload_applied,
            now_ms(),
        )

    # Capture final state
    final_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    result.extra["final_node_count"] = len(final_names)
    result.extra["new_nodes"] = sorted(final_names - baseline_names)
    result.extra["scheduler"] = "cas"
    result.extra["capacity_type"] = "spot"


# ── AutoNode path ─────────────────────────────────────────────────────────────


def _run_autonode(
    args: argparse.Namespace,
    kubeconfig: str | None,
    result: BenchmarkResult,
    nodepool_name: str,
) -> None:
    # ── Phase 0 — NodePool ────────────────────────────────────────────────────
    print(f"[15] Applying spot NodePool {nodepool_name!r} ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_NODEPOOL), kubeconfig=kubeconfig)
        # Patch NodePool name if not using the default 'autonode-spot'
        if nodepool_name != "autonode-spot":
            print(
                f"[15] NOTE: manifest defines NodePool 'autonode-spot'; "
                f"--nodepool-name={nodepool_name!r} is used for polling only. "
                "Edit manifests/autonode/nodepool-spot.yaml to change the pool name.",
                file=sys.stderr,
            )
        try:
            oc_lib.wait_for_nodepool_ready(
                nodepool_name, timeout_s=120, interval_s=5, kubeconfig=kubeconfig
            )
        except oc_lib.PollTimeout:
            print(
                "[15] WARNING: NodePool Ready condition not observed within 120s; "
                "continuing — it may still be initializing.",
                file=sys.stderr,
            )
    print(f"[15] NodePool {nodepool_name!r} applied.", file=sys.stderr)

    baseline_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    nc_before = oc_lib.get_nodeclaim_count(nodepool_name=nodepool_name, kubeconfig=kubeconfig)
    result.extra["baseline_node_count"] = len(baseline_names)

    # ── Phase 1 — Apply workload ──────────────────────────────────────────────
    print("[15] Applying spot-trigger-autonode.yaml ...", file=sys.stderr)
    t_workload_applied = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_AUTONODE), kubeconfig=kubeconfig)
    print(f"[15] spot-trigger applied at {t_workload_applied}.", file=sys.stderr)

    # Wait for FailedScheduling
    print("[15] Waiting for FailedScheduling event ...", file=sys.stderr)
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
        print(
            f"[15] FailedScheduling observed ({elapsed_human(t_workload_applied, t_failed_scheduling)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for FailedScheduling. "
            "Check that trigger pods have nodeAffinity for the spot NodePool and "
            "that no other pool can absorb them.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for NodeClaim (Karpenter provisioning decision)
    print("[15] Waiting for Karpenter spot NodeClaim ...", file=sys.stderr)
    t_scheduler_triggered = now_ms()
    try:
        new_nc = oc_lib.wait_for_new_nodeclaim(
            nc_before,
            nodepool_name=nodepool_name,
            timeout_s=300,
            interval_s=5,
            kubeconfig=kubeconfig,
        )
        t_scheduler_triggered = now_ms()
        nc_name = new_nc.get("metadata", {}).get("name", "")
        # Inspect the NodeClaim to confirm spot capacity type
        nc_labels = new_nc.get("metadata", {}).get("labels", {})
        capacity_type = nc_labels.get("karpenter.sh/capacity-type", "unknown")
        result.milestone(
            "failed_scheduling_to_nodeclaim",
            t_failed_scheduling,
            t_scheduler_triggered,
            meta={"nodeclaim": nc_name, "capacity_type": capacity_type},
        )
        result.milestone(
            "failed_scheduling_to_scheduler_triggered",
            t_failed_scheduling,
            t_scheduler_triggered,
            meta={"nodeclaim": nc_name, "scheduler": "autonode", "capacity_type": capacity_type},
        )
        result.extra["nodeclaim_capacity_type"] = capacity_type
        print(
            f"[15] Karpenter NodeClaim {nc_name!r} created "
            f"(capacity-type={capacity_type}, "
            f"{elapsed_human(t_failed_scheduling, t_scheduler_triggered)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for Karpenter NodeClaim. "
            "Ensure ec2nodeclass/default is Ready, the NodePool name matches "
            "the nodeAffinity in spot-trigger-autonode.yaml, and spot capacity "
            "is available in the cluster's AZs.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for new spot node Ready
    print("[15] Waiting for spot node to be Ready ...", file=sys.stderr)
    try:
        new_node = oc_lib.wait_for_new_ready_node(
            baseline_names,
            timeout_s=PROVISION_TIMEOUT_S,
            interval_s=WAIT_INTERVAL_S,
            kubeconfig=kubeconfig,
        )
        t_node_ready = now_ms()
        result.milestone(
            "nodeclaim_to_node_ready",
            t_scheduler_triggered,
            t_node_ready,
            meta={"new_node": new_node, "capacity_type": "spot"},
        )
        result.milestone(
            "scheduler_triggered_to_node_ready",
            t_scheduler_triggered,
            t_node_ready,
            meta={"new_node": new_node, "capacity_type": "spot"},
        )
        result.extra["first_spot_node"] = new_node
        print(
            f"[15] Spot node Ready: {new_node} "
            f"({elapsed_human(t_scheduler_triggered, t_node_ready)} from NodeClaim).",
            file=sys.stderr,
        )
        collect_node_telemetry(
            new_node,
            prefix=f"{TEST_ID}.new_node",
            since_ms=t_workload_applied,
            run_id=result.run_id,
            cluster_type=result.cluster_type,
            cluster_name=result.cluster_name,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            f"Timed out after {PROVISION_TIMEOUT_S}s waiting for spot node Ready. "
            "EC2 spot capacity may be constrained; check NodeClaim status and "
            "AWS EC2 spot availability for the selected AZs.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for pods Running
    print(f"[15] Waiting for {DEPLOYMENT} pods to be Running ...", file=sys.stderr)
    try:
        running_pods = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            LABEL_SELECTOR,
            timeout_s=600,
            interval_s=WAIT_INTERVAL_S,
            kubeconfig=kubeconfig,
        )
        t_pods_running = now_ms()
        result.milestone(
            "node_ready_to_pods_running",
            t_node_ready,
            t_pods_running,
            meta={"running_pods": str(len(running_pods))},
        )
        result.milestone(
            "workload_applied_to_pods_running",
            t_workload_applied,
            t_pods_running,
        )
        print(
            f"[15] {len(running_pods)} pods Running "
            f"(total: {elapsed_human(t_workload_applied, t_pods_running)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            "[15] WARNING: not all pods reached Running within timeout.",
            file=sys.stderr,
        )
        result.milestone(
            "workload_applied_to_pods_running_partial",
            t_workload_applied,
            now_ms(),
        )

    # Capture final state
    final_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    result.extra["final_node_count"] = len(final_names)
    result.extra["new_nodes"] = sorted(final_names - baseline_names)
    result.extra["scheduler"] = "autonode"
    result.extra["capacity_type"] = "spot"
    result.extra["nodepool_name"] = nodepool_name


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = standard_args(
        "Test 15 — Spot instance autoscaling benchmark "
        "(classic + hcp-autonode; hcp is skipped)."
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-spot",
        help="Karpenter NodePool name for spot nodes (hcp-autonode only; default: autonode-spot).",
    )
    parser.add_argument(
        "--spot-max-price",
        default="",
        help=(
            "Maximum spot price per instance-hour (classic only). "
            "Omit to use the on-demand price as the ceiling (default ROSA behaviour)."
        ),
    )
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)

    # Guard: plain HCP is not supported
    if args.cluster_type == "hcp":
        print(
            "[15] SKIP: standard ROSA HCP (without AutoNode) does not support "
            "spot instances on machine pools. "
            "Use cluster-type=classic or cluster-type=hcp-autonode.",
            file=sys.stderr,
        )
        sys.exit(0)

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["capacity_type"] = "spot"

    # Set up cleanup callbacks before touching the cluster
    if args.cluster_type == "classic":
        handle_sigint(
            lambda: cleanup_classic(args.cluster_name, kubeconfig),
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )
    else:
        handle_sigint(
            lambda: cleanup_autonode(args.nodepool_name, kubeconfig),
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    if args.cluster_type == "hcp-autonode" and not args.dry_run:
        _verify_autonode_ready(kubeconfig)

    # Load on-demand baseline for comparison (best-effort)
    baseline = _load_on_demand_baseline(args.run_id, args.cluster_type)
    if baseline:
        print(
            f"[15] On-demand baseline loaded ({len(baseline)} milestones) for comparison.",
            file=sys.stderr,
        )
    result.extra["on_demand_baseline_ms"] = baseline

    # ── Run ───────────────────────────────────────────────────────────────────
    if args.cluster_type == "classic":
        _run_classic(args, kubeconfig, result)
        if not args.dry_run:
            cleanup_classic(args.cluster_name, kubeconfig)
    else:
        _run_autonode(args, kubeconfig, result, nodepool_name=args.nodepool_name)
        if not args.dry_run:
            cleanup_autonode(args.nodepool_name, kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
