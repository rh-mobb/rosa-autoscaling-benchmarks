#!/usr/bin/env python3
"""
scripts/run-test-10-autonode-scale.py

Benchmark: AutoNode (Karpenter) node provisioning and consolidation (Test 10)

Two trigger modes are available via --trigger-mode:

  pause-pods (default, recommended for comparison with Classic Test 03)
    Phase 1 uses manifests/workloads/karpenter-trigger-100.yaml — the same pause
    image and resource requests as cas-trigger.yaml, with nodeAffinity pinning
    pods to the Karpenter NodePool.  The measurement chain is:
      workload applied → FailedScheduling → NodeClaim → node Ready → pods Running
    This is directly comparable to Test 03 (CAS scale-up).

  direct-scale (original behaviour, Karpenter-only analysis)
    Phase 1 applies autonode-app.yaml and scales replicas directly without
    going through FailedScheduling.  Use this mode to isolate EC2 provisioning
    latency from scheduler detection overhead.

Node sizing rationale (both modes)
---------------------
  m5.xlarge: 4 vCPU capacity, 3500m allocatable (500m reserved by OS/kubelet).
  System DaemonSets consume ~830m, leaving ~2670m for workload pods.
  direct-scale: 1000m CPU/pod → 2 pods per node.
  pause-pods: 500m CPU/pod → multiple pods per node; replica count sized to
              exceed total NodePool capacity and force FailedScheduling.

Procedure (pause-pods mode)
---------
  Phase 0 — Pre-flight
    1. Verify oc login and ec2nodeclass/default READY=True.
    2. Apply nodepool.yaml; wait for NodePool Ready.

  Phase 1 — Initial provision (1:1 with Test 03)
    3. Apply karpenter-trigger-100.yaml (100 pause pods, 500m/512Mi each, Karpenter affinity).
    4. Wait for FailedScheduling event in benchmark namespace.
    5. Wait for first NodeClaim (Karpenter decision <1s).
    6. Wait for first Ready node (~4-5 min EC2 boot).
    7. Wait for first pods Running.
    Milestones: initial.workload_applied_to_failed_scheduling,
                initial.failed_scheduling_to_nodeclaim,
                initial.nodeclaim_to_node_ready,
                initial.node_ready_to_pods_running,
                initial.pending_to_pods_running  (total)

  Phase 2 — Direct replica waves (scale-up, 1 new node each)
    Waves 1-3: +2 replicas per step on autonode-app deployment.
    Milestones: <wave>.scale_to_nodeclaim, .nodeclaim_to_node_ready,
                .node_ready_to_pods_running, .scale_to_pods_running

  Phase 3 — Reverse rollback (scale-down, 1 node consolidated per step)
    Rollback 3→1: -2 replicas per step.
    Milestones: <step>.scale_to_consolidated, .scale_to_pods_stable

  Cleanup
    Delete namespace autonode-test (and benchmark if pause-pods mode) and NodePool.

Usage
-----
  python3 scripts/run-test-10-autonode-scale.py \\
      --cluster-name <name> \\
      --cluster-type hcp-autonode \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--nodepool-name autonode-bench] \\
      [--trigger-mode pause-pods|direct-scale] \\
      [--timeout 5400]
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
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

TEST_ID = "10-autonode-scale"
NAMESPACE = "autonode-test"
NAMESPACE_TRIGGER = "benchmark"   # used by karpenter-trigger-100.yaml (pause-pods mode)
APP_DEPLOYMENT = "autonode-app"
TRIGGER_DEPLOYMENT = "karpenter-trigger"
LABEL_APP = "app=autonode-app"
LABEL_TRIGGER = "app=karpenter-trigger"

MANIFEST_NODEPOOL = REPO_ROOT / "manifests" / "autonode" / "nodepool.yaml"
MANIFEST_APP = REPO_ROOT / "manifests" / "workloads" / "autonode-app.yaml"
MANIFEST_TRIGGER = REPO_ROOT / "manifests" / "workloads" / "karpenter-trigger-100.yaml"

# Scale-up waves: (label, target_replicas)
# Each +2 replicas forces exactly 1 new Karpenter node (1000m CPU/pod, 2/node).
REPLICA_WAVES: list[tuple[str, int]] = [
    ("wave_1", 4),
    ("wave_2", 6),
    ("wave_3", 8),
]

# Rollback steps: reverse of waves above (each -2 replicas removes 1 node).
ROLLBACK_STEPS: list[tuple[str, int]] = [
    ("rollback_3", 6),
    ("rollback_2", 4),
    ("rollback_1", 2),
]

# Timeout per node provision/consolidation step
WAVE_PROVISION_TIMEOUT_S = 600    # 10 min — Karpenter expected ~4-5 min
CONSOLIDATION_TIMEOUT_S = 600     # 10 min per rollback step
WAVE_STABILIZE_S = 30             # pause after each wave before the next


# ── Helpers ───────────────────────────────────────────────────────────────────


def _verify_autonode_ready(kubeconfig: str | None) -> None:
    """Confirm ec2nodeclass/default is READY=True before starting."""
    print("[10] Checking ec2nodeclass/default is Ready ...", file=sys.stderr)
    try:
        ec2nc = oc_lib.run_oc(
            ["get", "ec2nodeclass", "default"],
            kubeconfig=kubeconfig,
        )
        conditions = ec2nc.get("status", {}).get("conditions", [])
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in conditions
        )
        if not ready:
            print(
                "[10] FATAL: ec2nodeclass/default is not Ready. "
                "Ensure AutoNode is enabled: rosa edit cluster --autonode=enabled "
                "and that subnets/security-groups carry the karpenter.sh/discovery tag.",
                file=sys.stderr,
            )
            sys.exit(1)
        print("[10] ec2nodeclass/default is Ready.", file=sys.stderr)
    except oc_lib.OcError as exc:
        print(
            f"[10] FATAL: could not read ec2nodeclass/default — {exc}\n"
            "Is AutoNode enabled on this cluster?",
            file=sys.stderr,
        )
        sys.exit(1)


def _load_cas_baseline(run_id: str) -> dict[str, Any]:
    """
    Read CAS baseline timings from events.jsonl for the same run (tests 03, 04, 08).

    Returns a dict of label → elapsed_ms for comparison in the JSON output.
    Returns an empty dict if events.jsonl is absent or has no CAS milestones.
    """
    if not run_id:
        return {}
    events_path = REPO_ROOT / "results" / run_id / "events.jsonl"
    if not events_path.exists():
        return {}

    cas_labels_of_interest = {
        "03-autoscale-up.cas_triggered_to_node_ready",
        "03-autoscale-up.scheduler_triggered_to_node_ready",  # autonode runs of test 03
        "03-autoscale-up.workload_applied_to_pods_running",
        "04-autoscale-down.workload_removed_to_stable",
        "08-hpa-triggers-cas.hpa_trigger_to_all_running",
        "08-hpa-triggers-cas.scheduler_triggered_to_node_ready",
    }
    baseline: dict[str, Any] = {}
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            label = event.get("label", "")
            if label in cas_labels_of_interest:
                baseline[label] = event.get("elapsed_ms", 0)
    except (OSError, json.JSONDecodeError):
        pass
    return baseline


def cleanup(nodepool_name: str, kubeconfig: str | None, *, trigger_mode: str = "direct-scale") -> None:
    """
    Remove test namespace(s) and NodePool.

    Deletes workload namespaces first (stops pods) then the NodePool so
    Karpenter drains and terminates EC2 instances cleanly.
    """
    namespaces = [NAMESPACE]
    if trigger_mode == "pause-pods":
        namespaces.append(NAMESPACE_TRIGGER)

    for ns in namespaces:
        try:
            oc_lib.run_oc(
                ["delete", "namespace", ns, "--ignore-not-found"],
                json_output=False, kubeconfig=kubeconfig, capture_stderr=False,
            )
            print(f"[cleanup] namespace {ns} removed.", file=sys.stderr)
        except Exception as exc:
            print(f"[cleanup] warning removing namespace {ns}: {exc}", file=sys.stderr)

    try:
        oc_lib.run_oc(
            ["delete", "nodepool", nodepool_name, "--ignore-not-found"],
            json_output=False, kubeconfig=kubeconfig, capture_stderr=False,
        )
        print(f"[cleanup] NodePool {nodepool_name} removed.", file=sys.stderr)
    except Exception as exc:
        print(f"[cleanup] warning removing NodePool: {exc}", file=sys.stderr)


# ── Wave helpers ──────────────────────────────────────────────────────────────


def _wait_nodeclaims_drain(
    *,
    nodepool_name: str,
    target: int = 0,
    timeout_s: int = 900,
    interval_s: int = 15,
    kubeconfig: str | None,
) -> None:
    """
    Block until NodeClaims for ``nodepool_name`` drop to ``target`` or lower.

    Called after scaling the karpenter-trigger to 0 in pause-pods mode so
    that Phase 2 waves start from a clean baseline.  With ``consolidateAfter:
    30s``, Karpenter starts removing nodes very quickly; EC2 termination adds
    1-2 min per batch.  A 15-minute ceiling is generous even for ~20 nodes.
    """
    deadline = time.monotonic() + timeout_s
    print(
        f"[10] Waiting for NodeClaims to drain to ≤{target} "
        f"(timeout {timeout_s}s) ...",
        file=sys.stderr,
    )
    while time.monotonic() < deadline:
        count = oc_lib.get_nodeclaim_count(nodepool_name=nodepool_name, kubeconfig=kubeconfig)
        if count <= target:
            print(f"[10] NodeClaims drained to {count}. Proceeding to Phase 2.", file=sys.stderr)
            return
        print(f"[10] NodeClaims remaining: {count} (waiting for ≤{target}) ...", file=sys.stderr)
        time.sleep(interval_s)
    count = oc_lib.get_nodeclaim_count(nodepool_name=nodepool_name, kubeconfig=kubeconfig)
    print(
        f"[10] WARNING: NodeClaims did not drain within {timeout_s}s "
        f"({count} remaining). Phase 2 baselines may include leftover nodes.",
        file=sys.stderr,
    )


def _run_replica_wave(
    label: str,
    target_replicas: int,
    nodepool_name: str,
    result: BenchmarkResult,
    kubeconfig: str | None,
) -> None:
    """
    Scale app deployment to `target_replicas` (direct scale, no HPA), then
    measure Karpenter provisioning.

    Expects exactly 1 new NodeClaim per wave (because +2 pods = +1 node with
    1000m CPU requests on m5.xlarge).

    Milestones recorded:
      <label>.scale_to_nodeclaim        — deployment scaled → NodeClaim created
      <label>.nodeclaim_to_node_ready   — NodeClaim → new node Ready
      <label>.node_ready_to_pods_running — node Ready → all pods Running
      <label>.scale_to_pods_running     — total: deployment scaled → all pods Running
    """
    baseline_nc_count = oc_lib.get_nodeclaim_count(
        nodepool_name=nodepool_name, kubeconfig=kubeconfig
    )
    baseline_node_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    print(
        f"[10] {label}: scaling app to {target_replicas} replicas "
        f"(baseline: {baseline_nc_count} NodeClaims, {len(baseline_node_names)} nodes) ...",
        file=sys.stderr,
    )
    t_scale = now_ms()
    oc_lib.scale_deployment(APP_DEPLOYMENT, target_replicas, NAMESPACE, kubeconfig=kubeconfig)

    # Wait for new NodeClaim
    t_nodeclaim: int | None = None
    new_nodeclaim_name = ""
    try:
        new_nc = oc_lib.wait_for_new_nodeclaim(
            baseline_nc_count,
            nodepool_name=nodepool_name,
            timeout_s=WAVE_PROVISION_TIMEOUT_S,
            interval_s=5,
            kubeconfig=kubeconfig,
        )
        t_nodeclaim = now_ms()
        new_nodeclaim_name = new_nc.get("metadata", {}).get("name", "")
        result.milestone(
            f"{label}.scale_to_nodeclaim",
            t_scale,
            t_nodeclaim,
            meta={"nodeclaim": new_nodeclaim_name, "target_replicas": str(target_replicas)},
        )
        print(
            f"[10] {label}: NodeClaim {new_nodeclaim_name} created "
            f"({elapsed_human(t_scale, t_nodeclaim)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            f"[10] {label}: WARNING — no new NodeClaim within {WAVE_PROVISION_TIMEOUT_S}s. "
            "Pods may have fit on existing nodes; check CPU requests.",
            file=sys.stderr,
        )

    # Wait for new node Ready
    t_node_ready: int | None = None
    if t_nodeclaim is not None:
        try:
            new_node = oc_lib.wait_for_new_ready_node(
                baseline_node_names,
                timeout_s=WAVE_PROVISION_TIMEOUT_S,
                interval_s=15,
                kubeconfig=kubeconfig,
            )
            t_node_ready = now_ms()
            result.milestone(
                f"{label}.nodeclaim_to_node_ready",
                t_nodeclaim,
                t_node_ready,
                meta={"new_node": new_node},
            )
            print(
                f"[10] {label}: node Ready: {new_node} "
                f"({elapsed_human(t_nodeclaim, t_node_ready)}).",
                file=sys.stderr,
            )
            collect_node_telemetry(
                new_node,
                prefix=f"{TEST_ID}.{label}.new_node",
                since_ms=t_scale,
                run_id=result.run_id,
                cluster_type=result.cluster_type,
                cluster_name=result.cluster_name,
                kubeconfig=kubeconfig,
            )
        except oc_lib.PollTimeout:
            print(
                f"[10] {label}: WARNING — timed out waiting for new node Ready.",
                file=sys.stderr,
            )

    # Wait for all app pods Running
    try:
        running = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            LABEL_APP,
            expected_count=target_replicas,
            timeout_s=WAVE_PROVISION_TIMEOUT_S,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_running = now_ms()
        if t_node_ready is not None:
            result.milestone(
                f"{label}.node_ready_to_pods_running",
                t_node_ready,
                t_running,
                meta={"running_pods": str(len(running))},
            )
        result.milestone(
            f"{label}.scale_to_pods_running",
            t_scale,
            t_running,
            meta={"running_pods": str(len(running)), "target_replicas": str(target_replicas)},
        )
        print(
            f"[10] {label}: {len(running)} pods Running "
            f"(total from scale: {elapsed_human(t_scale, t_running)}).",
            file=sys.stderr,
        )

        # Wait for pods Ready (readiness probes pass / traffic-serving state)
        try:
            ready = oc_lib.wait_for_all_pods_ready(
                NAMESPACE,
                LABEL_APP,
                expected_count=target_replicas,
                timeout_s=300,
                interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_ready = now_ms()
            result.milestone(f"{label}.pods_running_to_pods_ready", t_running, t_ready,
                             meta={"ready_pods": str(len(ready))})
            result.milestone(f"{label}.scale_to_pods_ready", t_scale, t_ready,
                             meta={"ready_pods": str(len(ready)), "target_replicas": str(target_replicas)})
            print(
                f"[10] {label}: {len(ready)} pods Ready "
                f"(+{elapsed_human(t_running, t_ready)} after Running).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print(f"[10] {label}: WARNING — pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        print(
            f"[10] {label}: WARNING — not all {target_replicas} pods reached Running.",
            file=sys.stderr,
        )
        result.milestone(
            f"{label}.scale_to_pods_running_partial",
            t_scale,
            now_ms(),
            meta={"note": "timeout", "target_replicas": str(target_replicas)},
        )


def _run_rollback_step(
    label: str,
    target_replicas: int,
    current_nc_count: int,
    nodepool_name: str,
    result: BenchmarkResult,
    kubeconfig: str | None,
) -> int:
    """
    Scale app deployment down to `target_replicas`, then wait for Karpenter to
    consolidate one node (NodeClaim count drops from `current_nc_count` to
    `current_nc_count - 1`).

    Returns the observed NodeClaim count after consolidation.

    Milestones recorded:
      <label>.scale_to_consolidated  — deployment scaled → NodeClaim count dropped by 1
      <label>.scale_to_pods_stable   — deployment scaled → all pods Running on remaining nodes
    """
    print(
        f"[10] {label}: scaling app down to {target_replicas} replicas "
        f"(current NodeClaims: {current_nc_count}, expecting consolidation to "
        f"{current_nc_count - 1}) ...",
        file=sys.stderr,
    )
    t_scale = now_ms()
    oc_lib.scale_deployment(APP_DEPLOYMENT, target_replicas, NAMESPACE, kubeconfig=kubeconfig)

    # Wait for Karpenter to consolidate 1 node
    # consolidateAfter: 30s means at least 30s before Karpenter fires
    target_nc = current_nc_count - 1
    try:
        final_nc = oc_lib.wait_for_nodeclaim_count_at_most(
            target_nc,
            nodepool_name=nodepool_name,
            timeout_s=CONSOLIDATION_TIMEOUT_S,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_consolidated = now_ms()
        result.milestone(
            f"{label}.scale_to_consolidated",
            t_scale,
            t_consolidated,
            meta={
                "nodeclaims_before": str(current_nc_count),
                "nodeclaims_after": str(final_nc),
                "target_replicas": str(target_replicas),
            },
        )
        print(
            f"[10] {label}: consolidated to {final_nc} NodeClaims "
            f"({elapsed_human(t_scale, t_consolidated)}).",
            file=sys.stderr,
        )
        current_nc_count = final_nc
    except oc_lib.PollTimeout:
        observed = oc_lib.get_nodeclaim_count(nodepool_name=nodepool_name, kubeconfig=kubeconfig)
        print(
            f"[10] {label}: WARNING — consolidation timed out "
            f"({observed} NodeClaims remain, expected ≤{target_nc}).",
            file=sys.stderr,
        )
        result.milestone(
            f"{label}.scale_to_consolidated_partial",
            t_scale,
            now_ms(),
            meta={"remaining_nodeclaims": str(observed), "note": "timeout"},
        )
        current_nc_count = observed

    # Wait for the corresponding EC2 node to disappear from oc get nodes.
    # This is the canonical t_end that matches Test 04's workload_removed_to_stable
    # (Test 04 also measures: remove command → node count drops).
    target_node_count = oc_lib.get_node_count(kubeconfig=kubeconfig) - 1
    try:
        final_node_count = oc_lib.wait_for_node_count_at_most(
            target_node_count,
            timeout_s=CONSOLIDATION_TIMEOUT_S,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_node_removed = now_ms()
        result.milestone(
            f"{label}.scale_to_node_removed",
            t_scale,
            t_node_removed,
            meta={
                "target_node_count": str(target_node_count),
                "final_node_count": str(final_node_count),
                "note": "canonical t_end matching Test 04 workload_removed_to_stable",
            },
        )
        print(
            f"[10] {label}: node removed ({final_node_count} remaining, "
            f"{elapsed_human(t_scale, t_node_removed)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            f"[10] {label}: WARNING — node did not disappear within timeout "
            f"(NodeClaim may already be removed but AWS termination is pending).",
            file=sys.stderr,
        )

    # Wait for pods to be stable on remaining nodes
    try:
        running = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            LABEL_APP,
            expected_count=target_replicas,
            timeout_s=300,
            interval_s=10,
            kubeconfig=kubeconfig,
        )
        t_stable = now_ms()
        result.milestone(
            f"{label}.scale_to_pods_stable",
            t_scale,
            t_stable,
            meta={"running_pods": str(len(running))},
        )
        print(
            f"[10] {label}: {len(running)} pods stable "
            f"({elapsed_human(t_scale, t_stable)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            f"[10] {label}: WARNING — pods did not stabilise within 300s.",
            file=sys.stderr,
        )

    return current_nc_count


# ── Main ──────────────────────────────────────────────────────────────────────


def _phase1_pause_pods(
    nodepool_name: str,
    baseline_node_names: set[str],
    nc_before: int,
    result: BenchmarkResult,
    kubeconfig: str | None,
    dry_run: bool,
    timeout_s: int,
    run_id: str,
) -> None:
    """
    Phase 1 in pause-pods mode.

    Applies karpenter-trigger-100.yaml (100 pause pods, same resource requests as
    cas-trigger.yaml but 5× the replicas for burst provisioning),
    waits for FailedScheduling, then NodeClaim, node Ready, and pods Running.
    Milestone chain mirrors Test 03 exactly for direct comparison.
    """
    print("[10] Phase 1 (pause-pods): applying karpenter-trigger-100.yaml ...", file=sys.stderr)
    t_workload_applied = now_ms()
    if not dry_run:
        oc_lib.apply_manifest(str(MANIFEST_TRIGGER), kubeconfig=kubeconfig)
    print(f"[10] karpenter-trigger applied at {t_workload_applied}.", file=sys.stderr)

    # Wait for FailedScheduling — identical to Test 03 Step 3
    print("[10] Waiting for FailedScheduling event ...", file=sys.stderr)
    try:
        oc_lib.wait_for_event(
            NAMESPACE_TRIGGER,
            "FailedScheduling",
            timeout_s=300,
            interval_s=10,
            kubeconfig=kubeconfig,
        )
        t_failed_scheduling = now_ms()
        result.milestone(
            "initial.workload_applied_to_failed_scheduling",
            t_workload_applied,
            t_failed_scheduling,
        )
        print(
            f"[10] FailedScheduling observed ({elapsed_human(t_workload_applied, t_failed_scheduling)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for FailedScheduling. "
            "Check that karpenter-trigger pods are actually Pending (not scheduling on default workers). "
            "Verify nodeAffinity in karpenter-trigger-100.yaml matches the NodePool name.",
            run_id=run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for first NodeClaim — Karpenter's provisioning decision
    print("[10] Waiting for first NodeClaim ...", file=sys.stderr)
    try:
        first_nc = oc_lib.wait_for_new_nodeclaim(
            nc_before,
            nodepool_name=nodepool_name,
            timeout_s=300,
            interval_s=5,
            kubeconfig=kubeconfig,
        )
        t_nodeclaim = now_ms()
        first_nc_name = first_nc.get("metadata", {}).get("name", "")
        result.milestone(
            "initial.failed_scheduling_to_nodeclaim",
            t_failed_scheduling,
            t_nodeclaim,
            meta={"nodeclaim": first_nc_name},
        )
        result.milestone(
            "initial.pending_to_nodeclaim",
            t_workload_applied,
            t_nodeclaim,
            meta={"nodeclaim": first_nc_name},
        )
        print(
            f"[10] First NodeClaim: {first_nc_name} ({elapsed_human(t_failed_scheduling, t_nodeclaim)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for first NodeClaim after FailedScheduling.",
            run_id=run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for new node Ready
    print("[10] Waiting for first Karpenter node to be Ready ...", file=sys.stderr)
    try:
        first_node = oc_lib.wait_for_new_ready_node(
            baseline_node_names,
            timeout_s=timeout_s,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_node_ready = now_ms()
        result.milestone(
            "initial.nodeclaim_to_node_ready",
            t_nodeclaim,
            t_node_ready,
            meta={"node": first_node},
        )
        result.extra["first_karpenter_node"] = first_node
        print(
            f"[10] First Karpenter node Ready: {first_node} "
            f"({elapsed_human(t_nodeclaim, t_node_ready)}).",
            file=sys.stderr,
        )
        collect_node_telemetry(
            first_node,
            prefix=f"{TEST_ID}.initial.new_node",
            since_ms=t_workload_applied,
            run_id=run_id,
            cluster_type=result.cluster_type,
            cluster_name=result.cluster_name,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            f"Timed out after {timeout_s}s waiting for first Karpenter node to be Ready.",
            run_id=run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for first pods Running (some subset of the 100 trigger pods)
    print("[10] Waiting for karpenter-trigger pods to start Running ...", file=sys.stderr)
    try:
        running = oc_lib.wait_for_all_pods_running(
            NAMESPACE_TRIGGER,
            LABEL_TRIGGER,
            expected_count=None,   # any pods Running is sufficient for the timing milestone
            timeout_s=600,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_pods_running = now_ms()
        result.milestone(
            "initial.node_ready_to_pods_running",
            t_node_ready,
            t_pods_running,
            meta={"running_pods": str(len(running))},
        )
        result.milestone(
            "initial.pending_to_pods_running",
            t_workload_applied,
            t_pods_running,
        )
        print(
            f"[10] {len(running)} trigger pods Running — "
            f"total: {elapsed_human(t_workload_applied, t_pods_running)}.",
            file=sys.stderr,
        )

        # Wait for trigger pods Ready
        try:
            ready = oc_lib.wait_for_all_pods_ready(
                NAMESPACE_TRIGGER,
                LABEL_TRIGGER,
                timeout_s=300,
                interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_pods_ready = now_ms()
            result.milestone("initial.pods_running_to_pods_ready", t_pods_running, t_pods_ready,
                             meta={"ready_pods": str(len(ready))})
            result.milestone("initial.pending_to_pods_ready", t_workload_applied, t_pods_ready)
            print(
                f"[10] {len(ready)} trigger pods Ready "
                f"(+{elapsed_human(t_pods_running, t_pods_ready)} after Running).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[10] WARNING: trigger pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        print("[10] WARNING: karpenter-trigger pods did not reach Running within timeout.", file=sys.stderr)

    # Scale trigger to 0 — leaves namespace/NodePool in place for Phase 2
    print("[10] Scaling karpenter-trigger to 0 (cleanup after phase 1) ...", file=sys.stderr)
    try:
        oc_lib.scale_deployment(TRIGGER_DEPLOYMENT, 0, NAMESPACE_TRIGGER, kubeconfig=kubeconfig)
    except Exception as exc:
        print(f"[10] WARNING: Could not scale karpenter-trigger to 0: {exc}", file=sys.stderr)

    # Wait for Karpenter to consolidate the trigger nodes before Phase 2.
    # Pause-pods trigger creates O(10) nodes to fit 100 pods; Phase 2 replica
    # waves each expect 1 new NodeClaim, so the baseline must be near-zero.
    # consolidateAfter=30s means consolidation starts quickly; EC2 termination
    # adds ~1-2 min per batch -- allow up to 15 min total.
    _wait_nodeclaims_drain(
        nodepool_name=nodepool_name,
        target=0,
        timeout_s=900,
        interval_s=15,
        kubeconfig=kubeconfig,
    )


def _phase1_direct_scale(
    nodepool_name: str,
    baseline_node_names: set[str],
    nc_before: int,
    result: BenchmarkResult,
    kubeconfig: str | None,
    dry_run: bool,
    timeout_s: int,
    run_id: str,
) -> None:
    """
    Phase 1 in direct-scale mode (original behaviour).

    Applies autonode-app.yaml (2 pods, 1000m CPU each) and measures the
    full chain from pod Pending to pods Running without a FailedScheduling step.
    """
    print("[10] Phase 1 (direct-scale): applying autonode-app.yaml ...", file=sys.stderr)
    t_app_applied = now_ms()
    if not dry_run:
        oc_lib.apply_manifest(str(MANIFEST_APP), kubeconfig=kubeconfig)
    print(f"[10] App manifests applied at {t_app_applied}.", file=sys.stderr)

    t_pending = now_ms()
    print("[10] Waiting for first NodeClaim (Karpenter provisioning decision) ...", file=sys.stderr)
    try:
        first_nc = oc_lib.wait_for_new_nodeclaim(
            nc_before,
            nodepool_name=nodepool_name,
            timeout_s=300,
            interval_s=5,
            kubeconfig=kubeconfig,
        )
        t_nodeclaim = now_ms()
        first_nc_name = first_nc.get("metadata", {}).get("name", "")
        result.milestone(
            "initial.pending_to_nodeclaim",
            t_pending,
            t_nodeclaim,
            meta={"nodeclaim": first_nc_name},
        )
        print(
            f"[10] First NodeClaim: {first_nc_name} ({elapsed_human(t_pending, t_nodeclaim)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for first NodeClaim. "
            "Check that AutoNode is enabled and ec2nodeclass/default is Ready, "
            "and that app pods are actually Pending (not scheduling on default workers).",
            run_id=run_id,
            test_id=TEST_ID,
            result=result,
        )

    print("[10] Waiting for first Karpenter node to be Ready ...", file=sys.stderr)
    try:
        first_node = oc_lib.wait_for_new_ready_node(
            baseline_node_names,
            timeout_s=timeout_s,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_node_ready = now_ms()
        result.milestone(
            "initial.nodeclaim_to_node_ready",
            t_nodeclaim,
            t_node_ready,
            meta={"node": first_node},
        )
        result.extra["first_karpenter_node"] = first_node
        print(
            f"[10] First Karpenter node Ready: {first_node} "
            f"({elapsed_human(t_nodeclaim, t_node_ready)}).",
            file=sys.stderr,
        )
        collect_node_telemetry(
            first_node,
            prefix=f"{TEST_ID}.initial.new_node",
            since_ms=t_app_applied,
            run_id=run_id,
            cluster_type=result.cluster_type,
            cluster_name=result.cluster_name,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            f"Timed out after {timeout_s}s waiting for first Karpenter node to be Ready.",
            run_id=run_id,
            test_id=TEST_ID,
            result=result,
        )

    print("[10] Waiting for initial app pods to be Running ...", file=sys.stderr)
    try:
        running = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            LABEL_APP,
            expected_count=2,
            timeout_s=600,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_pods_running = now_ms()
        result.milestone(
            "initial.node_ready_to_pods_running",
            t_node_ready,
            t_pods_running,
            meta={"pod_count": str(len(running))},
        )
        result.milestone(
            "initial.pending_to_pods_running",
            t_pending,
            t_pods_running,
        )
        print(
            f"[10] Initial pods Running — total provision: {elapsed_human(t_pending, t_pods_running)}.",
            file=sys.stderr,
        )

        # Wait for initial app pods Ready
        try:
            ready = oc_lib.wait_for_all_pods_ready(
                NAMESPACE,
                LABEL_APP,
                expected_count=2,
                timeout_s=300,
                interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_pods_ready = now_ms()
            result.milestone("initial.pods_running_to_pods_ready", t_pods_running, t_pods_ready,
                             meta={"ready_pods": str(len(ready))})
            result.milestone("initial.pending_to_pods_ready", t_pending, t_pods_ready)
            print(
                f"[10] {len(ready)} initial pods Ready "
                f"(+{elapsed_human(t_pods_running, t_pods_ready)} after Running).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[10] WARNING: initial app pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        print("[10] WARNING: initial app pods did not reach Running within timeout.", file=sys.stderr)


def main() -> None:
    parser = standard_args(
        "Test 10 — AutoNode (Karpenter) scale-up and consolidation benchmark."
    )
    parser.add_argument(
        "--nodepool-name",
        default="autonode-bench",
        help="Karpenter NodePool name to create/use (default: autonode-bench).",
    )
    parser.add_argument(
        "--trigger-mode",
        default="pause-pods",
        choices=["pause-pods", "direct-scale"],
        help=(
            "Phase 1 trigger mechanism. "
            "'pause-pods' (default): applies karpenter-trigger-100.yaml and waits for "
            "FailedScheduling — directly comparable to Classic Test 03. "
            "'direct-scale': scales autonode-app directly without FailedScheduling "
            "(original behaviour, Karpenter-only analysis)."
        ),
    )
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)
    nodepool_name: str = args.nodepool_name
    trigger_mode: str = args.trigger_mode

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["trigger_mode"] = trigger_mode
    result.extra["scale_down_policy"] = {
        "scheduler": "karpenter",
        "consolidate_after": "30s (nodepool.yaml consolidateAfter)",
        "consolidation_policy": "WhenEmptyOrUnderutilized",
        "note": "t_start = moment oc scale command is issued; t_end = node no longer in oc get nodes",
    }

    handle_sigint(
        lambda: cleanup(nodepool_name, kubeconfig, trigger_mode=trigger_mode),
        run_id=args.run_id,
        test_id=TEST_ID,
        result=result,
    )

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    if not args.dry_run:
        _verify_autonode_ready(kubeconfig)

    # Load CAS baseline for comparison (best-effort)
    cas_baseline = _load_cas_baseline(args.run_id)
    if cas_baseline:
        print(
            f"[10] CAS baseline loaded ({len(cas_baseline)} milestones) for comparison.",
            file=sys.stderr,
        )
    result.extra["cas_baseline_ms"] = cas_baseline

    # ── Phase 0 — NodePool ────────────────────────────────────────────────────
    print(f"[10] Applying NodePool {nodepool_name!r} ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_NODEPOOL), kubeconfig=kubeconfig)
        try:
            oc_lib.wait_for_nodepool_ready(
                nodepool_name, timeout_s=120, interval_s=5, kubeconfig=kubeconfig
            )
        except oc_lib.PollTimeout:
            print(
                "[10] WARNING: NodePool Ready condition not observed within 120s; "
                "continuing — it may still be initializing.",
                file=sys.stderr,
            )
    print(f"[10] NodePool {nodepool_name!r} applied.", file=sys.stderr)

    # ── Phase 1 — Initial provision ───────────────────────────────────────────
    print(f"[10] Phase 1: initial node provision (trigger-mode={trigger_mode}) ...", file=sys.stderr)
    nc_before_app = oc_lib.get_nodeclaim_count(
        nodepool_name=nodepool_name, kubeconfig=kubeconfig
    )
    baseline_node_names = oc_lib.get_node_names(kubeconfig=kubeconfig)

    phase1_kwargs = dict(
        nodepool_name=nodepool_name,
        baseline_node_names=baseline_node_names,
        nc_before=nc_before_app,
        result=result,
        kubeconfig=kubeconfig,
        dry_run=args.dry_run,
        timeout_s=args.timeout,
        run_id=args.run_id,
    )
    if trigger_mode == "pause-pods":
        _phase1_pause_pods(**phase1_kwargs)
    else:
        _phase1_direct_scale(**phase1_kwargs)

    # ── Phase 2 — Direct replica waves (1 new node each) ─────────────────────
    # In pause-pods mode the autonode-app deployment was never created in Phase 1
    # (karpenter-trigger-100.yaml was used instead). Apply it now so the wave scaling works.
    if trigger_mode == "pause-pods" and not args.dry_run:
        check_cmd = ["oc", "get", "deployment", APP_DEPLOYMENT, "-n", NAMESPACE]
        if kubeconfig:
            check_cmd = ["oc", "--kubeconfig", kubeconfig, *check_cmd[1:]]
        check = subprocess.run(check_cmd, capture_output=True)
        if check.returncode != 0:
            print(
                "[10] Phase 2 setup: applying autonode-app.yaml (not present in pause-pods mode) ...",
                file=sys.stderr,
            )
            oc_lib.apply_manifest(str(MANIFEST_APP), kubeconfig=kubeconfig)
            print("[10] autonode-app.yaml applied.", file=sys.stderr)
        else:
            print("[10] autonode-app deployment already present.", file=sys.stderr)

    print(
        f"[10] Phase 2: direct replica waves {[r for _, r in REPLICA_WAVES]} "
        f"(1 new node per wave) ...",
        file=sys.stderr,
    )
    for wave_label, wave_replicas in REPLICA_WAVES:
        if not args.dry_run:
            _run_replica_wave(wave_label, wave_replicas, nodepool_name, result, kubeconfig)
        else:
            print(
                f"[10] [dry-run] would scale app to {wave_replicas} replicas ({wave_label}).",
                file=sys.stderr,
            )
        if WAVE_STABILIZE_S > 0:
            print(
                f"[10] Waiting {WAVE_STABILIZE_S}s before next wave ...",
                file=sys.stderr,
            )
            time.sleep(WAVE_STABILIZE_S)

    peak_nc_count = oc_lib.get_nodeclaim_count(
        nodepool_name=nodepool_name, kubeconfig=kubeconfig
    )
    result.extra["peak_nodeclaim_count"] = peak_nc_count
    print(
        f"[10] Peak NodeClaim count after all waves: {peak_nc_count}.",
        file=sys.stderr,
    )

    # ── Phase 3 — Reverse rollback (1 node consolidated per step) ────────────
    print(
        f"[10] Phase 3: reverse rollback {[r for _, r in ROLLBACK_STEPS]} "
        f"(1 node consolidated per step) ...",
        file=sys.stderr,
    )
    current_nc_count = peak_nc_count
    for step_label, step_replicas in ROLLBACK_STEPS:
        if not args.dry_run:
            current_nc_count = _run_rollback_step(
                step_label,
                step_replicas,
                current_nc_count,
                nodepool_name,
                result,
                kubeconfig,
            )
        else:
            print(
                f"[10] [dry-run] would scale app to {step_replicas} replicas ({step_label}).",
                file=sys.stderr,
            )
        if WAVE_STABILIZE_S > 0:
            print(
                f"[10] Waiting {WAVE_STABILIZE_S}s before next rollback step ...",
                file=sys.stderr,
            )
            time.sleep(WAVE_STABILIZE_S)

    # ── Capture final state ───────────────────────────────────────────────────
    final_nc_count = oc_lib.get_nodeclaim_count(
        nodepool_name=nodepool_name, kubeconfig=kubeconfig
    )
    final_node_count = oc_lib.get_node_count(kubeconfig=kubeconfig)
    result.extra["final_nodeclaim_count"] = final_nc_count
    result.extra["final_node_count"] = final_node_count
    result.extra["nodepool_name"] = nodepool_name

    # ── Cleanup ───────────────────────────────────────────────────────────────
    print("[10] Cleaning up namespace(s) and NodePool ...", file=sys.stderr)
    if not args.dry_run:
        cleanup(nodepool_name, kubeconfig, trigger_mode=trigger_mode)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
