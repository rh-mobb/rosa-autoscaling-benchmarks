#!/usr/bin/env python3
"""
scripts/lib/overprovision_sizing.py

Compute ``capacity-filler`` replica count for saturated overprovisioning tests
from **live** pool allocatable CPU/memory and pod requests (excluding the
``benchmark`` namespace so stale test pods do not skew the baseline).
"""

from __future__ import annotations

import math
from typing import Any

from scripts.lib import oc as oc_lib

DEFAULT_EXCLUDE_NAMESPACES = frozenset({"benchmark"})
DEFAULT_MEMORY_RESERVE_MIB = 512
# HPA / deployment steady state before the scripted scale-out burst.
DEFAULT_CPU_BURNER_STEADY_REPLICAS = 1


def compute_saturated_capacity_filler_replicas(
    pool_label_key: str,
    pool_label_value: str,
    *,
    kubeconfig: str | None,
    max_slack_cpu_cores: float,
    pause_replicas: int,
    pause_cpu_millicores: int,
    pause_memory_mib: int,
    cpu_burner_steady_replicas: int = DEFAULT_CPU_BURNER_STEADY_REPLICAS,
    cpu_burner_cpu_millicores: int = 500,
    cpu_burner_memory_mib: int = 128,
    filler_cpu_millicores: int = 400,
    filler_memory_mib: int = 400,
    memory_reserve_mib: int = DEFAULT_MEMORY_RESERVE_MIB,
    exclude_namespaces: frozenset[str] = DEFAULT_EXCLUDE_NAMESPACES,
) -> tuple[int, dict[str, Any]]:
    """
    Return ``(replicas, sizing_dict)`` so that **after** applying pause + steady
    cpu-burner + this many filler pods on the pool, projected CPU slack is at
    or below ``max_slack_cpu_cores``, subject to memory schedulability.

    Raises ``ValueError`` if the pool has no Ready nodes or CPU/memory bounds are
    incompatible (CPU demands more filler replicas than memory allows).
    """
    alloc_mc, alloc_mi, ready_count = oc_lib.get_pool_allocatable_cpu_memory_for_label(
        pool_label_key,
        pool_label_value,
        kubeconfig=kubeconfig,
    )
    if ready_count <= 0:
        msg = (
            f"No Ready nodes with {pool_label_key}={pool_label_value!r} — "
            "cannot size capacity-filler."
        )
        raise ValueError(msg)

    nodes = oc_lib.get_nodes_for_label(pool_label_key, pool_label_value, kubeconfig=kubeconfig)
    ready_names: set[str] = set()
    for node in nodes:
        for cond in node.get("status", {}).get("conditions", []):
            if cond.get("type") == "Ready" and cond.get("status") == "True":
                meta = node.get("metadata") or {}
                name = meta.get("name")
                if name:
                    ready_names.add(name)
                break

    base_mc, base_mi = oc_lib.get_cluster_cpu_memory_requests_on_nodes_excluding_namespaces(
        ready_names,
        set(exclude_namespaces),
        kubeconfig=kubeconfig,
    )

    planned_mc = pause_replicas * pause_cpu_millicores + cpu_burner_steady_replicas * cpu_burner_cpu_millicores
    planned_mi = pause_replicas * pause_memory_mib + cpu_burner_steady_replicas * cpu_burner_memory_mib

    max_slack_mc = max(0, int(max_slack_cpu_cores * 1000))
    need_cpu_mc = alloc_mc - max_slack_mc - base_mc - planned_mc
    f_min_cpu = (
        max(0, math.ceil(need_cpu_mc / filler_cpu_millicores)) if need_cpu_mc > 0 else 0
    )

    avail_filler_mi = alloc_mi - memory_reserve_mib - base_mi - planned_mi
    f_max_mem = max(0, avail_filler_mi // filler_memory_mib)

    if f_min_cpu > f_max_mem:
        msg = (
            f"capacity-filler sizing: CPU needs at least {f_min_cpu} replicas (@{filler_cpu_millicores}m each) "
            f"to reach ≤{max_slack_cpu_cores} cores slack on this pool, but memory allows at most {f_max_mem} "
            f"(alloc {alloc_mi}Mi, reserve {memory_reserve_mib}Mi, base {base_mi}Mi excl. {exclude_namespaces!r}, "
            f"pause+burner {planned_mi}Mi). Shrink the bench pool, change manifest requests, or raise "
            "`--max-slack-cpu-cores`."
        )
        raise ValueError(msg)

    f = min(f_min_cpu, f_max_mem)
    proj_req_mc = base_mc + planned_mc + f * filler_cpu_millicores
    proj_slack_cores = (alloc_mc - proj_req_mc) / 1000.0

    sizing: dict[str, Any] = {
        "pool_label": f"{pool_label_key}={pool_label_value}",
        "ready_node_count": ready_count,
        "allocatable_cpu_millicores": alloc_mc,
        "allocatable_memory_mebibytes": alloc_mi,
        "baseline_cpu_millicores_excl_benchmark": base_mc,
        "baseline_memory_mebibytes_excl_benchmark": base_mi,
        "planned_non_filler_cpu_millicores": planned_mc,
        "planned_non_filler_memory_mebibytes": planned_mi,
        "max_slack_cpu_cores": max_slack_cpu_cores,
        "filler_cpu_millicores_per_replica": filler_cpu_millicores,
        "filler_memory_mebibytes_per_replica": filler_memory_mib,
        "memory_reserve_mebibytes": memory_reserve_mib,
        "exclude_namespaces": sorted(exclude_namespaces),
        "replicas_cpu_lower_bound": f_min_cpu,
        "replicas_memory_upper_bound": f_max_mem,
        "replicas_chosen": f,
        "projected_cpu_slack_cores_after_scale": round(proj_slack_cores, 3),
    }
    return f, sizing
