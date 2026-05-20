"""
Balloon pod sizing formulas and resource quantity parsing.
"""
from __future__ import annotations
import math
import re


def parse_cpu_millicores(value: str | None) -> float:
    """Convert a Kubernetes CPU quantity string to millicores (float)."""
    if not value:
        return 0.0
    value = str(value).strip()
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000.0


def parse_memory_bytes(value: str | None) -> float:
    """Convert a Kubernetes memory quantity string to bytes (float)."""
    if not value:
        return 0.0
    value = str(value).strip()
    suffixes = {
        "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40,
        "K": 10**3,  "M": 10**6,  "G": 10**9,  "T": 10**12,
    }
    for suffix, factor in suffixes.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * factor
    return float(value)


def format_cpu(millicores: float) -> str:
    if millicores < 1000:
        return f"{int(millicores)}m"
    return f"{millicores / 1000:.2f}"


def format_memory(bytes_val: float) -> str:
    for unit, factor in [("Gi", 2**30), ("Mi", 2**20), ("Ki", 2**10)]:
        if bytes_val >= factor:
            return f"{bytes_val / factor:.0f}{unit}"
    return f"{int(bytes_val)}"


def balloon_replicas(
    provision_time_s: float,
    burst_rate: float,
) -> int:
    """
    Number of balloon pod replicas needed to cover one full provision cycle.

    Args:
        provision_time_s: Node provisioning latency in seconds (measured or estimated).
        burst_rate: Maximum replica delta observed in a single HPA scaling event.

    Returns:
        Minimum balloon replica count that provides headroom for one provision cycle.
    """
    if provision_time_s <= 0 or burst_rate <= 0:
        return 1
    return max(1, math.ceil(provision_time_s / 60.0 * burst_rate))


def balloon_resources(
    pod_cpu_m: float,
    pod_memory_bytes: float,
    replicas: int,
) -> dict[str, str]:
    """Compute total balloon pod resource requests."""
    return {
        "cpu": format_cpu(pod_cpu_m * replicas),
        "memory": format_memory(pod_memory_bytes * replicas),
    }


# Provision time estimates when no benchmark data is available
PROVISION_TIME_ESTIMATES_S = {
    "classic":      360,  # CAS on Classic ~6 min
    "hcp":          240,  # CAS on HCP ~4 min
    "hcp-autonode": 150,  # Karpenter on HCP ~2.5 min
}
