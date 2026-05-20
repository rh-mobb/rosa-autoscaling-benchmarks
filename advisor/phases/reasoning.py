"""
Phase 3 — Reasoning and Recommendation Engine.

Pure logic: takes TopologyResult + ObservationResult, answers seven classification
questions per workload, and maps answers to the R0-R10 recommendation catalog.
No I/O. Returns a list of Recommendation objects.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .topology import TopologyResult, StructuralFinding
from .observation import ObservationResult, WorkloadObservation, ContainerResources
from ..lib.sizing import (
    parse_cpu_millicores, parse_memory_bytes,
    format_cpu, format_memory,
    balloon_replicas, balloon_resources,
    PROVISION_TIME_ESTIMATES_S,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Recommendation:
    workload: str                # "namespace/name"
    rec_id: str                  # R0 .. R10
    finding_type: str
    severity: str                # critical | warning | info
    category: str                # performance | cost
    evidence_source: str         # vpa_recommendation | prometheus_query | kubernetes_event | config_inspection
    evidence_detail: str
    metric_value: str
    recommendation: str
    expected_improvement: str
    yaml_delta: str
    confidence: str              # high | medium | low
    confidence_note: str
    benchmark_reference: str     # test number that backs the improvement claim
    # Internal classification answers used to reach this rec
    _classification: dict = field(default_factory=dict)


# R8 (spot) and R9 (ARM64) are cost optimizations. R0 over-provisioned is also cost.
# Everything else is a performance/reliability concern.
def _category(rec_id: str, finding_type: str = "") -> str:
    if rec_id in ("R8", "R9"):
        return "cost"
    if rec_id == "R0" and "over_provisioned" in finding_type:
        return "cost"
    return "performance"


@dataclass
class ReasoningResult:
    recommendations: list[Recommendation] = field(default_factory=list)
    cluster_recs: list[Recommendation] = field(default_factory=list)   # infra-level
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _ratio(actual: Optional[float], request: Optional[float]) -> Optional[float]:
    if not request or not actual:
        return None
    return request / actual if actual > 0 else None


def _classify_workload(
    wo: WorkloadObservation,
) -> dict:
    """Answer Q1-Q7 for a workload. Returns a dict of answers."""
    q: dict = {}

    # Q1: Right-sizing
    q["q1_over"] = False
    q["q1_under"] = False
    for cr in wo.containers:
        # Use VPA target as authoritative; fall back to p95 from Prometheus; then live top
        actual_cpu = cr.vpa_target_cpu_m or cr.p95_cpu_m or cr.actual_cpu_m
        actual_mem = cr.vpa_target_memory_bytes or cr.p95_memory_bytes or cr.actual_memory_bytes
        if cr.request_cpu_m > 0 and actual_cpu and actual_cpu > 0:
            ratio_cpu = cr.request_cpu_m / actual_cpu
            if ratio_cpu > 2.0:
                q["q1_over"] = True
            if ratio_cpu < 1.1:
                q["q1_under"] = True
        if cr.oom_restarts > 0:
            q["q1_under"] = True
    q["q1_oom_kills"] = sum(c.oom_restarts for c in wo.containers)

    # Q2: HPA headroom
    q["q2_threshold_high"] = (
        wo.hpa_threshold_pct is not None and wo.hpa_threshold_pct >= 70
        and wo.hpa_metric_type == "cpu"
    )
    q["q2_max_hit"] = (
        wo.hpa_current > 0 and wo.hpa_current >= wo.hpa_max
    )

    # Q3: Overflow (from topology findings — passed in separately)
    q["q3_overflow"] = False   # populated by caller
    q["q3_notrigger"] = False  # populated by caller

    # Q4: Latency budget (provisioning time vs acceptable degradation)
    q["q4_latency_s"] = wo.provision_latency_s

    # Q5: Traffic pattern
    if wo.pattern:
        q["q5_classification"] = wo.pattern.classification
        q["q5_cov"] = wo.pattern.cov
        q["q5_daily"] = wo.pattern.daily_pattern
        q["q5_spike_prone"] = wo.pattern.classification in ("spike_prone", "moderate_burst")
        q["q5_predictable"] = wo.pattern.classification == "predictable_peak"
    else:
        q["q5_classification"] = "unknown"
        q["q5_cov"] = 0.0
        q["q5_daily"] = False
        q["q5_spike_prone"] = False
        q["q5_predictable"] = False

    # Q6: Interruption tolerance (heuristic: stateless if no VolumeClaimTemplates)
    q["q6_stateless"] = True   # conservative assumption; could be refined
    q["q6_has_keda"] = bool(wo.keda_triggers)

    # Q7: Multi-arch (cannot determine without manifest inspection; flag as unknown)
    q["q7_multi_arch"] = None

    return q


# ---------------------------------------------------------------------------
# Recommendation generators
# ---------------------------------------------------------------------------

def _r0_rightsize(
    wo: WorkloadObservation,
    cr: ContainerResources,
    q: dict,
    confidence: str,
    confidence_note: str,
) -> Optional[Recommendation]:
    if not (q["q1_over"] or q["q1_under"]):
        return None

    workload = f"{wo.namespace}/{wo.name}"
    actual_cpu = cr.vpa_target_cpu_m or cr.p95_cpu_m or cr.actual_cpu_m
    actual_mem = cr.vpa_target_memory_bytes or cr.p95_memory_bytes or cr.actual_memory_bytes

    if q["q1_under"] or cr.oom_restarts > 0:
        direction = "under-provisioned"
        severity = "critical"
        new_cpu = max(cr.request_cpu_m, (actual_cpu or cr.request_cpu_m) * 1.3) if actual_cpu else cr.request_cpu_m * 1.5
        new_mem = max(cr.request_memory_bytes, (actual_mem or cr.request_memory_bytes) * 1.3) if actual_mem else cr.request_memory_bytes * 1.5
        expected = "Eliminate OOMKill restarts; stable scheduling"
    else:
        direction = "over-provisioned"
        severity = "warning"
        new_cpu = (actual_cpu or cr.request_cpu_m) * 1.3
        new_mem = (actual_mem or cr.request_memory_bytes) * 1.3
        ratio_cpu = cr.request_cpu_m / actual_cpu if actual_cpu else 1.0
        expected = f"~{ratio_cpu:.1f}x more pods per node; ~{100 - 100/ratio_cpu:.0f}% fewer CAS triggers"

    evidence_src = "vpa_recommendation" if cr.vpa_target_cpu_m else \
                   "prometheus_query" if cr.p95_cpu_m else "kubernetes_event"
    metric_val = (
        f"request={format_cpu(cr.request_cpu_m)} cpu, {format_memory(cr.request_memory_bytes)} mem | "
        f"VPA target={format_cpu(cr.vpa_target_cpu_m)} cpu" if cr.vpa_target_cpu_m
        else f"request={format_cpu(cr.request_cpu_m)} cpu | actual p95={format_cpu(actual_cpu or 0)}"
    )

    yaml_delta = f"""\
