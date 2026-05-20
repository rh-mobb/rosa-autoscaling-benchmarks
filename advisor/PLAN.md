# Autoscaling Advisor — Plan

## Purpose

Build a discovery-first AI agent that analyzes a running cluster (or a specific
workload/namespace) and produces ranked, evidence-backed autoscaling
recommendations. The advisor does not assume any particular autoscaling
configuration ahead of time — it discovers what is actually running, observes
behavioral patterns, and then reasons about what should change and why.

The initial prototype is a Cursor skill. The skill's instruction set and phase
structure become the specification for a standalone containerized agent once the
approach is validated.

---

## Problem Statement

Autoscaling on ROSA (and Kubernetes generally) is heterogeneous:

- Different services use different scaling mechanisms (HPA on CPU, HPA on custom
  metrics, KEDA on queue depth, nothing at all)
- Misconfigured resource requests make every downstream scaling decision wrong
- Silent failures (`NotTriggerScaleUp`, perpetually-pending pods, OOMKilled
  containers) go unnoticed until an incident
- The right configuration depends on the specific workload's traffic pattern,
  latency SLA, and tolerance for interruption

A deterministic script cannot handle this diversity. An AI agent that discovers
the cluster state, queries live metrics, and reasons about what it finds can.

---

## Approach: Three-Phase Discovery

```
Phase 1 — Topology Discovery
  What autoscaling mechanisms are configured?
  What node autoscaler is running?
  What machine pools / NodePools exist?
  Are there any obvious structural failures?
    → Output: cluster topology map + structural findings Canvas

Phase 2 — Workload Observation
  For each workload with (or needing) autoscaling:
    What metrics drive it? What does recent history look like?
    Is the workload correctly right-sized?
    What traffic pattern does it exhibit?
    → Output: per-workload behavioral profile

Phase 3 — Reasoning & Recommendations
  Classify each workload against the seven classification questions
  Map findings to the recommendation catalog
  Produce ranked recommendations with evidence, YAML deltas, expected improvement
    → Output: ranked recommendation set → Canvas
```

Each phase builds on the previous. Phase 1 shapes what Phase 2 queries. Phases
1 and 2 together determine which recommendations Phase 3 produces.

---

## MCP Tool Plan

### Primary: OpenShift / Kubernetes MCP

Used throughout Phase 1 and Phase 2.

| Query | What the advisor learns |
|-------|------------------------|
| `get clusterautoscaler` | CAS present and configured |
| `get nodeclaims -A` | Karpenter present (HCP + AutoNode) |
| `get nodepools -A` | Karpenter NodePool topology |
| `get machineset -n openshift-machine-api` | Classic/HCP machine pool topology |
| `get hpa -A -o json` | HPA configurations, current/desired replica state |
| `get vpa -A -o yaml` | VPA recommendations vs current requests |
| `get scaledobject -A -o yaml` | KEDA scalers, trigger types, thresholds |
| `get scaledjob -A -o yaml` | KEDA batch job scalers |
| `get pdb -A` | PodDisruptionBudgets (disruption tolerance) |
| `get events -A` | FailedScheduling, NotTriggerScaleUp, OOMKilled, TriggeredScaleUp |
| `adm top nodes` | Real-time node CPU/memory utilization |
| `adm top pods -A` | Real-time pod CPU/memory utilization |

**Fallback (no OpenShift MCP):** Use `oc` CLI via Shell tool with
`KUBECONFIG=tmp/kubeconfig.<cluster>.yaml` from the harness state file.

### Secondary: Prometheus MCP

Used in Phase 2 for pattern analysis. Requires Prometheus to be reachable
(standard on ROSA via `thanos-querier` route in `openshift-monitoring`).

| Query class | What the advisor learns |
|-------------|------------------------|
| CPU/memory utilization histograms (7d) | Over/under-provisioned requests |
| HPA metric history (7d) | Scale event frequency, threshold saturation |
| Custom metric history (from KEDA trigger) | Whether KEDA threshold is calibrated |
| `http_request_duration_seconds` p99 | Latency under load (OTel demo / instrumented apps) |
| `http_requests_total` rate | Traffic CoV, daily autocorrelation |
| Container restart count | OOMKill frequency |
| Node readiness timeline | CAS/Karpenter provision latency (cross-validate with events.jsonl) |

