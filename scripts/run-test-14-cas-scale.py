#!/usr/bin/env python3
"""
scripts/run-test-14-cas-scale.py

Benchmark: CAS progressive scale-up and scale-down (Test 14)

Linked test: This script is the CAS equivalent of run-test-10-autonode-scale.py.
Any changes to wave counts, replica sizing, timeout values, or milestone naming
conventions MUST be reflected in both scripts. See AGENTS.md for the coupling note.

Three phases mirror test 10's structure so results are directly comparable:

  Phase 1 — Initial provision (1:1 with Test 03 / Test 10 Phase 1)
    Apply cas-trigger.yaml (same pause workload as karpenter-trigger.yaml).
    Milestone chain:
      workload applied → FailedScheduling → CAS TriggeredScaleUp → node Ready → pods Running
    Milestones:
      initial.workload_applied_to_failed_scheduling
      initial.failed_scheduling_to_cas_triggered
      initial.cas_triggered_to_node_ready
      initial.node_ready_to_pods_running
      initial.pending_to_pods_running   (total — matches test 10 key stat)

  Phase 2 — Direct replica waves (scale-up, 1 new node each)
    Waves 1-3: +1 replica per step on cas-scale-app deployment (initial replicas=3).
    PodAntiAffinity (required, hostname) forces 1 pod/node; 1600m CPU prevents 2 pods/node.
    Each wave triggers CAS to provision exactly 1 new node, matching test 10's 3 waves.
    Milestones per wave <label>:
      <label>.scale_to_cas_triggered     — deployment scaled → CAS TriggeredScaleUp event
      <label>.cas_triggered_to_node_ready — CAS decision → new node Ready
      <label>.node_ready_to_pods_running  — node Ready → all app pods Running
      <label>.scale_to_pods_running       — total: deployment scaled → all pods Running

  Phase 3 — Reverse rollback (scale-down, 1 node removed per step)
    Rollback 3→1: -2 replicas per step.
    CAS scale-down is gated by scale-down-unneeded-time (10 min) and
    scale-down-delay-after-add (10 min), so each step takes 15–30 min.
    Milestones per step <label>:
      <label>.scale_to_cordon       — deployment scaled → node cordoned by CAS
      <label>.scale_to_node_removed — deployment scaled → node count drops
      <label>.scale_to_pods_stable  — deployment scaled → pods stable on remaining nodes

JSON output schema is intentionally aligned with test 10 wherever CAS has an
equivalent concept, enabling direct side-by-side comparison in the Canvas.

Usage
-----
  python3 scripts/run-test-14-cas-scale.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp> \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--timeout 5400]

Note: --cluster-type hcp-autonode is rejected — use run-test-10-autonode-scale.py
      for AutoNode/Karpenter clusters.
"""

from __future__ import annotations

import json
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

TEST_ID = "14-cas-scale"
NAMESPACE = "cas-scale-test"
NAMESPACE_TRIGGER = "benchmark"
APP_DEPLOYMENT = "cas-scale-app"
TRIGGER_DEPLOYMENT = "cas-trigger"
LABEL_APP = "app=cas-scale-app"
LABEL_TRIGGER = "app=cas-trigger"
MACHINE_API_NS = "openshift-machine-api"

MANIFEST_APP = REPO_ROOT / "manifests" / "workloads" / "cas-scale-app.yaml"
MANIFEST_TRIGGER = REPO_ROOT / "manifests" / "workloads" / "cas-trigger.yaml"

# Scale-up waves: (label, target_replicas)
# cas-scale-app.yaml starts at 3 replicas (1 per baseline standard worker, via PodAntiAffinity).
# Each +1 replica forces exactly 1 new CAS node (1600m CPU/pod, 1/node due to PodAntiAffinity).
# Wave targets 4, 5, 6 → +1 each → 3 consecutive CAS provisions, matching test 10's 3 waves.
REPLICA_WAVES: list[tuple[str, int]] = [
    ("wave_1", 4),
    ("wave_2", 5),
    ("wave_3", 6),
]

# Rollback steps: reverse of waves above (each -1 replica removes 1 node).
ROLLBACK_STEPS: list[tuple[str, int]] = [
    ("rollback_3", 5),
    ("rollback_2", 4),
    ("rollback_1", 3),
]