# Patch {wo.namespace}/{wo.name} container {cr.container}
# oc set resources deployment/{wo.name} -n {wo.namespace} \\
#   -c {cr.container} \\
#   --requests=cpu={format_cpu(new_cpu)},memory={format_memory(int(new_mem))} \\
#   --limits=cpu={format_cpu(new_cpu * 2)},memory={format_memory(int(new_mem * 1.5))}
spec:
  template:
    spec:
      containers:
      - name: {cr.container}
        resources:
          requests:
            cpu: "{format_cpu(new_cpu)}"
            memory: "{format_memory(int(new_mem))}"
          limits:
            cpu: "{format_cpu(new_cpu * 2)}"
            memory: "{format_memory(int(new_mem * 1.5))}"\
"""

    finding_type_r0 = f"{'under' if q['q1_under'] else 'over'}_provisioned_requests"
    return Recommendation(
        workload=workload,
        rec_id="R0",
        finding_type=finding_type_r0,
        category=_category("R0", finding_type_r0),
        severity=severity,
        evidence_source=evidence_src,
        evidence_detail=f"Container {cr.container} is {direction}",
        metric_value=metric_val,
        recommendation=f"Update resource requests for container {cr.container} in {workload}",
        expected_improvement=expected,
        yaml_delta=yaml_delta,
        confidence=confidence,
        confidence_note=confidence_note,
        benchmark_reference="Test 07 (VPA advise)",
        _classification=q,
    )


def _r1_tune_hpa_threshold(
    wo: WorkloadObservation, q: dict, confidence: str, confidence_note: str
) -> Optional[Recommendation]:
    if not q["q2_threshold_high"]:
        return None
    workload = f"{wo.namespace}/{wo.name}"
    new_thresh = 55 if (wo.provision_latency_s or 0) > 120 else 60

    yaml_delta = f"""\
