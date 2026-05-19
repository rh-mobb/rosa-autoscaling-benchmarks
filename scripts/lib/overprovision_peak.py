"""
Periodic cluster sampling during Test 09 / 09b sustained peak (high cpu-burner load).

Polls nodes, HPA replica counts, pause/cpu-burner pod phases, and fleet metrics
so autoscaler behavior during the dwell window can be reconstructed from JSON.
"""

from __future__ import annotations

import sys
import time
from typing import Any

from scripts.lib import oc as oc_lib
from scripts.lib.bench import BenchmarkResult, elapsed_human, now_ms


def _pod_phases(pods: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pod in pods:
        ph = pod.get("status", {}).get("phase") or "Unknown"
        counts[ph] = counts.get(ph, 0) + 1
    return counts


def collect_peak_sample(
    *,
    kubeconfig: str | None,
    namespace: str,
    label_overprov: str,
    label_cpu_burner: str,
    hpa_name: str,
    baseline_sel_key: str,
    baseline_sel_val: str,
    is_autonode: bool,
    nodepool_name: str | None,
    machine_api_ns: str,
) -> dict[str, Any]:
    """One point-in-time snapshot of the cluster during sustained peak."""
    ts = now_ms()
    node_names = sorted(oc_lib.get_node_names(kubeconfig=kubeconfig))
    pause_pods = oc_lib.get_pods(namespace, label_overprov, kubeconfig=kubeconfig)
    cpu_pods = oc_lib.get_pods(namespace, label_cpu_burner, kubeconfig=kubeconfig)
    cur, des = oc_lib.hpa_replica_counts(hpa_name, namespace, kubeconfig=kubeconfig)

    sample: dict[str, Any] = {
        "timestamp_ms": ts,
        "cluster_ready_node_count": oc_lib.get_node_count(kubeconfig=kubeconfig),
        "bench_pool_ready_nodes": oc_lib.get_ready_node_count_for_label(
            baseline_sel_key,
            baseline_sel_val,
            kubeconfig=kubeconfig,
        ),
        "node_names": node_names,
        "hpa_current_replicas": cur,
        "hpa_desired_replicas": des,
        "pause_pods_by_phase": _pod_phases(pause_pods),
        "cpu_burner_pods_by_phase": _pod_phases(cpu_pods),
    }

    if is_autonode and nodepool_name:
        sample["nodeclaim_count"] = oc_lib.get_nodeclaim_count(
            nodepool_name=nodepool_name,
            kubeconfig=kubeconfig,
        )
    else:
        ms = oc_lib.get_machineset_replica_counts(machine_api_ns, kubeconfig=kubeconfig)
        sample["machineset_desired_sum"] = sum(
            int((v or {}).get("desired", 0) or 0) for v in ms.values()
        )
        sample["machineset_replicas"] = {
            k: {
                "desired": (v or {}).get("desired"),
                "ready": (v or {}).get("ready"),
                "available": (v or {}).get("available"),
            }
            for k, v in ms.items()
        }
    return sample


def run_sustained_peak_observation(
    *,
    duration_s: int,
    poll_interval_s: int,
    kubeconfig: str | None,
    namespace: str,
    label_overprov: str,
    label_cpu_burner: str,
    hpa_name: str,
    baseline_sel_key: str,
    baseline_sel_val: str,
    is_autonode: bool,
    nodepool_name: str | None,
    machine_api_ns: str,
    result: BenchmarkResult,
    log_prefix: str,
) -> None:
    """
    Hold load (caller must keep cpu-burner at burst replica count and stress command) and poll.

    Writes ``result.extra["sustained_peak"]`` with samples and adds a milestone for the wall window.
    """
    if duration_s <= 0:
        return

    interval = max(5, poll_interval_s)
    print(
        f"{log_prefix} Sustained peak: polling every {interval}s for {duration_s}s "
        "(cpu-burner remains under load) ...",
        file=sys.stderr,
    )
    t_win_start = now_ms()
    deadline = time.monotonic() + duration_s
    samples: list[dict[str, Any]] = []
    prev_names: list[str] | None = None

    while time.monotonic() < deadline:
        try:
            s = collect_peak_sample(
                kubeconfig=kubeconfig,
                namespace=namespace,
                label_overprov=label_overprov,
                label_cpu_burner=label_cpu_burner,
                hpa_name=hpa_name,
                baseline_sel_key=baseline_sel_key,
                baseline_sel_val=baseline_sel_val,
                is_autonode=is_autonode,
                nodepool_name=nodepool_name,
                machine_api_ns=machine_api_ns,
            )
        except oc_lib.OcError as exc:
            print(f"{log_prefix} sustained-peak poll oc error (continuing): {exc}", file=sys.stderr)
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
            continue

        if prev_names is not None:
            cur_set = set(s["node_names"])
            prev_set = set(prev_names)
            s["nodes_added_vs_prev"] = sorted(cur_set - prev_set)
            s["nodes_removed_vs_prev"] = sorted(prev_set - cur_set)
        prev_names = list(s["node_names"])
        samples.append(s)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))

    t_win_end = now_ms()
    result.milestone("sustained_peak_wall_clock", t_win_start, t_win_end)
    result.extra["sustained_peak"] = {
        "duration_s_requested": duration_s,
        "poll_interval_s": interval,
        "sample_count": len(samples),
        "samples": samples,
    }
    print(
        f"{log_prefix} Sustained peak window done ({len(samples)} samples; "
        f"{elapsed_human(t_win_start, t_win_end)} wall).",
        file=sys.stderr,
    )