# Timeouts
WAVE_PROVISION_TIMEOUT_S = 900    # 15 min — CAS expected ~7–10 min (node ready wait)
WAVE_CAS_EVENT_TIMEOUT_S = 120   # 2 min — if CAS hasn't decided in 2 min, pods fit existing capacity
# CAS scale-down: scale-down-unneeded-time (10 min) + scale-down-delay-after-add (10 min)
# + drain + termination — allow up to 40 min per rollback step.
SCALEDOWN_TIMEOUT_S = 2400
WAVE_STABILIZE_S = 30


# ── Helpers ───────────────────────────────────────────────────────────────────


def _is_cordoned(node: dict[str, Any]) -> bool:
    """Return True if a node has SchedulingDisabled (cordoned by CAS pre-drain)."""
    spec = node.get("spec", {})
    return bool(spec.get("unschedulable"))


def _find_cordoned_node(
    baseline_names: set[str],
    kubeconfig: str | None,
) -> str | None:
    """Return the name of the first cordoned node that is not in baseline_names, or None."""
    for node in oc_lib.get_nodes(kubeconfig=kubeconfig):
        name = node.get("metadata", {}).get("name", "")
        if name not in baseline_names and _is_cordoned(node):
            return name
    return None


def _load_karpenter_baseline(run_id: str) -> dict[str, Any]:
    """
    Read Karpenter (test 10) baseline timings from events.jsonl for the same run.

    Returns a dict of label → elapsed_ms for comparison in the JSON output.
    Returns an empty dict if events.jsonl is absent or has no test-10 milestones.
    """
    if not run_id:
        return {}
    events_path = REPO_ROOT / "results" / run_id / "events.jsonl"
    if not events_path.exists():
        return {}

    karpenter_labels_of_interest = {
        "10-autonode-scale.initial.pending_to_pods_running",
        "10-autonode-scale.initial.failed_scheduling_to_nodeclaim",
        "10-autonode-scale.initial.nodeclaim_to_node_ready",
        "10-autonode-scale.wave_1.scale_to_pods_running",
        "10-autonode-scale.wave_2.scale_to_pods_running",
        "10-autonode-scale.wave_3.scale_to_pods_running",
        "10-autonode-scale.rollback_3.scale_to_consolidated",
        "10-autonode-scale.rollback_2.scale_to_consolidated",
        "10-autonode-scale.rollback_1.scale_to_consolidated",
        "10-autonode-scale.rollback_3.scale_to_node_removed",
    }
    baseline: dict[str, Any] = {}
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            label = event.get("label", "")
            if label in karpenter_labels_of_interest:
                baseline[label] = event.get("elapsed_ms", 0)
    except (OSError, ValueError):
        pass
    return baseline


def cleanup(kubeconfig: str | None) -> None:
    """Remove test namespaces. Idempotent — safe to call multiple times."""
    for ns in [NAMESPACE, NAMESPACE_TRIGGER]:
        try:
            oc_lib.run_oc(
                ["delete", "namespace", ns, "--ignore-not-found"],
                json_output=False,
                kubeconfig=kubeconfig,
                capture_stderr=False,
            )
            print(f"[cleanup] namespace {ns} removed.", file=sys.stderr)
        except Exception as exc:
            print(f"[cleanup] warning removing namespace {ns}: {exc}", file=sys.stderr)


# ── Wave helpers ──────────────────────────────────────────────────────────────