# Lower HPA threshold to give scale headroom before saturation
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {wo.hpa_name}
  namespace: {wo.namespace}
spec:
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: {new_thresh}\
"""
    return Recommendation(
        workload=workload,
        rec_id="R1",
        finding_type="hpa_threshold_high",
        category="performance",
        severity="warning",
        evidence_source="config_inspection",
        evidence_detail=f"HPA threshold is {wo.hpa_threshold_pct}% — pods are nearly saturated before HPA fires",
        metric_value=f"averageUtilization={wo.hpa_threshold_pct}%",
        recommendation=f"Lower HPA CPU threshold to {new_thresh}% to create scale headroom",
        expected_improvement="Pods scale before hitting saturation; p99 latency stays flat during scale events",
        yaml_delta=yaml_delta,
        confidence=confidence,
        confidence_note=confidence_note,
        benchmark_reference="Test 06 (HPA)",
        _classification=q,
    )


def _r2_raise_max_replicas(
    wo: WorkloadObservation, q: dict, confidence: str, confidence_note: str
) -> Optional[Recommendation]:
    if not q["q2_max_hit"]:
        return None
    workload = f"{wo.namespace}/{wo.name}"
    new_max = wo.hpa_max * 2

    yaml_delta = f"""\
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {wo.hpa_name}
  namespace: {wo.namespace}
spec:
  maxReplicas: {new_max}\
"""
    return Recommendation(
        workload=workload,
        rec_id="R2",
        finding_type="hpa_max_replicas_capped",
        category="performance",
        severity="critical",
        evidence_source="config_inspection",
        evidence_detail=f"HPA is at maxReplicas={wo.hpa_max} — scale-out is blocked",
        metric_value=f"current={wo.hpa_current}, max={wo.hpa_max}",
        recommendation=f"Raise HPA maxReplicas to {new_max} to unblock horizontal scale-out",
        expected_improvement="Removes artificial scale ceiling; HPA can grow with actual demand",
        yaml_delta=yaml_delta,
        confidence="high",
        confidence_note="Directly observed from HPA status",
        benchmark_reference="Test 06 (HPA)",
        _classification=q,
    )


def _r3_r4_balloon_pods(
    wo: WorkloadObservation, q: dict, confidence: str, confidence_note: str
) -> list[Recommendation]:
    recs: list[Recommendation] = []
    if not (q["q3_overflow"] or q["q5_spike_prone"]):
        return recs

    workload = f"{wo.namespace}/{wo.name}"
    provision_s = wo.provision_latency_s or PROVISION_TIME_ESTIMATES_S.get("classic", 360)

    # Estimate burst rate from HPA history (fallback: assume +3 replicas/event)
    burst_rate = 3.0
    if wo.pattern and wo.pattern.scale_event_count > 0 and wo.hpa_max > wo.hpa_min:
        burst_rate = float(wo.hpa_max - wo.hpa_min)

    n_balloons = balloon_replicas(provision_s, burst_rate)

    # Resource per balloon pod = same as workload (will be preempted by it)
    pod_cpu_m = 0.0
    pod_mem_b = 0.0
    for cr in wo.containers:
        pod_cpu_m += cr.request_cpu_m or 100.0
        pod_mem_b += cr.request_memory_bytes or 128 * 2**20

    recs.append(Recommendation(
        workload=workload,
        rec_id="R3",
        finding_type="missing_balloon_pods",
        category="performance",
        severity="warning",
        evidence_source="kubernetes_event",
        evidence_detail="FailedScheduling events observed; no pre-reserved node headroom",
        metric_value=f"provision_time={provision_s:.0f}s, burst_rate={burst_rate:.0f} replicas/event",
        recommendation=f"Add {n_balloons} balloon (pause) pods on low-priority PriorityClass to pre-reserve node headroom",
        expected_improvement=f"Pod pending time drops from ~{provision_s:.0f}s to <5s when HPA fires",
        yaml_delta=_balloon_yaml(wo.namespace, wo.name, n_balloons, pod_cpu_m, pod_mem_b),
        confidence=confidence,
        confidence_note=confidence_note,
        benchmark_reference="Tests 09/11/12 (overprovisioning, planned surge, sudden spike)",
        _classification=q,
    ))

    recs.append(Recommendation(
        workload=workload,
        rec_id="R4",
        finding_type="balloon_pod_sizing",
        category="performance",
        severity="info",
        evidence_source="config_inspection",
        evidence_detail=f"Balloon count derived from provision time ({provision_s:.0f}s) and burst rate ({burst_rate:.0f})",
        metric_value=f"n_balloons={n_balloons}",
        recommendation=f"Size balloon Deployment to {n_balloons} replicas (formula: ceil({provision_s:.0f}s / 60s × {burst_rate:.0f}))",
        expected_improvement="Headroom covers exactly one provision cycle; minimal waste",
        yaml_delta=f"# See R3 YAML above — set replicas: {n_balloons}",
        confidence=confidence,
        confidence_note=f"{confidence_note}; balloon sizing uses provision latency from {wo.provision_latency_source}",
        benchmark_reference="Test 12 (sudden spike degradation window)",
        _classification=q,
    ))
    return recs


def _balloon_yaml(ns: str, deploy: str, n: int, cpu_m: float, mem_b: float) -> str:
    cpu_str = format_cpu(cpu_m)
    mem_str = format_memory(int(mem_b))
    return f"""\
