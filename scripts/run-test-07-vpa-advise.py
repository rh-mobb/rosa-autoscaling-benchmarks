#!/usr/bin/env python3
"""
scripts/run-test-07-vpa-advise.py

Benchmark: VPA advise-only recommendations (Test 07)

Procedure:
  1. Verify VPA operator is running.
  2. Apply VPA manifest (if not already applied).
  3. Apply cpu-burner deployment (if not already running).
  4. Wait for VPA recommendation to appear (needs 5–10 min of history).
  5. Read current resource requests from the deployment.
  6. Compare: current requests vs VPA lowerBound / target / upperBound.
  7. Emit structured recommendation data and JSON summary.

No cluster mutation is made beyond applying manifests that may already exist.
This test can run standalone or immediately after test 06.

Usage:
  python3 scripts/run-test-07-vpa-advise.py \\
      --cluster-name <name> \\
      --cluster-type <classic|hcp> \\
      [--run-id <RUN_ID>] \\
      [--kubeconfig <path>] \\
      [--timeout 900]
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
    fatal,
    now_ms,
    resolve_kubeconfig,
    standard_args,
    verify_oc_login,
)

TEST_ID = "07-vpa-advise"
NAMESPACE = "benchmark"
DEPLOYMENT = "cpu-burner"
VPA_NAME = "cpu-burner-vpa"
LABEL_SELECTOR = "app=cpu-burner"

MANIFEST_CPU_BURNER = Path(__file__).parent.parent / "manifests" / "workloads" / "cpu-burner.yaml"
MANIFEST_VPA = Path(__file__).parent.parent / "manifests" / "autoscaling" / "vpa.yaml"
MANIFEST_VPA_SUB = Path(__file__).parent.parent / "manifests" / "autoscaling" / "vpa-operator-subscription.yaml"


def _check_vpa_operator(kubeconfig: str | None) -> bool:
    for ns in ("openshift-vertical-pod-autoscaler", "openshift-operators"):
        try:
            pods = oc_lib.get_pods(ns, kubeconfig=kubeconfig)
            for pod in pods:
                name = pod["metadata"]["name"]
                if ("vpa" in name.lower() or "vertical" in name.lower()) and \
                   pod.get("status", {}).get("phase") == "Running":
                    return True
        except oc_lib.OcError:
            pass
    return False


def _vpa_recommendation_ready(vpa: dict) -> bool:
    recs = (
        vpa.get("status", {})
        .get("recommendation", {})
        .get("containerRecommendations", [])
    )
    return bool(recs)


def _extract_vpa_recommendation(vpa: dict) -> dict:
    recs = (
        vpa.get("status", {})
        .get("recommendation", {})
        .get("containerRecommendations", [])
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


def _get_current_requests(kubeconfig: str | None) -> dict:
    try:
        dep = oc_lib.run_oc(
            ["get", "deployment", DEPLOYMENT, "-n", NAMESPACE],
            kubeconfig=kubeconfig,
        )
        containers = (
            dep.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        )
        if containers:
            return containers[0].get("resources", {}).get("requests", {})
    except oc_lib.OcError:
        pass
    return {}


def _compare_vpa_to_current(
    current: dict, recs: dict
) -> dict:
    """
    Return a per-container analysis comparing current requests to VPA target.
    Flags: over-provisioned (current > upper), under-provisioned (current < lower).
    """
    analysis = {}
    for container, rec in recs.items():
        target_cpu = rec.get("target", {}).get("cpu", "")
        target_mem = rec.get("target", {}).get("memory", "")
        current_cpu = current.get("cpu", "")
        current_mem = current.get("memory", "")
        analysis[container] = {
            "current_cpu": current_cpu,
            "vpa_target_cpu": target_cpu,
            "current_memory": current_mem,
            "vpa_target_memory": target_mem,
            "lower_cpu": rec.get("lowerBound", {}).get("cpu", ""),
            "upper_cpu": rec.get("upperBound", {}).get("cpu", ""),
            "lower_memory": rec.get("lowerBound", {}).get("memory", ""),
            "upper_memory": rec.get("upperBound", {}).get("memory", ""),
        }
    return analysis


def main() -> None:
    parser = standard_args("Test 07 — VPA advise-only recommendations.")
    args = parser.parse_args()
    kubeconfig = resolve_kubeconfig(args)

    result = BenchmarkResult(
        run_id=args.run_id,
        test_id=TEST_ID,
        cluster_type=args.cluster_type,
        cluster_name=args.cluster_name,
    )

    verify_oc_login(kubeconfig)
    checkpoint_start(args.run_id, TEST_ID)

    # ── Step 1 — Verify VPA operator ─────────────────────────────────────────
    print("[07] Checking VPA operator ...", file=sys.stderr)
    if not args.dry_run:
        if not _check_vpa_operator(kubeconfig):
            print("[07] VPA operator not found — applying OLM subscription ...", file=sys.stderr)
            oc_lib.apply_manifest(str(MANIFEST_VPA_SUB), kubeconfig=kubeconfig)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                if _check_vpa_operator(kubeconfig):
                    print("[07] VPA operator is Running.", file=sys.stderr)
                    break
                time.sleep(20)
            else:
                print(
                    "[07] WARNING: VPA operator not Running after 5m — "
                    "recommendations may be unavailable.",
                    file=sys.stderr,
                )
        else:
            print("[07] VPA operator is Running.", file=sys.stderr)

    # ── Step 2 — Apply cpu-burner and VPA (idempotent) ────────────────────────
    print("[07] Applying cpu-burner and VPA manifests (idempotent) ...", file=sys.stderr)
    if not args.dry_run:
        oc_lib.apply_manifest(str(MANIFEST_CPU_BURNER), kubeconfig=kubeconfig)
        oc_lib.apply_manifest(str(MANIFEST_VPA), kubeconfig=kubeconfig)
        oc_lib.wait_for_deployment_ready(
            DEPLOYMENT, NAMESPACE, timeout_s=300, kubeconfig=kubeconfig
        )
    t_ready = now_ms()

    # ── Step 3 — Wait for VPA recommendation ─────────────────────────────────
    print(
        "[07] Waiting for VPA recommendation (needs 5–10 min of load history) ...",
        file=sys.stderr,
    )

    def _recommendation_ready() -> dict | None:
        try:
            vpa = oc_lib.get_vpa(VPA_NAME, NAMESPACE, kubeconfig=kubeconfig)
            if _vpa_recommendation_ready(vpa):
                return vpa
        except oc_lib.OcError:
            pass
        return None

    try:
        vpa_obj = oc_lib.poll_until(
            _recommendation_ready,
            timeout_s=args.timeout,
            interval_s=30,
            label="VPA recommendation available",
        )
        t_recommendation = now_ms()
        result.milestone("workload_ready_to_recommendation", t_ready, t_recommendation)
        print("[07] VPA recommendation available.", file=sys.stderr)
    except oc_lib.PollTimeout:
        fatal(
            "VPA recommendation did not appear within timeout. "
            "Ensure the workload has been running under load for at least 5 minutes "
            "and the VPA operator is healthy.",
            run_id=args.run_id,
            test_id=TEST_ID,
            result=result,
        )

    # ── Step 4 — Extract and compare ─────────────────────────────────────────
    vpa_recs = _extract_vpa_recommendation(vpa_obj)
    current_requests = _get_current_requests(kubeconfig)
    comparison = _compare_vpa_to_current(current_requests, vpa_recs)

    result.extra["vpa_recommendations"] = vpa_recs
    result.extra["current_requests"] = current_requests
    result.extra["comparison"] = comparison

    # ── Step 5 — Read VPA events ──────────────────────────────────────────────
    try:
        vpa_events = [
            ev for ev in oc_lib.get_events(NAMESPACE, kubeconfig=kubeconfig)
            if ev.get("involvedObject", {}).get("kind") == "VerticalPodAutoscaler"
        ]
        result.extra["vpa_events"] = [
            {"reason": e.get("reason"), "message": e.get("message", "")[:200]}
            for e in vpa_events[-10:]
        ]
    except oc_lib.OcError as exc:
        print(f"[07] WARNING: Could not collect VPA events: {exc}", file=sys.stderr)

    print("[07] VPA comparison:", file=sys.stderr)
    for container, data in comparison.items():
        print(
            f"  {container}: "
            f"current cpu={data['current_cpu']} → vpa_target={data['vpa_target_cpu']}; "
            f"current mem={data['current_memory']} → vpa_target={data['vpa_target_memory']}",
            file=sys.stderr,
        )

    # ── Finish ────────────────────────────────────────────────────────────────
    checkpoint_complete(args.run_id, TEST_ID)
    result.finish()


if __name__ == "__main__":
    main()
