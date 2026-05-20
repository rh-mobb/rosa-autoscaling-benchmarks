"""
JSON report writer — machine-readable output.
Writes the full topology + observations + recommendations to a single JSON file.
"""
from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        d = {}
        for f in dataclasses.fields(obj):
            if f.name.startswith("_"):
                continue
            d[f.name] = _to_dict(getattr(obj, f.name))
        return d
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


def write(
    topology,
    obs,
    reasoning,
    out_dir: str,
    run_id: str = "",
) -> str:
    """Write advisor_report.json to out_dir. Returns the file path."""
    os.makedirs(out_dir, exist_ok=True)

    report = {
        "advisor_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "cluster_type": topology.cluster_type,
        "autoscaler_type": topology.autoscaler_type,
        "summary": reasoning.summary,
        "topology": {
            "node_count": topology.node_count,
            "machine_pools": _to_dict(topology.machine_pools),
            "hpa_count": len(topology.hpas),
            "vpa_count": len(topology.vpas),
            "keda_count": len(topology.keda_objects),
            "pdb_count": len(topology.pdbs),
            "structural_findings": _to_dict(topology.findings),
        },
        "observations": {
            "prometheus_available": obs.prometheus_available,
            "provision_latency_s": obs.provision_latency_s,
            "provision_latency_source": obs.provision_latency_source,
            "workloads": _to_dict(obs.workloads),
        },
        "recommendations": _to_dict(reasoning.recommendations),
        "cluster_recommendations": _to_dict(reasoning.cluster_recs),
    }

    path = os.path.join(out_dir, "advisor_report.json")
    with open(path, "w") as fp:
        json.dump(report, fp, indent=2, default=str)
    return path