# 1. PriorityClass for balloon pods (apply once per cluster)
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: balloon-low-priority
value: -1
preemptionPolicy: Never
globalDefault: false
description: "Low-priority pause pods for pre-reserved node headroom"
---
# 2. Balloon pod Deployment — preempted instantly when real pods need the capacity
apiVersion: apps/v1
kind: Deployment
metadata:
  name: balloon-{deploy}
  namespace: {ns}
spec:
  replicas: {n}
  selector:
    matchLabels:
      app: balloon-{deploy}
  template:
    metadata:
      labels:
        app: balloon-{deploy}
    spec:
      priorityClassName: balloon-low-priority
      terminationGracePeriodSeconds: 0
      containers:
      - name: pause
        image: registry.k8s.io/pause:3.9
        resources:
          requests:
            cpu: "{cpu_str}"
            memory: "{mem_str}"\
"""


def _r5_switch_karpenter(
    wo: WorkloadObservation,
    topology: TopologyResult,
    q: dict,
    confidence: str,
    confidence_note: str,
) -> Optional[Recommendation]:
    if topology.autoscaler_type == "karpenter":
        return None
    if not q["q3_overflow"]:
        return None
    provision_s = wo.provision_latency_s or 360.0

    yaml_delta = """\
# Migrate to ROSA HCP with AutoNode (Karpenter).
# See: make create-hcp-autonode
# Karpenter provisions nodes in ~2.5 min vs ~6 min for CAS on Classic.
# With balloon pods (R3): effective latency drops to <5s.
#
# Step 1 — enable AutoNode on existing HCP:
#   rosa edit cluster --cluster=<name> --autonode=enabled
# Step 2 — apply NodePool with required instance families:
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: default
spec:
  template:
    spec:
      requirements:
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["m", "c", "r"]
      - key: karpenter.k8s.aws/instance-generation
        operator: Gt
        values: ["5"]
  limits:
    cpu: "1000"
  disruption:
    consolidationPolicy: WhenUnderutilized\
