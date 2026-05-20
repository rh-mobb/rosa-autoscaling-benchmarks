"""
Phase 1 — Topology Discovery.

Queries the cluster to build a complete map of:
- Node autoscaler type (CAS / Karpenter / none)
- Machine pool / NodePool topology
- All HPA, VPA, KEDA, PDB objects
- Recent events for structural findings (FailedScheduling, NotTriggerScaleUp, etc.)

Returns a TopologyResult dataclass with all discovered objects and structural findings.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MachinePool:
    name: str
    instance_type: str
    desired: int
    ready: int
    namespace: str = "openshift-machine-api"


@dataclass
class HPAConfig:
    namespace: str
    name: str
    target_kind: str
    target_name: str
    min_replicas: int
    max_replicas: int
    current_replicas: int
    desired_replicas: int
    metrics: list[dict]    # raw metric specs


@dataclass
class VPAConfig:
    namespace: str
    name: str
    target_name: str
    update_mode: str       # Off | Initial | Recreate | Auto
    recommendations: list[dict]  # containerRecommendations


@dataclass
class KEDAConfig:
    namespace: str
    name: str
    target_name: str
    min_replicas: int
    max_replicas: int
    triggers: list[str]    # trigger types


@dataclass
class PDBConfig:
    namespace: str
    name: str
    selector: dict
    min_available: Optional[str]
    max_unavailable: Optional[str]


@dataclass
class StructuralFinding:
    finding_id: str                # F-NOTRIGGER, F-PENDING, etc.
    severity: str                  # critical | warning | info
    namespace: str
    workload: str
    detail: str
    event_count: int = 0


@dataclass
class NodeInfo:
    name: str
    ready: bool
    cpu_allocatable: str
    memory_allocatable: str
    instance_type: str
    role: str                      # worker | master | infra


@dataclass
class TopologyResult:
    cluster_type: str              # classic | hcp | hcp-autonode
    autoscaler_type: str           # cas | karpenter | none
    node_count: int
    nodes: list[NodeInfo] = field(default_factory=list)
    machine_pools: list[MachinePool] = field(default_factory=list)
    hpas: list[HPAConfig] = field(default_factory=list)
    vpas: list[VPAConfig] = field(default_factory=list)
    keda_objects: list[KEDAConfig] = field(default_factory=list)
    pdbs: list[PDBConfig] = field(default_factory=list)
    findings: list[StructuralFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _oc(args: list[str], kubeconfig: Optional[str] = None) -> Optional[dict]:
    """Run an oc command and return parsed JSON, or None on failure."""
    env = {}
    if kubeconfig:
        import os
        env = {**__import__("os").environ, "KUBECONFIG": kubeconfig}
    else:
        import os
        env = dict(os.environ)

    cmd = ["oc"] + args + ["-o", "json"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, env=env
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


def _oc_text(args: list[str], kubeconfig: Optional[str] = None) -> Optional[str]:
    """Run an oc command and return raw stdout text."""
    env = {}
    import os
    env = {**os.environ, **({"KUBECONFIG": kubeconfig} if kubeconfig else {})}
    cmd = ["oc"] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, env=env
        )
        return result.stdout if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _recent_events(raw: Optional[dict], reason: str, hours: int = 24) -> list[dict]:
    if not raw:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for e in raw.get("items", []):
        ts_str = e.get("lastTimestamp") or e.get("eventTime") or ""
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts > cutoff:
                out.append(e)
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------------------
# Phase 1 main entry point
# ---------------------------------------------------------------------------

def discover(
    kubeconfig: Optional[str] = None,
    cluster_type: str = "classic",
    namespace_filter: Optional[str] = None,
) -> TopologyResult:
    result = TopologyResult(
        cluster_type=cluster_type,
        autoscaler_type="none",
        node_count=0,
    )

    # -----------------------------------------------------------------------
    # Nodes
    # -----------------------------------------------------------------------
    nodes_raw = _oc(["get", "nodes"], kubeconfig)
    if nodes_raw:
        for n in nodes_raw.get("items", []):
            name = n["metadata"]["name"]
            labels = n["metadata"].get("labels", {})
            role = "worker"
            if "node-role.kubernetes.io/master" in labels:
                role = "master"
            elif "node-role.kubernetes.io/infra" in labels:
                role = "infra"
            conditions = n.get("status", {}).get("conditions", [])
            ready = any(c["type"] == "Ready" and c["status"] == "True" for c in conditions)
            alloc = n.get("status", {}).get("allocatable", {})
            instance_type = labels.get("beta.kubernetes.io/instance-type") or \
                            labels.get("node.kubernetes.io/instance-type", "unknown")
            result.nodes.append(NodeInfo(
                name=name, ready=ready,
                cpu_allocatable=alloc.get("cpu", ""),
                memory_allocatable=alloc.get("memory", ""),
                instance_type=instance_type,
                role=role,
            ))
        result.node_count = len(result.nodes)

    # -----------------------------------------------------------------------
    # Autoscaler detection
    # -----------------------------------------------------------------------
    cas_raw = _oc(["get", "clusterautoscaler"], kubeconfig)
    has_cas = bool(cas_raw and cas_raw.get("items"))

    nodeclaims_raw = _oc(["get", "nodeclaims", "-A"], kubeconfig)
    has_karpenter = bool(nodeclaims_raw and nodeclaims_raw.get("items") is not None)

    if has_karpenter:
        result.autoscaler_type = "karpenter"
        result.cluster_type = "hcp-autonode"
    elif has_cas:
        result.autoscaler_type = "cas"
    else:
        result.autoscaler_type = "none"

    # -----------------------------------------------------------------------
    # Machine pools (Classic / HCP)
    # -----------------------------------------------------------------------
    ms_raw = _oc(["get", "machinesets", "-n", "openshift-machine-api"], kubeconfig)
    if ms_raw:
        for ms in ms_raw.get("items", []):
            name = ms["metadata"]["name"]
            desired = ms.get("spec", {}).get("replicas", 0) or 0
            ready = ms.get("status", {}).get("readyReplicas", 0) or 0
            itype = (ms.get("spec", {})
                       .get("template", {})
                       .get("spec", {})
                       .get("providerSpec", {})
                       .get("value", {})
                       .get("instanceType", "unknown"))
            result.machine_pools.append(MachinePool(
                name=name, instance_type=itype, desired=desired, ready=ready
            ))

    # -----------------------------------------------------------------------
    # HPA inventory
    # -----------------------------------------------------------------------
    ns_args = ["-n", namespace_filter] if namespace_filter else ["-A"]
    hpa_raw = _oc(["get", "hpa"] + ns_args, kubeconfig)
    if hpa_raw:
        for h in hpa_raw.get("items", []):
            meta = h["metadata"]
            spec = h["spec"]
            status = h.get("status", {})
            result.hpas.append(HPAConfig(
                namespace=meta["namespace"],
                name=meta["name"],
                target_kind=spec["scaleTargetRef"]["kind"],
                target_name=spec["scaleTargetRef"]["name"],
                min_replicas=spec.get("minReplicas", 1),
                max_replicas=spec["maxReplicas"],
                current_replicas=status.get("currentReplicas", 0),
                desired_replicas=status.get("desiredReplicas", 0),
                metrics=spec.get("metrics", []),
            ))

    # -----------------------------------------------------------------------
    # VPA inventory
    # -----------------------------------------------------------------------
    vpa_raw = _oc(["get", "vpa"] + ns_args, kubeconfig)
    if vpa_raw:
        for v in vpa_raw.get("items", []):
            meta = v["metadata"]
            spec = v.get("spec", {})
            mode = spec.get("updatePolicy", {}).get("updateMode", "Off")
            target_name = spec.get("targetRef", {}).get("name") or \
                          spec.get("scaleTargetRef", {}).get("name", "")
            recs = (v.get("status", {})
                      .get("recommendation", {})
                      .get("containerRecommendations", []))
            result.vpas.append(VPAConfig(
                namespace=meta["namespace"],
                name=meta["name"],
                target_name=target_name,
                update_mode=mode,
                recommendations=recs,
            ))

    # -----------------------------------------------------------------------
    # KEDA
    # -----------------------------------------------------------------------
    keda_raw = _oc(["get", "scaledobject"] + ns_args, kubeconfig)
    if keda_raw:
        for so in keda_raw.get("items", []):
            meta = so["metadata"]
            spec = so.get("spec", {})
            triggers = [t.get("type", "unknown") for t in spec.get("triggers", [])]
            result.keda_objects.append(KEDAConfig(
                namespace=meta["namespace"],
                name=meta["name"],
                target_name=spec.get("scaleTargetRef", {}).get("name", ""),
                min_replicas=spec.get("minReplicaCount", 0),
                max_replicas=spec.get("maxReplicaCount", 100),
                triggers=triggers,
            ))

    # -----------------------------------------------------------------------
    # PDB inventory
    # -----------------------------------------------------------------------
    pdb_raw = _oc(["get", "pdb"] + ns_args, kubeconfig)
    if pdb_raw:
        for p in pdb_raw.get("items", []):
            meta = p["metadata"]
            spec = p.get("spec", {})
            result.pdbs.append(PDBConfig(
                namespace=meta["namespace"],
                name=meta["name"],
                selector=spec.get("selector", {}),
                min_available=str(spec.get("minAvailable")) if "minAvailable" in spec else None,
                max_unavailable=str(spec.get("maxUnavailable")) if "maxUnavailable" in spec else None,
            ))

    # -----------------------------------------------------------------------
    # Event scan for structural findings
    # -----------------------------------------------------------------------
    _check_events(result, kubeconfig)

    # -----------------------------------------------------------------------
    # Cross-checks
    # -----------------------------------------------------------------------
    _check_vpa_hpa_conflict(result)
    _check_hpa_cap(result)
    _check_no_autoscale(result, namespace_filter, kubeconfig)

    return result


def _check_events(result: TopologyResult, kubeconfig: Optional[str]) -> None:
    checks = [
        ("FailedScheduling", "F-PENDING", "critical"),
        ("NotTriggerScaleUp", "F-NOTRIGGER", "critical"),
        ("OOMKilling", "F-OOM", "warning"),
    ]
    for reason, fid, severity in checks:
        raw = _oc(
            ["get", "events", "-A", f"--field-selector=reason={reason}"],
            kubeconfig,
        )
        recent = _recent_events(raw, reason, hours=24)
        if recent:
            namespaces = list({e.get("metadata", {}).get("namespace", "") for e in recent})
            result.findings.append(StructuralFinding(
                finding_id=fid,
                severity=severity,
                namespace=", ".join(namespaces),
                workload="",
                detail=f"{len(recent)} {reason} event(s) in last 24h",
                event_count=len(recent),
            ))


def _check_vpa_hpa_conflict(result: TopologyResult) -> None:
    """Flag VPA in Auto/Recreate mode that shares a target with a CPU-based HPA."""
    hpa_targets = {
        (h.namespace, h.target_name)
        for h in result.hpas
        if any(m.get("type") == "Resource" for m in h.metrics)
    }
    for v in result.vpas:
        if v.update_mode in ("Auto", "Recreate"):
            key = (v.namespace, v.target_name)
            if key in hpa_targets:
                result.findings.append(StructuralFinding(
                    finding_id="F-VPA-CONFLICT",
                    severity="critical",
                    namespace=v.namespace,
                    workload=v.target_name,
                    detail=f"VPA in {v.update_mode} mode conflicts with CPU-based HPA",
                ))


def _check_hpa_cap(result: TopologyResult) -> None:
    """Flag HPA where current replicas == maxReplicas (scaling is capped)."""
    for h in result.hpas:
        if h.current_replicas > 0 and h.current_replicas >= h.max_replicas:
            result.findings.append(StructuralFinding(
                finding_id="F-POOL-MISMATCH",
                severity="warning",
                namespace=h.namespace,
                workload=h.target_name,
                detail=(
                    f"HPA {h.name} at maxReplicas={h.max_replicas} "
                    f"(current={h.current_replicas}, desired={h.desired_replicas})"
                ),
            ))


def _check_no_autoscale(
    result: TopologyResult,
    namespace_filter: Optional[str],
    kubeconfig: Optional[str],
) -> None:
    """Flag Deployments with no HPA, VPA, or KEDA."""
    ns_args = ["-n", namespace_filter] if namespace_filter else ["-A"]
    deploy_raw = _oc(["get", "deployments"] + ns_args, kubeconfig)
    if not deploy_raw:
        return

    scaled_targets = (
        {(h.namespace, h.target_name) for h in result.hpas}
        | {(v.namespace, v.target_name) for v in result.vpas}
        | {(k.namespace, k.target_name) for k in result.keda_objects}
    )

    system_prefixes = ("kube-", "openshift-", "default")

    for d in deploy_raw.get("items", []):
        ns = d["metadata"]["namespace"]
        name = d["metadata"]["name"]
        if any(ns.startswith(p) for p in system_prefixes):
            continue
        # Only flag deployments with > 1 replica or a deliberate single-replica spec —
        # singletons (replicas == 1 and spec.replicas == 1) rarely need autoscaling.
        spec_replicas = d.get("spec", {}).get("replicas", 1) or 1
        ready_replicas = d.get("status", {}).get("readyReplicas", 0) or 0
        if spec_replicas < 2 and ready_replicas < 2:
            continue
        if (ns, name) not in scaled_targets:
            result.findings.append(StructuralFinding(
                finding_id="F-NO-AUTOSCALE",
                severity="warning",
                namespace=ns,
                workload=name,
                detail=f"Deployment (replicas={spec_replicas}) has no HPA, VPA, or KEDA — no autoscaling configured",
            ))