**Fallback (no Prometheus MCP):** Use `oc exec -n openshift-monitoring` to run
`curl` against the thanos-querier API, or skip the pattern analysis phase and
flag lower confidence on recommendations that normally rely on historical data.

### Tertiary: Grafana MCP

Used in Phase 2 to read SLO definitions from existing dashboards. If an SLO
panel defines "p99 latency < 200ms" for a service, that becomes the ground
truth for what "good enough" scaling response time means — which directly
changes balloon pod sizing recommendations.

**Fallback (no Grafana MCP):** Skip SLO cross-referencing. Document in the
output that recommendations are calibrated to generic defaults rather than
confirmed SLOs.

---

## Output Contract

### Cluster-wide Canvas

Produced at the end of Phase 1 (structural findings) and updated at the end of
Phase 3 (full recommendations).

Sections:
- **Infrastructure summary:** node autoscaler type, machine pool/NodePool count,
  cluster type (Classic / HCP / HCP+AutoNode)
- **Structural findings:** silent failures, topology gaps, pool mismatches
- **Provision latency:** measured (from `results/<RUN_ID>/events.jsonl` when
  available) or estimated from node creation event history
- **Cluster-wide recommendations:** node autoscaler selection, balloon pod
  strategy, spot instance policy, ARM64 viability

### Per-Workload Finding Cards

One card per workload with material findings. Not produced for workloads that
are correctly configured.

Each card:
```
Workload: <namespace>/<name>
Severity: critical | warning | info
Finding type: <category>
Evidence: <specific metric or event observed>
Recommendation: <what to change>
Expected improvement: <quantified where possible>
YAML delta: <exact manifest change>
Confidence: high | medium | low
Confidence note: <what data is missing if not high>
```

### Confidence Levels

- **High:** directly observed from 7 days of Prometheus data or explicit cluster
  events
- **Medium:** inferred from 1–7 days of data, or from a proxy metric
- **Low:** estimated from < 24 hours of observation or from static config only

---

## Seven Classification Questions

These are the questions the agent answers about each workload in Phase 3. The
answers drive which recommendations are produced.

| # | Question | Primary signal source |
|---|----------|-----------------------|
| Q1 | Is the workload correctly right-sized? | VPA advise data, `adm top pods` vs requests |
| Q2 | Does HPA have enough room to work? | HPA status, threshold vs p95 utilization history |
| Q3 | Does scaling regularly overflow node capacity? | FailedScheduling event frequency |
| Q4 | What is the node provisioning latency budget? | `events.jsonl` (measured) or node creation event history |
| Q5 | Is the traffic pattern predictable or random? | Prometheus CoV + 24h autocorrelation |
| Q6 | Is the workload interruption-tolerant? | PDB presence, stateless check, restart behavior |
| Q7 | Are container images multi-arch? | Image manifest inspection or user confirmation |

---

## Recommendation Catalog

Each recommendation maps to one or more classification question answers.

| Rec | Trigger condition | Benchmark evidence |
|-----|------------------|--------------------|
| R0: Rightsize requests | Q1: current > 2× VPA upper, or OOMKilled > 0 | Test 07 (VPA advise) |
| R1: Tune HPA threshold | Q2: HPA perpetually near maxReplicas, or threshold > 70% with latency SLA | Test 06 (HPA) |
| R2: Raise HPA maxReplicas | Q2: HPA capped while pods pending | Test 06 |
| R3: Add balloon pods | Q3: FailedScheduling > 0/week, Q5: high-variance traffic | Tests 09/11/12 |
| R4: Size balloon pods correctly | Q3+Q4: balloon count must cover one provision cycle | Test 12 (degradation window) |
| R5: Switch to Karpenter (AutoNode) | Q3: frequent overflow, latency SLA < 3 min, Classic/HCP cluster | Tests 10 vs 14 |
| R6: Add KEDA scaler | Q5: workload is queue/event-driven, not RPS-driven | Test harness KEDA scenario |
| R7: Proactive pre-warm | Q5: predictable daily peak | Test 11 (planned surge) |
| R8: Spot instances | Q6: interruption-tolerant | Test 15 (spot) |
| R9: ARM64 pool | Q7: multi-arch images | Test 16 (ARM64) |
| R10: Fix NotTriggerScaleUp | Q3: NotTriggerScaleUp events present | Test 05 (unschedulable) |

---

## Integration with Existing Benchmark Data