"""
    return Recommendation(
        workload=f"{wo.namespace}/{wo.name}",
        rec_id="R5",
        finding_type="cas_latency_exceeds_sla",
        category="performance",
        severity="warning",
        evidence_source="kubernetes_event",
        evidence_detail=f"CAS provisioning latency ~{provision_s:.0f}s; Karpenter (AutoNode) achieves ~150s",
        metric_value=f"cas_latency={provision_s:.0f}s, karpenter_estimate=150s",
        recommendation="Migrate to ROSA HCP with AutoNode (Karpenter) to reduce node provision latency by ~60%",
        expected_improvement="Node provision time: ~360s → ~150s; with balloon pods: <5s effective HPA response",
        yaml_delta=yaml_delta,
        confidence="medium",
        confidence_note="Karpenter latency is a benchmark-derived estimate; actual improvement depends on instance availability",
        benchmark_reference="Tests 10 vs 14 (Karpenter vs CAS progressive scale)",
        _classification=q,
    )


def _r6_add_keda(
    wo: WorkloadObservation, q: dict, confidence: str, confidence_note: str
) -> Optional[Recommendation]:
    if not (q["q6_has_keda"] is False and q.get("q5_classification") in ("spike_prone",)):
        return None
    workload = f"{wo.namespace}/{wo.name}"
    yaml_delta = f"""\
# Replace CPU-based HPA with KEDA queue-depth scaler (example: Valkey/Redis)
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: {wo.name}-keda
  namespace: {wo.namespace}
spec:
  scaleTargetRef:
    name: {wo.name}
  minReplicaCount: {wo.hpa_min}
  maxReplicaCount: {wo.hpa_max}
  triggers:
  - type: redis
    metadata:
      address: valkey:6379
      listName: <queue-name>
      listLength: "5"          # scale up when > 5 items per replica\
"""
    return Recommendation(
        workload=workload,
        rec_id="R6",
        finding_type="cpu_hpa_on_queue_workload",
        category="performance",
        severity="warning",
        evidence_source="config_inspection",
        evidence_detail="Workload has spike-prone CPU pattern but no queue-based trigger; CPU HPA lags behind event bursts",
        metric_value=f"cov={q.get('q5_cov', 0):.2f}, classification={q.get('q5_classification')}",
        recommendation="Add KEDA ScaledObject with queue-depth trigger alongside or replacing CPU HPA",
        expected_improvement="Scale decisions based on actual queue depth: faster response, fewer false-positive scale-downs",
        yaml_delta=yaml_delta,
        confidence=confidence,
        confidence_note=confidence_note,
        benchmark_reference="Load-test KEDA scenario (email service)",
        _classification=q,
    )


def _r7_proactive_prewarm(
    wo: WorkloadObservation, q: dict, confidence: str, confidence_note: str
) -> Optional[Recommendation]:
    if not q["q5_predictable"]:
        return None
    workload = f"{wo.namespace}/{wo.name}"
    yaml_delta = f"""\
# CronJob to pre-scale {wo.name} 10 minutes before expected peak
apiVersion: batch/v1
kind: CronJob
metadata:
  name: prewarm-{wo.name}
  namespace: {wo.namespace}
spec:
  schedule: "50 8 * * 1-5"    # Weekdays at 08:50 — adjust to your peak
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: default
          restartPolicy: OnFailure
          containers:
          - name: kubectl
            image: bitnami/kubectl:latest
            command:
            - kubectl
            - scale
            - deployment/{wo.name}
            - --replicas={wo.hpa_max}
            - -n
            - {wo.namespace}\
"""
    return Recommendation(
        workload=workload,
        rec_id="R7",
        finding_type="predictable_peak_no_prewarm",
        category="performance",
        severity="info",
        evidence_source="prometheus_query",
        evidence_detail="Traffic shows strong daily pattern; pre-scaling avoids provision latency entirely",
        metric_value=f"daily_autocorr=high, classification={q.get('q5_classification')}",
        recommendation="Add pre-warm CronJob (or KEDA cron trigger) to scale up before the daily peak",
        expected_improvement="Zero node-provisioning latency at peak start; CAS/Karpenter not needed for scheduled load",
        yaml_delta=yaml_delta,
        confidence=confidence,
        confidence_note=confidence_note,
        benchmark_reference="Test 11 (planned surge)",
        _classification=q,
    )


def _r8_spot(
    wo: WorkloadObservation,
    topology: TopologyResult,
    q: dict,
    confidence: str,
    confidence_note: str,
) -> Optional[Recommendation]:
    if not q["q6_stateless"]:
        return None
    if topology.autoscaler_type == "none":
        return None
    workload = f"{wo.namespace}/{wo.name}"
    yaml_delta = f"""\
