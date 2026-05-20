"""
Phase 2 — Workload Observation.

For each workload with autoscaling in Phase 1, this phase:
1. Checks right-sizing using VPA recommendations + oc adm top
2. Queries Prometheus for traffic pattern classification (CoV, autocorrelation)
3. Reads benchmark event data if available for provisioning latency
4. Produces an ObservationResult per workload

Gracefully degrades: if Prometheus is unreachable, findings are marked
confidence=low and the phase continues with only live utilization data.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Optional

from ..lib.patterns import PatternResult, classify_pattern, parse_prometheus_matrix
from ..lib.sizing import (
    parse_cpu_millicores, parse_memory_bytes,
    format_cpu, format_memory,
    PROVISION_TIME_ESTIMATES_S,
)
from ..lib.events_jsonl import BenchmarkLatencies
from .topology import TopologyResult, HPAConfig, VPAConfig


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ContainerResources:
    container: str
    request_cpu_m: float
    request_memory_bytes: float
    limit_cpu_m: float
    limit_memory_bytes: float
    # Live (oc adm top)
    actual_cpu_m: float = 0.0
    actual_memory_bytes: float = 0.0
    # VPA recommendation
    vpa_target_cpu_m: Optional[float] = None
    vpa_target_memory_bytes: Optional[float] = None
    vpa_upper_cpu_m: Optional[float] = None
    vpa_upper_memory_bytes: Optional[float] = None
    # Prometheus p95 over 7d
    p95_cpu_m: Optional[float] = None
    p95_memory_bytes: Optional[float] = None
    # OOM restarts in 7d
    oom_restarts: int = 0


@dataclass
class WorkloadObservation:
    namespace: str
    name: str
    kind: str = "Deployment"
    # Resource right-sizing
    containers: list[ContainerResources] = field(default_factory=list)
    # Traffic pattern (from Prometheus or live top)
    pattern: Optional[PatternResult] = None
    # HPA state snapshot
    hpa_name: Optional[str] = None
    hpa_threshold_pct: Optional[float] = None
    hpa_min: int = 1
    hpa_max: int = 1
    hpa_current: int = 0
    hpa_metric_type: str = ""   # cpu | memory | custom
    # KEDA info
    keda_triggers: list[str] = field(default_factory=list)
    # VPA mode
    vpa_mode: Optional[str] = None
    # Confidence for this workload
    confidence: str = "low"     # high | medium | low
    confidence_note: str = ""
    # Provisioning latency used for sizing
    provision_latency_s: float = 0.0
    provision_latency_source: str = "estimate"


@dataclass
class ObservationResult:
    workloads: list[WorkloadObservation] = field(default_factory=list)
    prometheus_available: bool = False
    prom_endpoint: str = ""
    provision_latency_s: float = 0.0
    provision_latency_source: str = "estimate"
    benchmark_latencies: Optional[BenchmarkLatencies] = None


# ---------------------------------------------------------------------------
# Prometheus helpers
# ---------------------------------------------------------------------------

def _prom_query_range(
    endpoint: str,
    query: str,
    token: Optional[str] = None,
    days: int = 7,
    step: str = "5m",
) -> Optional[list[dict]]:
    """
    Run a Prometheus range query and return the result list, or None on error.
    Handles both http:// and https:// endpoints.
    """
    import time
    end_ts = int(time.time())
    start_ts = end_ts - days * 86400

    base = endpoint if endpoint.startswith("http") else f"https://{endpoint}"
    params = urllib.parse.urlencode({
        "query": query,
        "start": start_ts,
        "end": end_ts,
        "step": step,
    })
    url = f"{base}/api/v1/query_range?{params}"

    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if data.get("status") == "success":
                return data.get("data", {}).get("result", [])
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        pass
    return None


def _prom_query_instant(
    endpoint: str,
    query: str,
    token: Optional[str] = None,
) -> Optional[float]:
    """Run an instant Prometheus query and return the first numeric value."""
    base = endpoint if endpoint.startswith("http") else f"https://{endpoint}"
    params = urllib.parse.urlencode({"query": query})
    url = f"{base}/api/v1/query?{params}"

    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            result = data.get("data", {}).get("result", [])
            if result:
                return float(result[0].get("value", [None, None])[1])
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        pass
    return None


def _discover_prometheus(
    kubeconfig: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """
    Returns (endpoint, token) for a reachable Prometheus instance.
    Priority:
      1. User-workload monitoring route
      2. OTel demo bundled Prometheus
      3. Thanos-querier port-forward (sets up background process, returns localhost:9091)
    """
    env = dict(os.environ)
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    def run(args: list[str]) -> Optional[str]:
        try:
            r = subprocess.run(
                ["oc"] + args, capture_output=True, text=True, timeout=15, env=env
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    # Try thanos-querier route first (standard ROSA)
    route = run([
        "get", "route", "-n", "openshift-monitoring", "thanos-querier",
        "-o", "jsonpath={.spec.host}",
    ])
    if route:
        token = run([
            "create", "token", "-n", "openshift-monitoring",
            "prometheus-k8s", "--duration=1h",
        ])
        endpoint = f"https://{route}"
        # Quick probe
        result = _prom_query_instant(endpoint, "up", token)
        if result is not None:
            return endpoint, token

    # Try OTel demo bundled Prometheus
    route = run([
        "get", "route", "-n", "otel-demo", "otel-demo-prometheus-server",
        "-o", "jsonpath={.spec.host}",
    ])
    if not route:
        route = run([
            "get", "route", "-n", "otel-demo", "prometheus",
            "-o", "jsonpath={.spec.host}",
        ])
    if route:
        endpoint = f"https://{route}"
        result = _prom_query_instant(endpoint, "up", None)
        if result is not None:
            return endpoint, None

    return None, None


# ---------------------------------------------------------------------------
# oc adm top helpers
# ---------------------------------------------------------------------------

def _top_pods(
    namespace: Optional[str] = None,
    kubeconfig: Optional[str] = None,
) -> dict[str, tuple[float, float]]:
    """
    Returns {pod_name: (cpu_m, memory_bytes)} from oc adm top pods.
    """
    env = {**os.environ, **({"KUBECONFIG": kubeconfig} if kubeconfig else {})}
    ns_args = ["-n", namespace] if namespace else ["-A"]
    try:
        r = subprocess.run(
            ["oc", "adm", "top", "pods"] + ns_args + ["--no-headers"],
            capture_output=True, text=True, timeout=30, env=env
        )
        out: dict[str, tuple[float, float]] = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            pod = parts[0] if namespace else parts[1]
            cpu_str = parts[-2]
            mem_str = parts[-1]
            cpu_m = float(cpu_str.rstrip("m")) if cpu_str.endswith("m") else float(cpu_str) * 1000
            mem_b = parse_memory_bytes(mem_str)
            out[pod] = (cpu_m, mem_b)
        return out
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return {}


def _get_deploy_spec(
    namespace: str,
    name: str,
    kubeconfig: Optional[str] = None,
) -> Optional[dict]:
    env = {**os.environ, **({"KUBECONFIG": kubeconfig} if kubeconfig else {})}
    try:
        r = subprocess.run(
            ["oc", "get", "deployment", name, "-n", namespace, "-o", "json"],
            capture_output=True, text=True, timeout=15, env=env
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Phase 2 main entry point
# ---------------------------------------------------------------------------

def observe(
    topology: TopologyResult,
    kubeconfig: Optional[str] = None,
    namespace_filter: Optional[str] = None,
    benchmark_latencies: Optional[BenchmarkLatencies] = None,
) -> ObservationResult:
    obs_result = ObservationResult()

    # Resolve provision latency
    obs_result.provision_latency_s, obs_result.provision_latency_source = \
        _resolve_provision_latency(topology, benchmark_latencies)
    obs_result.benchmark_latencies = benchmark_latencies

    # Discover Prometheus
    prom_endpoint, prom_token = _discover_prometheus(kubeconfig)
    if prom_endpoint:
        obs_result.prometheus_available = True
        obs_result.prom_endpoint = prom_endpoint

    # Get live pod utilization once (amortised across all namespaces)
    live_top = _top_pods(namespace_filter, kubeconfig)

    # Collect all namespaces with HPA/VPA/KEDA to observe
    targets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for h in topology.hpas:
        k = (h.namespace, h.target_name)
        if k not in seen and (not namespace_filter or h.namespace == namespace_filter):
            targets.append(k)
            seen.add(k)
    for v in topology.vpas:
        k = (v.namespace, v.target_name)
        if k not in seen and (not namespace_filter or v.namespace == namespace_filter):
            targets.append(k)
            seen.add(k)
    for kd in topology.keda_objects:
        k = (kd.namespace, kd.target_name)
        if k not in seen and (not namespace_filter or kd.namespace == namespace_filter):
            targets.append(k)
            seen.add(k)

    for ns, name in targets:
        wo = _observe_workload(
            ns, name, topology, obs_result,
            live_top, prom_endpoint, prom_token,
            kubeconfig, obs_result.provision_latency_s,
        )
        obs_result.workloads.append(wo)

    return obs_result


def _resolve_provision_latency(
    topology: TopologyResult,
    benchmark_latencies: Optional[BenchmarkLatencies],
) -> tuple[float, str]:
    """Return (seconds, source_description)."""
    if benchmark_latencies:
        if topology.autoscaler_type == "karpenter" and benchmark_latencies.karpenter_claim_ready_s:
            return benchmark_latencies.karpenter_claim_ready_s, f"measured (run {benchmark_latencies.run_id})"
        if benchmark_latencies.cas_wave_latency_p95_s:
            return benchmark_latencies.cas_wave_latency_p95_s, f"measured (run {benchmark_latencies.run_id})"

    estimate = PROVISION_TIME_ESTIMATES_S.get(topology.cluster_type, 360)
    return float(estimate), f"estimate ({topology.cluster_type} default)"


def _observe_workload(
    ns: str, name: str,
    topology: TopologyResult,
    obs_result: ObservationResult,
    live_top: dict[str, tuple[float, float]],
    prom_endpoint: Optional[str],
    prom_token: Optional[str],
    kubeconfig: Optional[str],
    provision_latency_s: float,
) -> WorkloadObservation:
    wo = WorkloadObservation(
        namespace=ns,
        name=name,
        provision_latency_s=provision_latency_s,
        provision_latency_source=obs_result.provision_latency_source,
    )

    # HPA info
    for h in topology.hpas:
        if h.namespace == ns and h.target_name == name:
            wo.hpa_name = h.name
            wo.hpa_min = h.min_replicas
            wo.hpa_max = h.max_replicas
            wo.hpa_current = h.current_replicas
            for m in h.metrics:
                if m.get("type") == "Resource":
                    wo.hpa_metric_type = m["resource"]["name"]
                    wo.hpa_threshold_pct = m["resource"]["target"].get("averageUtilization")
                elif m.get("type") in ("Pods", "Object", "External"):
                    wo.hpa_metric_type = "custom"
            break

    # KEDA info
    for kd in topology.keda_objects:
        if kd.namespace == ns and kd.target_name == name:
            wo.keda_triggers = kd.triggers
            break

    # VPA mode
    for v in topology.vpas:
        if v.namespace == ns and v.target_name == name:
            wo.vpa_mode = v.update_mode
            break

    # Container resource specs from Deployment
    deploy_spec = _get_deploy_spec(ns, name, kubeconfig)
    if deploy_spec:
        containers = (
            deploy_spec.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        )
        for c in containers:
            reqs = c.get("resources", {}).get("requests", {})
            limits = c.get("resources", {}).get("limits", {})
            cr = ContainerResources(
                container=c["name"],
                request_cpu_m=parse_cpu_millicores(reqs.get("cpu")),
                request_memory_bytes=parse_memory_bytes(reqs.get("memory")),
                limit_cpu_m=parse_cpu_millicores(limits.get("cpu")),
                limit_memory_bytes=parse_memory_bytes(limits.get("memory")),
            )
            # Live utilization (match by pod prefix)
            pod_cpu_m = 0.0
            pod_mem_b = 0.0
            pod_count = 0
            for pod_name, (cpu, mem) in live_top.items():
                if pod_name.startswith(name + "-") or pod_name.startswith(name):
                    pod_cpu_m += cpu
                    pod_mem_b += mem
                    pod_count += 1
            if pod_count > 0:
                cr.actual_cpu_m = pod_cpu_m / pod_count
                cr.actual_memory_bytes = pod_mem_b / pod_count

            # VPA recommendations for this container
            for v in topology.vpas:
                if v.namespace == ns and v.target_name == name:
                    for rec in v.recommendations:
                        if rec.get("containerName") == c["name"]:
                            tgt = rec.get("target", {})
                            ub = rec.get("upperBound", {})
                            cr.vpa_target_cpu_m = parse_cpu_millicores(tgt.get("cpu"))
                            cr.vpa_target_memory_bytes = parse_memory_bytes(tgt.get("memory"))
                            cr.vpa_upper_cpu_m = parse_cpu_millicores(ub.get("cpu"))
                            cr.vpa_upper_memory_bytes = parse_memory_bytes(ub.get("memory"))

            # Prometheus p95 utilization
            if prom_endpoint:
                _enrich_with_prometheus(cr, ns, name, prom_endpoint, prom_token)

            wo.containers.append(cr)

    # Traffic pattern from Prometheus or live top
    if prom_endpoint and wo.hpa_name:
        wo.pattern = _fetch_traffic_pattern(
            ns, wo.hpa_name, prom_endpoint, prom_token
        )

    # Confidence level
    if prom_endpoint and wo.containers and any(c.p95_cpu_m is not None for c in wo.containers):
        wo.confidence = "high"
        wo.confidence_note = "Prometheus 7d history available"
    elif any(c.vpa_target_cpu_m is not None for c in wo.containers):
        wo.confidence = "medium"
        wo.confidence_note = "VPA recommendation available; no Prometheus history"
    else:
        wo.confidence = "low"
        wo.confidence_note = "No Prometheus or VPA data; using live oc adm top only"

    return wo


def _enrich_with_prometheus(
    cr: ContainerResources,
    ns: str,
    deploy: str,
    endpoint: str,
    token: Optional[str],
) -> None:
    cpu_q = (
        f'quantile_over_time(0.95, '
        f'rate(container_cpu_usage_seconds_total{{namespace="{ns}",'
        f'pod=~"{deploy}-.*",container="{cr.container}"}}[5m])[7d:5m])'
    )
    mem_q = (
        f'quantile_over_time(0.95, '
        f'container_memory_working_set_bytes{{namespace="{ns}",'
        f'pod=~"{deploy}-.*",container="{cr.container}"}}[7d])'
    )
    restart_q = (
        f'increase(kube_pod_container_status_restarts_total{{namespace="{ns}",'
        f'pod=~"{deploy}-.*",container="{cr.container}"}}[7d])'
    )

    cpu_val = _prom_query_instant(endpoint, cpu_q, token)
    if cpu_val is not None:
        cr.p95_cpu_m = cpu_val * 1000.0

    mem_val = _prom_query_instant(endpoint, mem_q, token)
    if mem_val is not None:
        cr.p95_memory_bytes = mem_val

    restart_val = _prom_query_instant(endpoint, restart_q, token)
    if restart_val is not None:
        cr.oom_restarts = int(restart_val)


def _fetch_traffic_pattern(
    ns: str,
    hpa_name: str,
    endpoint: str,
    token: Optional[str],
) -> Optional[PatternResult]:
    replica_q = (
        f'kube_horizontalpodautoscaler_status_current_replicas'
        f'{{namespace="{ns}",horizontalpodautoscaler="{hpa_name}"}}'
    )
    result = _prom_query_range(endpoint, replica_q, token, days=7)
    if not result:
        return None

    values = parse_prometheus_matrix(result)
    if not values:
        return None

    scale_events_q = (
        f'changes(kube_horizontalpodautoscaler_status_current_replicas'
        f'{{namespace="{ns}",horizontalpodautoscaler="{hpa_name}"}}[7d])'
    )
    scale_events = _prom_query_instant(endpoint, scale_events_q, token) or 0

    return classify_pattern(values, step_minutes=5, scale_events=int(scale_events))
