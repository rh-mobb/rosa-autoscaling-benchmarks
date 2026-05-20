# Autoscaling Advisor

Discovery-first agent that analyzes a running ROSA cluster (or a specific
workload/namespace) and produces ranked, evidence-backed autoscaling recommendations.

## Quick start

```bash
# Install dependencies
cd advisor && pip install -r requirements.txt

# Run against the classic-bench cluster (auto-detects kubeconfig)
python3 agent.py --cluster-type classic

# Scope to the OTel demo namespace
python3 agent.py --cluster-type classic --namespace otel-demo

# HCP + AutoNode cluster
python3 agent.py --cluster-type hcp-autonode

# Outputs land in reports/advisor/ by default
open reports/advisor/advisor_report.html
```

## CLI reference

| Flag | Default | Description |
|------|---------|-------------|
| `--cluster-type` | `classic` | `classic \| hcp \| hcp-autonode` |
| `--kubeconfig` | auto-detect | Path to kubeconfig; falls back to `KUBECONFIG` env or `tmp/kubeconfig.*.yaml` |
| `--namespace` | cluster-wide | Scope to a single namespace |
| `--workload` | all | Scope to a specific Deployment name |
| `--output` | `both` | `json \| html \| both` |
| `--out-dir` | `reports/advisor` | Where to write outputs |
| `--run-id` | `""` | Benchmark run ID for `events.jsonl` lookup (enables measured latencies) |
| `--results-dir` | `results` | Where to scan for `events.jsonl` files |
| `--quiet` | `false` | Suppress progress output |

## How it works

### Phase 1 — Topology Discovery
Queries the cluster for all autoscaling objects (HPA, VPA, KEDA, CAS,
Karpenter), machine pools, and recent events. Produces structural findings
(NotTriggerScaleUp, HPA at maxReplicas, VPA/HPA conflicts, etc.).

### Phase 2 — Workload Observation
For each workload with autoscaling configured, queries Prometheus for 7-day
utilization history, computes coefficient of variation (traffic pattern
classification), reads VPA recommendations, and resolves provisioning latency
from benchmark data or default estimates.

### Phase 3 — Reasoning
Answers seven classification questions per workload and maps answers to the
R0–R10 recommendation catalog. Each recommendation includes a YAML delta and
expected improvement estimate.

## Recommendation catalog

| Rec | Trigger |
|-----|---------|
| R0 | Container over- or under-provisioned (requests vs VPA/Prometheus actuals) |
| R1 | HPA threshold ≥ 70% with latency SLA |
| R2 | HPA at maxReplicas with pods pending |
| R3 | Add balloon pods (FailedScheduling events or spike-prone traffic) |
| R4 | Size balloon pods to match provisioning window |
| R5 | Switch to Karpenter/AutoNode (CAS latency > SLA budget) |
| R6 | Add KEDA scaler (workload is event/queue-driven) |
| R7 | Proactive pre-warm CronJob (predictable daily peak) |
| R8 | Spot instances (stateless, interruption-tolerant) |
| R9 | ARM64 pool (multi-arch images) |
| R10 | Fix NotTriggerScaleUp (CAS blocked by pool limits) |

## Integration with benchmark data

When `results/<RUN_ID>/events.jsonl` exists, the advisor uses measured
provisioning latencies from benchmark tests 03/10/14 instead of default
estimates. Pass `--run-id <RUN_ID>` or let the agent scan automatically.

## Cursor Skill

Use the `.cursor/skills/autoscaling-advisor` skill for interactive analysis
inside Cursor. The skill runs the same three-phase logic using MCP tool calls
and produces a Canvas output.

## Structure

```
advisor/
  agent.py              — CLI entry point
  requirements.txt
  phases/
    topology.py         — Phase 1: cluster topology discovery
    observation.py      — Phase 2: workload metrics + utilization
    reasoning.py        — Phase 3: classification + recommendation engine
  output/
    canvas.py           — HTML report generator
    json_report.py      — Machine-readable JSON output
  lib/
    sizing.py           — Balloon pod sizing formulas
    patterns.py         — CoV, autocorrelation, pattern classification
    events_jsonl.py     — Benchmark events.jsonl reader
```
