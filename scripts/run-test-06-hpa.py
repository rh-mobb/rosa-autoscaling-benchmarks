#!/usr/bin/env python3
"""
scripts/run-test-06-hpa.py

Benchmark: Horizontal Pod Autoscaler response time (Test 06)

Procedure:
  1. Verify VPA operator is installed (warn if missing).
  2. Apply cpu-burner deployment, HPA, and VPA (Off mode).
  3. Wait for the initial pod to be Running and Ready.
  4. Record baseline CPU utilization from HPA status.
  5. Poll HPA until averageUtilization > 50% (metric breach).
  6. Poll until HPA desiredReplicas > initial (scale decision).
  7. Poll until all new pods are Running.
  8. Read VPA recommendation.
  9. Emit milestones and JSON summary.

Cleanup: scale cpu-burner back to 1 replica.
HPA and VPA are left in place for test 08.

Usage:
  python3 scripts/run-test-06-hpa.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp|hcp-autonode> \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
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

TEST_ID = "06-hpa"
NAMESPACE = "benchmark"
DEPLOYMENT = "cpu-burner"
HPA_NAME = "cpu-burner-hpa"
VPA_NAME = "cpu-burner-vpa"
LABEL_SELECTOR = "app=cpu-burner"
HPA_THRESHOLD_PCT = 50

_WORKLOADS = Path(__file__).parent.parent / "manifests" / "workloads"
_AUTOSCALING = Path(__file__).parent.parent / "manifests" / "autoscaling"

MANIFEST_CPU_BURNER = _WORKLOADS / "cpu-burner.yaml"
MANIFEST_CPU_BURNER_KARPENTER = _WORKLOADS / "cpu-burner-karpenter.yaml"
MANIFEST_HPA = _AUTOSCALING / "hpa.yaml"
MANIFEST_VPA = _AUTOSCALING / "vpa.yaml"
MANIFEST_VPA_SUB = _AUTOSCALING / "vpa-operator-subscription.yaml"


def cleanup(kubeconfig: str | None) -> None:
    """Scale cpu-burner back to 1 replica."""
    try:
        oc_lib.scale_deployment(DEPLOYMENT, 1, NAMESPACE, kubeconfig=kubeconfig)
        print("[cleanup] cpu-burner scaled to 1.", file=sys.stderr)
    except Exception as exc:
        print(f"[cleanup] warning: {exc}", file=sys.stderr)


def _check_vpa_operator(kubeconfig: str | None) -> bool:
    """Return True if the VPA operator appears to be running."""
    for ns in ("openshift-vertical-pod-autoscaler", "openshift-operators"):
        try:
            pods = oc_lib.get_pods(ns, kubeconfig=kubeconfig)
            for pod in pods:
                name = pod["metadata"]["name"]
                if "vpa" in name.lower() or "vertical" in name.lower():
                    phase = pod.get("status", {}).get("phase", "")
                    if phase == "Running":
                        return True
        except oc_lib.OcError:
            pass
    return False


def _ensure_vpa_operator(kubeconfig: str | None) -> None:
    """Install VPA operator via OLM subscription if not already running."""
    if _check_vpa_operator(kubeconfig):
        print("[06] VPA operator is running.", file=sys.stderr)
        return

    print(
        "[06] VPA operator not found — applying OLM subscription ...",
        file=sys.stderr,
    )
    oc_lib.apply_manifest(str(MANIFEST_VPA_SUB), kubeconfig=kubeconfig)
    print("[06] Waiting up to 5m for VPA operator to become Ready ...", file=sys.stderr)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if _check_vpa_operator(kubeconfig):
            print("[06] VPA operator is now Running.", file=sys.stderr)
            return
        time.sleep(20)
    print(
        "[06] WARNING: VPA operator still not Running after 5m. "
        "VPA recommendations may not appear in test 07. Continuing ...",
        file=sys.stderr,
    )


def _get_hpa_current_cpu(hpa: dict) -> int | None:
    """Extract the current CPU average utilization % from an HPA object."""
    for metric in hpa.get("status", {}).get("currentMetrics", None) or []:
        if metric.get("type") == "Resource":
            res = metric.get("resource", {})
            if res.get("name") == "cpu":
                return res.get("current", {}).get("averageUtilization")
    return None


def _get_hpa_desired(hpa: dict) -> int:
    return hpa.get("status", {}).get("desiredReplicas", 0)


def _extract_vpa_recommendation(vpa: dict) -> dict:
    """Extract VPA containerRecommendations into a friendly dict."""
    recs = (
        vpa.get("status", {})
        .get("recommendation", {})
        .get("containerRecommendations", None) or []
    )
    result = {}
    for rec in recs:
        container = rec.get("containerName", "unknown")
        result[container] = {
            "lowerBound": rec.get("lowerBound", {}),
            "target": rec.get("target", {}),
            "upperBound": rec.get("upperBound", {}),
            "uncappedTarget": rec.get("uncappedTarget", {}),
        }
    return result


def main() -> None:
    parser = standard_args("Test 06 — HPA response time benchmark.")
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)

    # Select the right workload manifest based on cluster type.
    # hcp-autonode needs nodeAffinity so pods land on Karpenter-managed nodes.
    is_autonode = args.cluster_type == "hcp-autonode"
    cpu_burner_manifest = MANIFEST_CPU_BURNER_KARPENTER if is_autonode else MANIFEST_CPU_BURNER

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )
    result.extra["cpu_burner_manifest"] = cpu_burner_manifest.name

    handle_sigint(lambda: cleanup(kubeconfig), run_id=args.run_id, test_id=TEST_ID, result=result)

    # ── Pre-flight ────────────────────────────────────────────────────────────
    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # ── Step 1 — Ensure VPA operator (Classic / standard HCP only) ───────────
    # VPA is not available on HCP AutoNode clusters.
    if not args.dry_run and not is_autonode:
        _ensure_vpa_operator(kubeconfig)
    elif is_autonode:
        print("[06] Skipping VPA operator check — not available on HCP AutoNode.", file=sys.stderr)

    # ── Step 2 — Apply manifests ──────────────────────────────────────────────
    print(f"[06] Applying {cpu_burner_manifest.name}, HPA manifests ...", file=sys.stderr)
    t_start = now_ms()
    if not args.dry_run:
        oc_lib.apply_manifest(str(cpu_burner_manifest), kubeconfig=kubeconfig)
        oc_lib.apply_manifest(str(MANIFEST_HPA), kubeconfig=kubeconfig)
        if not is_autonode:
            oc_lib.apply_manifest(str(MANIFEST_VPA), kubeconfig=kubeconfig)

    # ── Step 3 — Wait for initial pod Ready ──────────────────────────────────
    print("[06] Waiting for initial cpu-burner pod to be Ready ...", file=sys.stderr)
    try:
        if not args.dry_run:
            oc_lib.wait_for_deployment_ready(DEPLOYMENT, NAMESPACE, timeout_s=300, kubeconfig=kubeconfig)
        t_workload_ready = now_ms()
        result.milestone("manifests_applied_to_workload_ready", t_start, t_workload_ready)
        print(f"[06] cpu-burner ready ({elapsed_human(t_start, t_workload_ready)}).", file=sys.stderr)
    except oc_lib.OcError as exc:
        fatal(str(exc), run_id=args.run_id, test_id=TEST_ID, result=result)

    # ── Step 4 — Baseline HPA state ──────────────────────────────────────────
    initial_replicas = 1
    try:
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        initial_replicas = hpa.get("status", {}).get("currentReplicas", 1)
        baseline_cpu = _get_hpa_current_cpu(hpa)
        print(f"[06] Baseline: {initial_replicas} replicas, CPU={baseline_cpu}%", file=sys.stderr)
        result.extra["initial_replicas"] = initial_replicas
        result.extra["baseline_cpu_pct"] = baseline_cpu
    except oc_lib.OcError as exc:
        print(f"[06] WARNING: Could not read HPA baseline: {exc}", file=sys.stderr)

    # ── Step 5 — Wait for metric breach (CPU > 50%) ───────────────────────────
    print(f"[06] Waiting for HPA CPU utilization > {HPA_THRESHOLD_PCT}% ...", file=sys.stderr)

    t_metric_breach: int | None = None

    def _cpu_breached() -> bool:
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        cpu = _get_hpa_current_cpu(hpa)
        if cpu is not None:
            print(f"[06] HPA CPU: {cpu}%", file=sys.stderr)
            return cpu > HPA_THRESHOLD_PCT
        return False

    try:
        oc_lib.poll_until(_cpu_breached, timeout_s=args.timeout, interval_s=30, label="HPA CPU breach")
        t_metric_breach = now_ms()
        result.milestone("workload_ready_to_metric_breach", t_workload_ready, t_metric_breach)
        print(f"[06] Metric breach at {elapsed_human(t_workload_ready, t_metric_breach)}.", file=sys.stderr)
    except oc_lib.PollTimeout:
        fatal(
            f"CPU utilization never exceeded {HPA_THRESHOLD_PCT}% within timeout. "
            "Check that cpu-burner is generating load (stress-ng running in pods).",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # ── Step 6 — Wait for HPA scale decision ─────────────────────────────────
    print("[06] Waiting for HPA scale decision (desiredReplicas > initial) ...", file=sys.stderr)

    def _hpa_scaled() -> bool:
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        desired = _get_hpa_desired(hpa)
        print(f"[06] HPA desiredReplicas: {desired}", file=sys.stderr)
        return desired > initial_replicas

    try:
        oc_lib.poll_until(_hpa_scaled, timeout_s=600, interval_s=15, label="HPA scale decision")
        t_scale_decision = now_ms()
        result.milestone("metric_breach_to_scale_decision", t_metric_breach, t_scale_decision)
        hpa = oc_lib.get_hpa(HPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
        desired = _get_hpa_desired(hpa)
        result.extra["peak_desired_replicas"] = desired
        print(
            f"[06] HPA decided to scale to {desired} replicas "
            f"({elapsed_human(t_metric_breach, t_scale_decision)}).",
            file=sys.stderr,
        )
    except oc_lib.PollTimeout:
        fatal(
            "HPA did not issue a scale decision within 10m. "
            "Check HPA configuration and metrics-server availability.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # ── Step 7 — Wait for new pods Running ───────────────────────────────────
    print("[06] Waiting for HPA-requested pods to be Running ...", file=sys.stderr)
    try:
        running_pods = oc_lib.wait_for_all_pods_running(
            NAMESPACE,
            LABEL_SELECTOR,
            expected_count=desired,
            timeout_s=600,
            interval_s=15,
            kubeconfig=kubeconfig,
        )
        t_pods_running = now_ms()
        result.milestone("scale_decision_to_pods_running", t_scale_decision, t_pods_running)
        result.milestone(
            "metric_breach_to_pods_running",
            t_metric_breach,
            t_pods_running,
            meta={"pod_count": str(len(running_pods))},
        )
        result.extra["peak_running_replicas"] = len(running_pods)
        print(
            f"[06] {len(running_pods)} pods Running "
            f"(breach→running: {elapsed_human(t_metric_breach, t_pods_running)}).",
            file=sys.stderr,
        )

        # Step 7b — Wait for pods Ready (readiness probes pass / traffic-serving state)
        print("[06] Waiting for HPA pods to be Ready ...", file=sys.stderr)
        try:
            ready_pods = oc_lib.wait_for_all_pods_ready(
                NAMESPACE,
                LABEL_SELECTOR,
                expected_count=desired,
                timeout_s=300,
                interval_s=5,
                kubeconfig=kubeconfig,
            )
            t_pods_ready = now_ms()
            result.milestone("pods_running_to_pods_ready", t_pods_running, t_pods_ready,
                             meta={"ready_pod_count": str(len(ready_pods))})
            result.milestone("metric_breach_to_pods_ready", t_metric_breach, t_pods_ready,
                             meta={"pod_count": str(len(ready_pods))})
            print(
                f"[06] {len(ready_pods)} pods Ready "
                f"(+{elapsed_human(t_pods_running, t_pods_ready)} after Running; "
                f"breach→ready: {elapsed_human(t_metric_breach, t_pods_ready)}).",
                file=sys.stderr,
            )
        except oc_lib.PollTimeout:
            print("[06] WARNING: pods did not all reach Ready within 5m.", file=sys.stderr)
    except oc_lib.PollTimeout:
        print("[06] WARNING: Not all HPA pods reached Running within timeout.", file=sys.stderr)
        t_pods_running = now_ms()

    # ── Step 8 — Collect HPA events ──────────────────────────────────────────
    try:
        hpa_events = [
            ev for ev in oc_lib.get_events(NAMESPACE, kubeconfig=kubeconfig)
            if ev.get("involvedObject", {}).get("kind") == "HorizontalPodAutoscaler"
        ]
        result.extra["hpa_events"] = [
            {"reason": e.get("reason"), "message": e.get("message", "")[:200]}
            for e in hpa_events[-10:]
        ]
    except oc_lib.OcError as exc:
        print(f"[06] WARNING: Could not collect HPA events: {exc}", file=sys.stderr)

    # ── Step 9 — Read VPA recommendation (Classic / standard HCP only) ───────
    if not is_autonode:
        print("[06] Reading VPA recommendation ...", file=sys.stderr)
        try:
            vpa = oc_lib.get_vpa(VPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
            vpa_recs = _extract_vpa_recommendation(vpa)
            result.extra["vpa_recommendations"] = vpa_recs
            print(f"[06] VPA recommendations: {vpa_recs}", file=sys.stderr)
        except oc_lib.OcError as exc:
            print(f"[06] WARNING: Could not read VPA recommendation: {exc}", file=sys.stderr)
    else:
        print("[06] Skipping VPA recommendation read — VPA not available on HCP AutoNode.", file=sys.stderr)

    # Also grab current requests for comparison
    try:
        cpu_burner = oc_lib.run_oc(
            ["get", "deployment", DEPLOYMENT, "-n", NAMESPACE],
            kubeconfig=kubeconfig,
        )
        containers = (
            cpu_burner.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        )
        if containers:
            result.extra["current_requests"] = containers[0].get("resources", {}).get("requests", {})
    except oc_lib.OcError:
        pass

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cleanup(kubeconfig)

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