def _run_replica_wave(
    label: str,
    target_replicas: int,
    baseline_node_names: set[str],
    result: BenchmarkResult,
    kubeconfig: str | None,
) -> set[str]:
    """
    Scale cas-scale-app to target_replicas, then measure CAS provisioning.

    Expects exactly 1 new node per wave (1000m CPU requests on m5.xlarge →
    2 pods per node → each +2 replicas = +1 node).

    Milestones recorded (mirrors test 10 _run_replica_wave naming):
      <label>.scale_to_cas_triggered     — deployment scaled → CAS TriggeredScaleUp event
      <label>.cas_triggered_to_node_ready — CAS decision → new node Ready
      <label>.node_ready_to_pods_running  — node Ready → all app pods Running
      <label>.scale_to_pods_running       — total: deployment scaled → all pods Running

    Returns the updated set of known node names (baseline + new node).
    """
    current_node_count = len(baseline_node_names)
    print(
        f"[14] {label}: scaling app to {target_replicas} replicas "
        f"(baseline: {current_node_count} nodes) ...",
        file=sys.stderr,
    )
    t_scale = now_ms()
    oc_lib.scale_deployment(APP_DEPLOYMENT, target_replicas, NAMESPACE, kubeconfig=kubeconfig)

    # Wait for CAS scale-up decision.
    # Use a short timeout: if no CAS event in 2 min, pods fit existing capacity
    # and no new node is needed — skip straight to pod-running wait.
    # not_before_ms filters out stale events from earlier phases/waves.
    t_cas_triggered: int | None = None
    try:
        cas_event = oc_lib.wait_for_event(
            MACHINE_API_NS,
            ["TriggeredScaleUp", "ScaledUpGroup"],
            timeout_s=WAVE_CAS_EVENT_TIMEOUT_S,
            interval_s=10,
            kubeconfig=kubeconfig,
            not_before_ms=t_scale - 10_000,  # allow 10s clock skew
        )
        t_cas_triggered = now_ms()
        result.milestone(
            f"{label}.scale_to_cas_triggered",
            t_scale,
            t_cas_triggered,
            meta={
                "cas_event": cas_event.get("reason", ""),
                "cas_message": cas_event.get("message", "")[:200],
                "target_replicas": str(target_replicas),
            },
        )
        print(
            f"[14] {label}: CAS {cas_event.get('reason')} "
            f"({elapsed_human(t_scale, t_cas_triggered)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            f"[14] {label}: no CAS scale-up event within {WAVE_CAS_EVENT_TIMEOUT_S}s — "
            "pods fit existing capacity; skipping new-node wait.",
            file=sys.stderr,
        )
        result.milestone(
            f"{label}.scale_fits_existing_capacity",
            t_scale,
            now_ms(),
            meta={"note": "no CAS event — pods scheduled on existing nodes",
                  "target_replicas": str(target_replicas)},
        )

    # Wait for new Ready node — only when CAS actually fired a scale-up decision.
    # If no CAS event, pods fit existing capacity and there is no new node to wait for.
    t_node_ready: int | None = None
    new_node = ""
    if t_cas_triggered is not None:
        try:
            new_node = oc_lib.wait_for_new_ready_node(
                baseline_node_names,
                timeout_s=WAVE_PROVISION_TIMEOUT_S,
                interval_s=20,
                kubeconfig=kubeconfig,
            )
            t_node_ready = now_ms()
            result.milestone(
                f"{label}.cas_triggered_to_node_ready",
                t_cas_triggered,
                t_node_ready,
                meta={"new_node": new_node},
            )
            print(
                f"[14] {label}: node Ready: {new_node} "
                f"({elapsed_human(t_cas_triggered, t_node_ready)}).",
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
                f"[14] {label}: WARNING — timed out waiting for new node Ready.",
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
            f"[14] {label}: {len(running)} pods Running "
            f"(total from scale: {elapsed_human(t_scale, t_running)}).",
            file=sys.stderr,
        )

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
                f"[14] {label}: {len(ready)} pods Ready "
                f"(+{elapsed_human(t_running, t_ready)} after Running).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print(f"[14] {label}: WARNING — pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        print(
            f"[14] {label}: WARNING — not all {target_replicas} pods reached Running.",
            file=sys.stderr,
        )
        result.milestone(
            f"{label}.scale_to_pods_running_partial",
            t_scale,
            now_ms(),
            meta={"note": "timeout", "target_replicas": str(target_replicas)},
        )

    updated_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    return updated_names