When `results/<RUN_ID>/events.jsonl` exists for the target cluster, the advisor
uses measured latencies rather than estimates:

```
cas_wave_latency_p95    ← test 03/14 milestones
karpenter_claim_ready   ← test 10 milestones
hpa_to_all_pods_ready   ← test 08 milestones (cascade total)
parallel_node_stagger   ← test 13 milestones
```

These numbers feed directly into balloon pod sizing (R3/R4) and the
Karpenter migration ROI calculation (R5). When no benchmark data exists, the
advisor flags lower confidence and recommends running the relevant test.

---

## Evolution Path

```
Phase A — Cursor Skill (this phase)
  File: .cursor/skills/autoscaling-advisor/SKILL.md
  I/O: MCP tool calls + Canvas output
  Purpose: prototype, iterate, validate recommendation quality

Phase B — Standalone Python Agent
  File: advisor/agent.py
  I/O: kubernetes-client + prometheus-api-client + HTML/JSON output
  Purpose: run locally against any cluster, no Cursor required

Phase C — Containerized Agent
  File: advisor/Dockerfile + manifests/advisor/
  I/O: in-cluster service account, writes to ConfigMap or advisor CRD
  Trigger: CronJob (daily) or Operator (watches HPA/VPA object changes)
  Purpose: always-on recommendations in production clusters
```

The SKILL.md instruction set is the specification for Phase B. The same phase
structure, same queries, same classification logic — different I/O layer.

---

## Milestones

### Milestone 1 — Topology Discovery Canvas (Phase 1 complete)
Deliverable: running the skill against any ROSA cluster produces a Canvas
showing the node autoscaler type, all configured HPA/VPA/KEDA objects, and any
obvious structural failures (NotTriggerScaleUp events, missing PDBs on
stateful workloads, etc.).

Success criteria:
- Canvas produced within 5 minutes of invocation
- Correctly identifies Classic vs HCP vs HCP+AutoNode
- Surfaces at least one finding on a misconfigured cluster

### Milestone 2 — Workload Observation (Phase 2 complete)
Deliverable: the skill queries Prometheus for each workload found in Phase 1
and produces a behavioral profile (CoV, peak-to-baseline ratio, utilization
vs requests delta).

Success criteria:
- Works against a cluster with Prometheus available
- Gracefully degrades (lower-confidence findings) when Prometheus is unavailable
- Correctly identifies over-provisioned containers using VPA + top data

### Milestone 3 — Full Recommendation Set (Phase 3 complete)
Deliverable: ranked recommendation cards with specific YAML deltas and expected
improvement estimates, validated against the OTel demo load-test harness.

Success criteria:
- Recommendations are actionable (YAML delta can be applied directly)
- At least one recommendation is validated by running the load-test before and
  after applying it
- Confidence level is correctly set based on data availability

### Milestone 4 — Standalone Python Agent
Deliverable: `advisor/agent.py` reproduces Milestone 3 output using
`kubernetes-client` instead of MCP calls, runnable as `python3 advisor/agent.py
--kubeconfig <path>`.

### Milestone 5 — Containerized Deployment
Deliverable: `Dockerfile` + CronJob manifest. Agent runs in-cluster, writes
recommendations to a `ConfigMap` in `openshift-autoscaling-advisor` namespace.

---

## Open Questions (resolved iteratively during build)

- Which Prometheus queries are reliably available across different ROSA
  monitoring configurations (user workload monitoring enabled vs disabled)?
- How to normalize KEDA trigger types into a unified recommendation framework —
  Kafka, Redis, HTTP, and custom metrics all need different analysis paths.
- How much can the LLM reasoning step infer about a workload's interruption
  tolerance from its configuration vs needing to ask the user?
- What is the right Canvas layout for clusters with many workloads — per-service
  accordion, severity-sorted table, or namespace grouping?
- Should the agent ask clarifying questions during the session (e.g., "Is this
  workload latency-sensitive?") or make conservative assumptions and document them?
- What RBAC permissions does the containerized agent need? (Minimum viable
  read-only ClusterRole to be determined during Phase B.)

---

## Non-Goals

- The advisor does not automatically apply recommendations. It produces YAML
  deltas and `oc apply` commands for the operator to review and run.
- The advisor does not manage cluster lifecycle (no `rosa create`, no `terraform
  apply`, no node deletion).
- The advisor does not replace the existing benchmark scripts — it complements
  them by using their output as ground truth calibration data.