# Add spot-instance MachineSet (Classic) or NodePool (AutoNode)
# Adds spot capacity alongside on-demand; HPA/Karpenter prefers spot.
#
# Classic example — duplicate existing MachineSet and add:
spec:
  template:
    spec:
      providerSpec:
        value:
          spotMarketOptions:
            maxPrice: ""    # empty = on-demand price cap
# Label nodes: node.kubernetes.io/capacity-type=spot
# Add node affinity to {wo.name} to prefer spot:
spec:
  template:
    spec:
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 80
            preference:
              matchExpressions:
              - key: node.kubernetes.io/capacity-type
                operator: In
                values: ["spot"]\
"""
    return Recommendation(
        workload=workload,
        rec_id="R8",
        finding_type="no_spot_on_stateless_workload",
        category="cost",
        severity="info",
        evidence_source="config_inspection",
        evidence_detail="Workload appears stateless; spot instances would reduce compute cost 60-80%",
        metric_value="stateless=true, spot_configured=false",
        recommendation=f"Add spot-instance MachineSet/NodePool and configure {wo.name} to prefer spot nodes",
        expected_improvement="60-80% compute cost reduction for stateless workloads with acceptable interruption rate",
        yaml_delta=yaml_delta,
        confidence="medium",
        confidence_note="Stateless classification is heuristic; confirm no local state before enabling spot",
        benchmark_reference="Test 15 (spot instances)",
        _classification=q,
    )


def _r9_arm64(
    wo: WorkloadObservation,
    topology: TopologyResult,
    q: dict,
    confidence: str,
    confidence_note: str,
) -> Optional[Recommendation]:
    # Cannot determine without image manifest inspection; always low confidence
    workload = f"{wo.namespace}/{wo.name}"
    yaml_delta = f"""\
# Add Graviton (ARM64) NodePool/MachineSet
# First confirm image supports aarch64:
#   crane manifest <image> | jq '.manifests[].platform.architecture'
#
# AutoNode NodePool that accepts ARM64:
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: arm64-pool
spec:
  template:
    spec:
      requirements:
      - key: kubernetes.io/arch
        operator: In
        values: ["arm64"]
      - key: karpenter.k8s.aws/instance-category
        operator: In
        values: ["m", "c", "r"]
# Add to {wo.name}:
spec:
  template:
    spec:
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 50
            preference:
              matchExpressions:
              - key: kubernetes.io/arch
                operator: In
                values: ["arm64"]\