def _run_rollback_step(
    label: str,
    target_replicas: int,
    current_node_count: int,
    current_node_names: set[str],
    result: BenchmarkResult,
    kubeconfig: str | None,
) -> tuple[int, set[str]]:
    """
    Scale cas-scale-app down to target_replicas, then wait for CAS to remove a node.

    CAS gates scale-down behind scale-down-unneeded-time (10 min default) and
    scale-down-delay-after-add (10 min default). Each rollback step therefore
    takes 15–30 min — the deliberate contrast with Karpenter's 30s consolidation.

    Milestones (mirrors test 10 _run_rollback_step naming where possible):
      <label>.scale_to_cordon       — deployment scaled → CAS cordons a node
      <label>.scale_to_node_removed — deployment scaled → node count drops by 1
      <label>.scale_to_pods_stable  — deployment scaled → pods stable on remaining nodes

    Returns (updated_node_count, updated_node_names).
    """
    target_node_count = current_node_count - 1
    print(
        f"[14] {label}: scaling app down to {target_replicas} replicas "
        f"(current nodes: {current_node_count}, expecting CAS to remove 1 "
        f"in ~15–30 min) ...",
        file=sys.stderr,
    )
    t_scale = now_ms()
    oc_lib.scale_deployment(APP_DEPLOYMENT, target_replicas, NAMESPACE, kubeconfig=kubeconfig)

    # Wait for CAS to cordon a node — earliest detectable scale-down signal.
    # CAS cordons briefly (~30–60s) before draining and deleting; poll at 10s to avoid missing it.
    # Also break early if the node count already dropped to target (cordon window was missed).
    t_cordon: int | None = None
    deadline = time.monotonic() + SCALEDOWN_TIMEOUT_S
    while time.monotonic() < deadline:
        current_count = oc_lib.get_node_count(kubeconfig=kubeconfig)
        if current_count <= target_node_count:
            print(
                f"[14] {label}: node count already at {current_count} (≤{target_node_count}) — "
                "cordon window was missed; recording node-removed time.",
                file=sys.stderr,
            )
            t_cordon = now_ms()
            result.milestone(
                f"{label}.scale_to_node_removed",
                t_scale,
                t_cordon,
                meta={
                    "nodes_before": str(current_node_count),
                    "nodes_after": str(current_count),
                    "target_replicas": str(target_replicas),
                    "note": "cordon window missed (30s poll); node_removed captured at next poll",
                },
            )
            print(
                f"[14] {label}: node removed ({current_count} remaining, "
                f"{elapsed_human(t_scale, t_cordon)}).",
                file=sys.stderr,
            )
            current_node_count = current_count
            break
        cordoned = _find_cordoned_node(current_node_names, kubeconfig)
        if cordoned:
            t_cordon = now_ms()
            result.milestone(
                f"{label}.scale_to_cordon",
                t_scale,
                t_cordon,
                meta={
                    "cordoned_node": cordoned,
                    "note": (
                        "CAS cordon precedes drain; "
                        "scale-down-unneeded-time (~10 min) + scale-down-delay-after-add (~10 min) "
                        "elapsed before this milestone"
                    ),
                },
            )
            print(
                f"[14] {label}: CAS cordoned {cordoned} "
                f"({elapsed_human(t_scale, t_cordon)}).",
                file=sys.stderr,
            )
            break
        remaining = deadline - time.monotonic()
        print(
            f"[14] {label}: waiting for CAS cordon "
            f"({int(remaining / 60)}m remaining, current nodes: {current_count}) ...",
            file=sys.stderr,
        )
        time.sleep(10)
    else:
        print(
            f"[14] {label}: WARNING — no cordon observed within {SCALEDOWN_TIMEOUT_S}s; "
            "continuing to watch for node removal ...",
            file=sys.stderr,
        )
        t_cordon = now_ms()

    # Wait for node count to drop — only if we didn't already record removal via missed-cordon path.
    # canonical t_end matching test 04 workload_removed_to_stable and test 10 rollback.
    node_removed_already = oc_lib.get_node_count(kubeconfig=kubeconfig) <= target_node_count
    remaining_s = max(60, int(deadline - time.monotonic()))
    if not node_removed_already:
        try:
            final_node_count = oc_lib.wait_for_node_count_at_most(
                target_node_count,
                timeout_s=remaining_s,
                interval_s=10,
                kubeconfig=kubeconfig,
            )
            t_node_removed = now_ms()
            result.milestone(
                f"{label}.scale_to_node_removed",
                t_scale,
                t_node_removed,
                meta={
                    "nodes_before": str(current_node_count),
                    "nodes_after": str(final_node_count),
                    "target_replicas": str(target_replicas),
                    "note": "canonical t_end matching test 04 workload_removed_to_stable and test 10 rollback",
                },
            )
            print(
                f"[14] {label}: node removed ({final_node_count} remaining, "
                f"{elapsed_human(t_scale, t_node_removed)}).",
                file=sys.stderr,
            )
            current_node_count = final_node_count
        except oc_lib.PollTimeout:
            observed = oc_lib.get_node_count(kubeconfig=kubeconfig)
            print(
                f"[14] {label}: WARNING — node did not disappear within timeout "
                f"({observed} nodes remain, expected ≤{target_node_count}).",
                file=sys.stderr,
            )
            result.milestone(
                f"{label}.scale_to_node_removed_partial",
                t_scale,
                now_ms(),
                meta={"remaining_nodes": str(observed), "note": "timeout"},
            )
            current_node_count = observed

    # Wait for pods to stabilise on remaining nodes.
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
            f"[14] {label}: {len(running)} pods stable "
            f"({elapsed_human(t_scale, t_stable)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            f"[14] {label}: WARNING — pods did not stabilise within 300s.",
            file=sys.stderr,
        )

    updated_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    return current_node_count, updated_names


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = standard_args(
        "Test 14 — CAS progressive scale-up and scale-down benchmark (CAS equivalent of test 10)."
    )
    args = parser.parse_args()

    if args.cluster_type == "hcp-autonode":
        print(
            "[14] FATAL: --cluster-type hcp-autonode is not supported by test 14. "
            "Use run-test-10-autonode-scale.py for AutoNode/Karpenter clusters.",
            file=sys.stderr,
        )
        sys.exit(1)

    kubeconfig = resolve_kubeconfig(args)

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["scale_down_policy"] = {
        "scheduler": "cas",
        "scale_down_unneeded_time": "10m (ROSA default)",
        "scale_down_delay_after_add": "10m (ROSA default)",
        "note": (
            "t_start = moment oc scale command is issued; "
            "t_cordon = CAS sets SchedulingDisabled; "
            "t_end = node no longer in oc get nodes"
        ),
    }

    handle_sigint(
        lambda: cleanup(kubeconfig),
        run_id=args.run_id,
        test_id=TEST_ID,
        result=result,
    )

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # Load Karpenter baseline from test 10 for comparison (best-effort)
    karpenter_baseline = _load_karpenter_baseline(args.run_id)
    if karpenter_baseline:
        print(
            f"[14] Karpenter baseline loaded ({len(karpenter_baseline)} milestones) for comparison.",
            file=sys.stderr,
        )
    result.extra["karpenter_baseline_ms"] = karpenter_baseline

    # ── Phase 1 — Initial provision ───────────────────────────────────────────
    print("[14] Phase 1: initial provision (cas-trigger.yaml — mirrors test 03) ...", file=sys.stderr)
    baseline_node_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    baseline_node_count = len(baseline_node_names)

    # Record the pre-Phase-1 standard worker count so Phase 2 can drain back to it.
    # Standard nodes are identified by the pool-type=standard label.
    _all_nodes_pre = oc_lib.get_nodes(kubeconfig=kubeconfig)
    _standard_pre = {
        n.get("metadata", {}).get("name", "")
        for n in _all_nodes_pre
        if n.get("metadata", {}).get("labels", {}).get("pool-type") == "standard"
        and any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in n.get("status", {}).get("conditions", [])
        )
    }
    baseline_standard_node_count = len(_standard_pre)
    # All nodes that are NOT standard workers — used to identify new standard nodes in drain wait.
    baseline_non_standard_nodes = baseline_node_names - _standard_pre

    print(
        f"[14] Baseline: {baseline_node_count} Ready nodes total, "
        f"{baseline_standard_node_count} standard workers: {sorted(_standard_pre)}",
        file=sys.stderr,
    )
    result.extra["baseline_standard_node_count"] = baseline_standard_node_count

    t_workload_applied = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_TRIGGER), kubeconfig=kubeconfig)
    print(f"[14] cas-trigger applied at {t_workload_applied}.", file=sys.stderr)

    # Wait for FailedScheduling
    print("[14] Waiting for FailedScheduling event ...", file=sys.stderr)
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
            f"[14] FailedScheduling observed ({elapsed_human(t_workload_applied, t_failed_scheduling)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "Timed out waiting for FailedScheduling. "
            "Check that cas-trigger replicas exceed available node capacity and "
            "that nodes carry the pool-type=standard label.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for CAS scale-up decision.
    # not_before_ms ensures we only match events generated after the trigger was applied.
    print("[14] Waiting for CAS scale-up decision event ...", file=sys.stderr)
    t_cas_triggered = now_ms()
    try:
        cas_event = oc_lib.wait_for_event(
            MACHINE_API_NS,
            ["TriggeredScaleUp", "ScaledUpGroup"],
            timeout_s=600,
            interval_s=15,
            kubeconfig=kubeconfig,
            not_before_ms=t_workload_applied - 10_000,  # allow 10s clock skew
        )
        t_cas_triggered = now_ms()
        result.milestone(
            "initial.failed_scheduling_to_cas_triggered",
            t_failed_scheduling,
            t_cas_triggered,
            meta={
                "cas_event": cas_event.get("reason", ""),
                "cas_message": cas_event.get("message", "")[:200],
            },
        )
        print(
            f"[14] CAS {cas_event.get('reason')} observed "
            f"({elapsed_human(t_failed_scheduling, t_cas_triggered)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        print(
            "[14] WARNING: No CAS scale-up event found in openshift-machine-api within 600s; "
            "continuing to watch for new node ...",
            file=sys.stderr,
        )

    # Wait for new node Ready
    print("[14] Waiting for first new node to be Ready ...", file=sys.stderr)
    try:
        first_node = oc_lib.wait_for_new_ready_node(
            baseline_node_names,
            timeout_s=args.timeout,
            interval_s=20,
            kubeconfig=kubeconfig,
        )
        t_node_ready = now_ms()
        result.milestone(
            "initial.cas_triggered_to_node_ready",
            t_cas_triggered,
            t_node_ready,
            meta={"node": first_node},
        )
        result.extra["first_new_node"] = first_node
        print(
            f"[14] First new node Ready: {first_node} "
            f"({elapsed_human(t_cas_triggered, t_node_ready)}).",
            file=sys.stderr,
        )
        collect_node_telemetry(
            first_node,
            prefix=f"{TEST_ID}.initial.new_node",
            since_ms=t_workload_applied,
            run_id=args.run_id,
            cluster_type=args.cluster_type,
            cluster_name=args.cluster_name,
            kubeconfig=kubeconfig,
        )
    except oc_lib.PollTimeout:
        fatal(
            f"Timed out after {args.timeout}s waiting for first new node Ready.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # Wait for cas-trigger pods Running
    print("[14] Waiting for cas-trigger pods to start Running ...", file=sys.stderr)
    try:
        running = oc_lib.wait_for_all_pods_running(
            NAMESPACE_TRIGGER,
            LABEL_TRIGGER,
            expected_count=None,
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
            f"[14] {len(running)} trigger pods Running — "
            f"total: {elapsed_human(t_workload_applied, t_pods_running)}.",
            file=sys.stderr,
        )

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
        except oc_lib.PollTimeout:
            print("[14] WARNING: trigger pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        print("[14] WARNING: cas-trigger pods did not reach Running within timeout.", file=sys.stderr)

    # Scale trigger to 0 and remove the namespace before Phase 2.
    # The cas-scale-app waves use a separate namespace so there is no interference.
    print("[14] Scaling cas-trigger to 0 (cleanup after Phase 1) ...", file=sys.stderr)
    try:
        oc_lib.scale_deployment(TRIGGER_DEPLOYMENT, 0, NAMESPACE_TRIGGER, kubeconfig=kubeconfig)
    except Exception as exc:
        print(f"[14] WARNING: could not scale cas-trigger to 0: {exc}", file=sys.stderr)

    # Remove trigger namespace so its pods don't consume capacity during Phase 2.
    try:
        oc_lib.run_oc(
            ["delete", "namespace", NAMESPACE_TRIGGER, "--ignore-not-found"],
            json_output=False,
            kubeconfig=kubeconfig,
            capture_stderr=False,
        )
        print("[14] benchmark namespace removed (Phase 1 cleanup).", file=sys.stderr)
    except Exception as exc:
        print(f"[14] WARNING: could not remove benchmark namespace: {exc}", file=sys.stderr)

    # ── Phase 2 — Direct replica waves (1 new node each) ─────────────────────
    # Wait for CAS to drain any extra nodes provisioned in Phase 1 back to
    # baseline before starting the replica waves.  Without this, the waves may
    # fit on existing extra capacity and never trigger new provisioning.
    # Use the original_standard_node_count (pre-Phase-1) as the target.
    print(
        f"[14] Phase 2 setup: waiting for CAS to drain Phase-1 extra nodes "
        f"back to {baseline_standard_node_count} standard workers ...",
        file=sys.stderr,
    )
    drain_deadline = time.monotonic() + 1800   # allow up to 30 min for drain
    while time.monotonic() < drain_deadline and not args.dry_run:
        current_standard = len([
            n for n in oc_lib.get_node_names(kubeconfig=kubeconfig)
            if n not in baseline_non_standard_nodes
        ])
        if current_standard <= baseline_standard_node_count:
            print(
                f"[14] Standard workers drained to {current_standard} "
                f"(baseline). Starting Phase 2.",
                file=sys.stderr,
            )
            break
        print(
            f"[14] {current_standard} standard workers (waiting for "
            f"≤{baseline_standard_node_count}) ...",
            file=sys.stderr,
        )
        time.sleep(30)
    else:
        if not args.dry_run:
            print(
                "[14] WARNING: standard workers did not drain to baseline within 30 min; "
                "Phase 2 wave provisioning may be skipped if existing capacity is sufficient.",
                file=sys.stderr,
            )

    print("[14] Phase 2 setup: applying cas-scale-app.yaml ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_APP), kubeconfig=kubeconfig)

    # Re-snapshot node names after Phase 1 drain and app apply.
    current_node_names = oc_lib.get_node_names(kubeconfig=kubeconfig)
    current_node_count = len(current_node_names)
    print(
        f"[14] Phase 2: direct replica waves {[r for _, r in REPLICA_WAVES]} "
        f"(+1 replica per wave, 1 new CAS node each via PodAntiAffinity, current: {current_node_count} nodes) ...",
        file=sys.stderr,
    )

    for wave_label, wave_replicas in REPLICA_WAVES:
        if not args.dry_run:
            current_node_names = _run_replica_wave(
                wave_label, wave_replicas, current_node_names, result, kubeconfig
            )
            current_node_count = len(current_node_names)
        else:
            print(
                f"[14] [dry-run] would scale app to {wave_replicas} replicas ({wave_label}).",
                file=sys.stderr,
            )
        if WAVE_STABILIZE_S > 0:
            print(f"[14] Waiting {WAVE_STABILIZE_S}s before next wave ...", file=sys.stderr)
            time.sleep(WAVE_STABILIZE_S)

    result.extra["peak_node_count"] = current_node_count
    print(
        f"[14] Peak node count after all waves: {current_node_count}.",
        file=sys.stderr,
    )

    # ── Phase 3 — Reverse rollback (1 node removed per step) ─────────────────
    print(
        f"[14] Phase 3: reverse rollback {[r for _, r in ROLLBACK_STEPS]} "
        f"(1 CAS node removed per step — expect ~15–30 min each due to "
        f"scale-down-unneeded-time + scale-down-delay-after-add) ...",
        file=sys.stderr,
    )
    for step_label, step_replicas in ROLLBACK_STEPS:
        if not args.dry_run:
            current_node_count, current_node_names = _run_rollback_step(
                step_label,
                step_replicas,
                current_node_count,
                current_node_names,
                result,
                kubeconfig,
            )
        else:
            print(
                f"[14] [dry-run] would scale app to {step_replicas} replicas ({step_label}).",
                file=sys.stderr,
            )
        if WAVE_STABILIZE_S > 0:
            print(
                f"[14] Waiting {WAVE_STABILIZE_S}s before next rollback step ...",
                file=sys.stderr,
            )
            time.sleep(WAVE_STABILIZE_S)

    # ── Capture final state ───────────────────────────────────────────────────
    final_node_count = oc_lib.get_node_count(kubeconfig=kubeconfig)
    result.extra["final_node_count"] = final_node_count
    result.extra["baseline_node_count"] = baseline_node_count

    # ── Cleanup ───────────────────────────────────────────────────────────────
    print("[14] Cleaning up namespace(s) ...", file=sys.stderr)
    if not args.dry_run:
        cleanup(kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
