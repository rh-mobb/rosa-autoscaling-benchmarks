"""
Reader for results/<RUN_ID>/events.jsonl — benchmark-measured latency data.

When a run ID is present, the advisor uses measured provisioning latencies
from test milestones instead of default estimates.
"""
from __future__ import annotations
import glob
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BenchmarkLatencies:
    """Provisioning latencies extracted from a benchmark run."""
    run_id: str = ""
    cluster_name: str = ""
    # Phase times in seconds; None means not observed
    cas_wave_latency_p95_s: Optional[float] = None    # tests 03/14
    karpenter_claim_ready_s: Optional[float] = None   # test 10
    hpa_to_all_pods_ready_s: Optional[float] = None  # test 08 cascade
    parallel_node_stagger_s: Optional[float] = None  # test 13
    source_file: str = ""


def _extract_elapsed(events: list[dict], phase: str, step: str) -> Optional[float]:
    """Find the elapsed_s for a specific phase.step milestone."""
    for e in events:
        ep = e.get("phase", "")
        es = e.get("step", "")
        if ep == phase and es == step:
            return e.get("elapsed_s")
        # also match key-style: "phase.step"
        key = e.get("key", "")
        if key == f"{phase}.{step}":
            return e.get("elapsed_s")
    return None


def load_benchmark_latencies(
    results_dir: str = "results",
    cluster_name: str = "",
) -> Optional[BenchmarkLatencies]:
    """
    Scan results/ for events.jsonl files. Returns the most recent matching run.
    If cluster_name is provided, filters to runs for that cluster.
    """
    pattern = os.path.join(results_dir, "*", "events.jsonl")
    candidates = sorted(glob.glob(pattern), reverse=True)

    for candidate in candidates:
        try:
            with open(candidate) as fp:
                events = [json.loads(line) for line in fp if line.strip()]
        except (OSError, json.JSONDecodeError):
            continue

        if not events:
            continue

        run_id = Path(candidate).parent.name
        found_cluster = ""
        for e in events:
            if e.get("cluster_name"):
                found_cluster = e["cluster_name"]
                break

        if cluster_name and found_cluster and found_cluster != cluster_name:
            continue

        lat = BenchmarkLatencies(run_id=run_id, cluster_name=found_cluster, source_file=candidate)

        # CAS scale-up (test 03 / test 14): milestone "wave1.node_ready"
        val = _extract_elapsed(events, "wave1", "node_ready")
        if val is None:
            val = _extract_elapsed(events, "scale_up", "node_ready")
        lat.cas_wave_latency_p95_s = val

        # Karpenter (test 10): milestone "wave1.nodeclaim_ready"
        val = _extract_elapsed(events, "wave1", "nodeclaim_ready")
        if val is None:
            val = _extract_elapsed(events, "provision", "nodeclaim_ready")
        lat.karpenter_claim_ready_s = val

        # HPA cascade (test 08): milestone "cascade.all_pods_ready"
        val = _extract_elapsed(events, "cascade", "all_pods_ready")
        if val is None:
            val = _extract_elapsed(events, "hpa_cascade", "pods_running")
        lat.hpa_to_all_pods_ready_s = val

        # Parallel nodes (test 13): stagger between first and last node ready
        val = _extract_elapsed(events, "parallel", "last_node_ready")
        lat.parallel_node_stagger_s = val

        if any([lat.cas_wave_latency_p95_s, lat.karpenter_claim_ready_s,
                lat.hpa_to_all_pods_ready_s, lat.parallel_node_stagger_s]):
            return lat

    return None