"""
    return Recommendation(
        workload=workload,
        rec_id="R9",
        category="cost",
        finding_type="arm64_not_configured",
        severity="info",
        evidence_source="config_inspection",
        evidence_detail="ARM64 (Graviton) not configured; multi-arch images enable 20-40% cost savings",
        metric_value="arm64_pool=false",
        recommendation="Add ARM64 NodePool/MachineSet and annotate workload to prefer Graviton nodes",
        expected_improvement="20-40% instance cost reduction; Graviton provisioning speed comparable to x86",
        yaml_delta=yaml_delta,
        confidence="low",
        confidence_note="Cannot confirm multi-arch image without manifest inspection; verify before applying",
        benchmark_reference="Test 16 (ARM64 Graviton)",
        _classification=q,
    )


# ---------------------------------------------------------------------------
# Phase 3 main entry point
# ---------------------------------------------------------------------------

def reason(
    topology: TopologyResult,
    obs: ObservationResult,
) -> ReasoningResult:
    result = ReasoningResult()

    # Build set of overflow namespaces from topology findings
    overflow_ns: set[str] = set()
    notrigger_ns: set[str] = set()
    for f in topology.findings:
        if f.finding_id in ("F-PENDING", "F-POOL-MISMATCH"):
            for ns in f.namespace.split(", "):
                overflow_ns.add(ns.strip())
        if f.finding_id == "F-NOTRIGGER":
            for ns in f.namespace.split(", "):
                notrigger_ns.add(ns.strip())

    for wo in obs.workloads:
        q = _classify_workload(wo)
        q["q3_overflow"] = wo.namespace in overflow_ns
        q["q3_notrigger"] = wo.namespace in notrigger_ns
        confidence = wo.confidence
        confidence_note = wo.confidence_note

        # R0 — one card per container
        for cr in wo.containers:
            rec = _r0_rightsize(wo, cr, q, confidence, confidence_note)
            if rec:
                result.recommendations.append(rec)

        # R1 — tune HPA threshold
        rec = _r1_tune_hpa_threshold(wo, q, confidence, confidence_note)
        if rec:
            result.recommendations.append(rec)

        # R2 — raise maxReplicas
        rec = _r2_raise_max_replicas(wo, q, confidence, confidence_note)
        if rec:
            result.recommendations.append(rec)

        # R3 + R4 — balloon pods
        recs = _r3_r4_balloon_pods(wo, q, confidence, confidence_note)
        result.recommendations.extend(recs)

        # R5 — switch to Karpenter
        rec = _r5_switch_karpenter(wo, topology, q, confidence, confidence_note)
        if rec:
            result.recommendations.append(rec)

        # R6 — add KEDA
        rec = _r6_add_keda(wo, q, confidence, confidence_note)
        if rec:
            result.recommendations.append(rec)

        # R7 — proactive pre-warm
        rec = _r7_proactive_prewarm(wo, q, confidence, confidence_note)
        if rec:
            result.recommendations.append(rec)

        # R8 — spot instances
        rec = _r8_spot(wo, topology, q, confidence, confidence_note)
        if rec:
            result.recommendations.append(rec)

        # R9 — ARM64 (only if other higher-priority recs are not critical)
        critical_count = sum(1 for r in result.recommendations if r.severity == "critical" and r.workload == f"{wo.namespace}/{wo.name}")
        if critical_count == 0:
            rec = _r9_arm64(wo, topology, q, confidence, confidence_note)
            if rec:
                result.recommendations.append(rec)

    # R10 — NotTriggerScaleUp (cluster-level, not per-workload)
    for f in topology.findings:
        if f.finding_id == "F-NOTRIGGER":
            result.cluster_recs.append(Recommendation(
                workload=f"cluster/{f.namespace}",
                rec_id="R10",
                finding_type="not_trigger_scale_up",
                category="performance",
                severity="critical",
                evidence_source="kubernetes_event",
                evidence_detail=f.detail,
                metric_value=f"count={f.event_count}",
                recommendation="Fix NotTriggerScaleUp: check HPA maxReplicas, MachineSet min/max, and resource quotas",
                expected_improvement="Removes scaling blocker; CAS will provision new nodes when pods are pending",
                yaml_delta="""\
# Diagnose with:
#   oc get events -A --field-selector reason=NotTriggerScaleUp -o json
#   oc describe clusterautoscaler
# Common fixes:
#   1. Raise MachineSet maxReplicas
#   2. Raise HPA maxReplicas (see R2)
#   3. Verify resource quotas in the namespace
#   4. Check pod selectors / node affinities that prevent scheduling\
""",
                confidence="high",
                confidence_note="Directly observed from cluster events",
                benchmark_reference="Test 05 (unschedulable)",
                _classification={},
            ))

    all_recs = result.recommendations + result.cluster_recs
    # Summary stats
    result.summary = {
        "total_recommendations": len(all_recs),
        "critical": sum(1 for r in all_recs if r.severity == "critical"),
        "warning": sum(1 for r in all_recs if r.severity == "warning"),
        "info": sum(1 for r in all_recs if r.severity == "info"),
        "performance_count": sum(1 for r in all_recs if r.category == "performance"),
        "cost_count": sum(1 for r in all_recs if r.category == "cost"),
        "workloads_with_findings": len({r.workload for r in result.recommendations}),
        "prometheus_available": obs.prometheus_available,
    }

    return result
