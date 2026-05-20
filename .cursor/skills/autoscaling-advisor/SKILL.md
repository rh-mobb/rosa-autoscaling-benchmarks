---
name: autoscaling-advisor
description: >-
  Analyze a running ROSA cluster or specific workload and produce ranked,
  evidence-backed autoscaling recommendations. Runs three phases: topology
  discovery (what is configured), workload observation (how it actually behaves
  from Prometheus), and reasoning (which of R0-R10 apply and why). Delivers a
  Cursor Canvas with per-workload finding cards, YAML deltas, and expected
  improvement estimates. Use when the user wants to audit autoscaling
  configuration, find misconfigured HPAs or oversized containers, understand
  why a workload is scaling poorly, or get a prioritized recommendation set
  before running load tests.
---

# Autoscaling Advisor

Three-phase discovery agent. Do not skip phases — each builds context for the next.

## Preflight

```bash
# 1. Resolve cluster
CLUSTER_TYPE=${CLUSTER_TYPE:-classic}
STATE_FILE="tmp/cluster.${CLUSTER_TYPE}.json"
CLUSTER_NAME=$(python3 -c "import json; print(json.load(open('${STATE_FILE}'))['cluster_name'])")
export KUBECONFIG="$PWD/tmp/kubeconfig.${CLUSTER_NAME}.yaml"
oc whoami   # confirm auth

# 2. Optional: scope to a namespace or workload
SCOPE_NS=${SCOPE_NS:-""}         # empty = cluster-wide
SCOPE_WORKLOAD=${SCOPE_WORKLOAD:-""}  # empty = all workloads
```

Prefer the Python agent for automated runs:
```bash
cd advisor && pip install -r requirements.txt -q
python3 agent.py --cluster-type $CLUSTER_TYPE [--namespace $SCOPE_NS]
```

---

## Phase 1 — Topology Discovery

Goal: build a complete map of what autoscaling is configured before touching any metrics.

### 1a. Node autoscaler type

```bash
# CAS (Classic / HCP)
oc get clusterautoscaler -o json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
items = d.get('items', [d]) if 'items' in d else [d]
for ca in items:
    spec = ca.get('spec', {})
    print('CAS present:', spec.get('resourceLimits', {}) or 'default limits')
" || echo "No CAS"

# Karpenter / AutoNode (HCP + AutoNode)
oc get nodeclaims -A -o json 2>/dev/null | python3 -c "
import json, sys; d=json.load(sys.stdin)
print('Karpenter NodeClaims:', len(d.get('items',[])))
" || echo "No Karpenter"

oc get nodepool -A --no-headers 2>/dev/null | head -10 || echo "No NodePools"
```

### 1b. Machine pool / NodePool topology

```bash
oc get machineset -n openshift-machine-api -o json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for ms in d.get('items', []):
    name = ms['metadata']['name']
    desired = ms.get('spec', {}).get('replicas', 0)
    ready = ms.get('status', {}).get('readyReplicas', 0)
    itype = ms.get('spec',{}).get('template',{}).get('spec',{}).get('providerSpec',{}).get('value',{}).get('instanceType', 'unknown')
    print(f'{name}: desired={desired} ready={ready} type={itype}')
"
```

### 1c. Autoscaling object inventory

```bash
# HPA — all namespaces
oc get hpa -A -o json | python3 -c "
import json, sys
d = json.load(sys.stdin)
for h in d.get('items', []):
    ns = h['metadata']['namespace']
    name = h['metadata']['name']
    target = h['spec']['scaleTargetRef']['name']
    min_r = h['spec'].get('minReplicas', 1)
    max_r = h['spec']['maxReplicas']
    current = h.get('status', {}).get('currentReplicas', '?')
    desired = h.get('status', {}).get('desiredReplicas', '?')
    for m in h['spec'].get('metrics', []):
        if m.get('type') == 'Resource':
            thresh = m['resource']['target'].get('averageUtilization', '?')
            metric = m['resource']['name']
            print(f'{ns}/{name} → {target}: {metric}@{thresh}% [{min_r}-{max_r}] cur={current} des={desired}')
"

# VPA
oc get vpa -A -o json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for v in d.get('items', []):
    ns = v['metadata']['namespace']
    name = v['metadata']['name']
    mode = v.get('spec', {}).get('updatePolicy', {}).get('updateMode', 'Off')
    recs = v.get('status', {}).get('recommendation', {}).get('containerRecommendations', [])
    for r in recs:
        target = r.get('target', {})
        print(f'{ns}/{name} [{mode}]: {r[\"containerName\"]} target cpu={target.get(\"cpu\",\"?\")} mem={target.get(\"memory\",\"?\")}')
" || echo "No VPA objects"

# KEDA
oc get scaledobject -A -o json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for so in d.get('items', []):
    ns = so['metadata']['namespace']
    name = so['metadata']['name']
    target = so['spec']['scaleTargetRef']['name']
    triggers = [t['type'] for t in so['spec'].get('triggers', [])]
    print(f'{ns}/{name} → {target}: triggers={triggers}')
" || echo "No KEDA"

# PDBs
oc get pdb -A --no-headers 2>/dev/null | awk '{print $1"/"$2, "min="$3, "desired="$4, "healthy="$5}'
```

### 1e. Cluster Proportional Autoscaler (CPA) + balloon pod discovery

```bash
# Detect CPA deployments (look for the cluster-proportional-autoscaler image or binary)
oc get deployment -A -o json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
found = []
for dep in d.get('items', []):
    ns   = dep['metadata']['namespace']
    name = dep['metadata']['name']
    for c in dep.get('spec',{}).get('template',{}).get('spec',{}).get('containers',[]):
        all_args = ' '.join(c.get('command',[]) + c.get('args',[]))
        if 'cluster-proportional-autoscaler' in c.get('image','') \
                or 'cluster-proportional-autoscaler' in all_args:
            target = next((a.split('=',1)[1] for a in c.get('args',[])
                           if a.startswith('--target=')), 'unknown')
            ns_arg = next((a.split('=',1)[1] for a in c.get('args',[])
                           if a.startswith('--namespace=')), ns)
            found.append(f'{ns}/{name} target={target} ns={ns_arg}')
print('\n'.join(found) if found else 'No CPA found')
"

# Detect balloon deployments (pause image or negative priorityClass)
oc get deployment -A -o json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for dep in d.get('items', []):
    ns      = dep['metadata']['namespace']
    name    = dep['metadata']['name']
    spec    = dep.get('spec',{}).get('template',{}).get('spec',{})
    pc      = spec.get('priorityClassName','')
    replicas = dep.get('spec',{}).get('replicas', 1)
    is_pause = any('pause' in c.get('image','')
                   for c in spec.get('containers',[]))
    if pc or is_pause:
        print(f'{ns}/{name}: priorityClassName={pc!r} pause={is_pause} replicas={replicas}')
" || echo "No balloon deployments"
```

Record: **CPA present** (and which Deployment it targets) or **absent**. Record: **balloon pods present** (static replicas) or **absent**. Both feed R12.

### 1d. Event scan (last 1h for structural findings)

```bash
for reason in FailedScheduling NotTriggerScaleUp TriggeredScaleUp OOMKilling; do
  count=$(oc get events -A --field-selector "reason=${reason}" \
    -o json 2>/dev/null | python3 -c "
import json, sys
from datetime import datetime, timezone, timedelta
d = json.load(sys.stdin)
cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
recent = [e for e in d.get('items', [])
          if datetime.fromisoformat(e.get('lastTimestamp','1970-01-01T00:00:00Z').replace('Z','+00:00')) > cutoff]
print(len(recent))
")
  echo "${reason}: ${count}"
done
```

### Phase 1 output (record before proceeding)

Produce an intermediate summary in your response:
```
AUTOSCALER:   [CAS | Karpenter | none]
CLUSTER TYPE: [classic | hcp | hcp-autonode]
NODES:        [total] ([ready])
HPAs:         [count] across [namespaces]
VPAs:         [count] ([Auto/Recreate count])
KEDA:         [count ScaledObjects]
PDBs:         [count]
PROMETHEUS FLEET:
  Cluster (thanos-querier): [reachable | unreachable] — kube_* + container_*
  User-workload monitoring: [enabled | disabled] — app custom metrics
  Bundled (namespace):      [list ns/svc:port or none] — container_* + app metrics
CPA:          [present (targets: Deployment/balloon in ns/NAME) | absent]
BALLOON PODS: [present — static N replicas (no CPA) | present — managed by CPA | absent]
FINDINGS:
  F-NOTRIGGER: [count in 24h]
  F-PENDING:   [count pods pending > 5min]
  F-NO-AUTOSCALE: [deployments with no scaling]
  F-VPA-CONFLICT: [VPA Auto + HPA CPU pairs]
```

---

## Phase 2 — Workload Observation

For each workload discovered in Phase 1, collect behavioral evidence.

### 2a. Real-time utilization

```bash
oc adm top pods -A --no-headers 2>/dev/null | sort -k3 -rn | head -20
oc adm top nodes --no-headers 2>/dev/null
```

### 2b. Prometheus fleet discovery (enumerate ALL sources first)

A cluster can have multiple Prometheus instances serving different metric families. **Discover all of them before querying any.** Do not stop at the first one that responds.

```bash
# ── Tier 1: OpenShift cluster monitoring (kube-state-metrics + cAdvisor) ──────
# Provides: kube_* (HPA replicas, pod states), container_* (CPU/mem usage/throttle)
# Needs a token; federated via thanos-querier on port 9091
THANOS_ROUTE=$(oc get route -n openshift-monitoring thanos-querier \
  -o jsonpath='{.spec.host}' 2>/dev/null)
if [[ -n "$THANOS_ROUTE" ]]; then
  THANOS_TOKEN=$(oc create token -n openshift-monitoring prometheus-k8s \
    --duration=1h 2>/dev/null || \
    oc sa get-token -n openshift-monitoring prometheus-k8s 2>/dev/null)
  PROM_CLUSTER="https://${THANOS_ROUTE}"
  echo "Cluster Prometheus: ${PROM_CLUSTER} (token acquired)"
else
  # No external route — port-forward instead
  oc port-forward -n openshift-monitoring svc/thanos-querier 9091:9091 &>/dev/null &
  sleep 2
  THANOS_TOKEN=$(oc create token -n openshift-monitoring prometheus-k8s \
    --duration=1h 2>/dev/null)
  PROM_CLUSTER="http://localhost:9091"
  echo "Cluster Prometheus: port-forward 9091 (token acquired: $([ -n "$THANOS_TOKEN" ] && echo yes || echo no))"
fi

# ── Tier 2: OpenShift user-workload monitoring ─────────────────────────────────
# Provides: application-instrumented metrics (custom counters, histograms, etc.)
# Only present if cluster-monitoring-config has enableUserWorkload: true
UWM_ROUTE=$(oc get route -n openshift-user-workload-monitoring \
  prometheus-user-workload -o jsonpath='{.spec.host}' 2>/dev/null)
if [[ -n "$UWM_ROUTE" ]]; then
  UWM_TOKEN=$(oc create token -n openshift-user-workload-monitoring \
    prometheus-user-workload --duration=1h 2>/dev/null)
  PROM_UWM="https://${UWM_ROUTE}"
  echo "User-workload Prometheus: ${PROM_UWM}"
else
  echo "User-workload Prometheus: not enabled (check cluster-monitoring-config)"
  PROM_UWM=""
fi

# ── Tier 3: Namespace-bundled Prometheus instances ────────────────────────────
# Provides: namespace-scoped container_* AND any app metrics the chart bundles
# Common in: otel-demo, observability stacks, operator-deployed monitoring
# Hunt via Services with port 9090 that expose Prometheus endpoints
for ns in ${SCOPE_NS:-$(oc get namespaces -o jsonpath='{.items[*].metadata.name}')}; do
  svc=$(oc get svc -n "$ns" \
    -o json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for s in d.get('items', []):
    name = s['metadata']['name']
    for p in s.get('spec', {}).get('ports', []):
        if p.get('port') in (9090, 9091):
            print(f'{name}:{p[\"port\"]}')
" 2>/dev/null)
  if [[ -n "$svc" ]]; then
    echo "Bundled Prometheus in ${ns}: ${svc}"
    # Port-forward to an available local port and record
    # e.g.: oc port-forward -n ${ns} svc/prometheus 9092:9090 &
  fi
done
```

**Before querying: record which tier(s) are available and what each provides:**

| Tier | URL | Provides | Token required |
|------|-----|----------|----------------|
| Cluster (thanos-querier) | `PROM_CLUSTER` | `kube_*`, `container_*`, node metrics | Yes |
| User-workload | `PROM_UWM` | App-instrumented custom metrics | Yes |
| Namespace-bundled | per-namespace port-forward | `container_*` (cAdvisor) + app metrics bundled by chart | Usually no |

**Query each tier for what it can actually provide.** Do not run `kube_hpa_*` against a bundled Prometheus; do not expect app HTTP metrics from thanos-querier unless user-workload monitoring is enabled.

```bash
# Helper: query any Prometheus (pass URL and optional token)
prom_query() {
  local url="$1" query="$2" token="${3:-}"
  local auth=""
  [[ -n "$token" ]] && auth="-H \"Authorization: Bearer ${token}\""
  eval curl -sk ${auth} "${url}/api/v1/query" \
    --data-urlencode "query=${query}" \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
for r in d.get('data', {}).get('result', []):
    print(r['metric'], r['value'][1])
" 2>/dev/null
}
```

**Metric family → preferred source:**

```
container_cpu_usage_seconds_total       → Cluster (cAdvisor via kubelet) OR bundled
container_cpu_cfs_throttled_*           → Cluster OR bundled
container_memory_working_set_bytes      → Cluster OR bundled
kube_horizontalpodautoscaler_*          → Cluster only (kube-state-metrics)
kube_pod_container_status_restarts_*    → Cluster only
http_server_request_duration_*          → User-workload OR bundled (OTel OTLP/Prom)
http_requests_total                     → User-workload OR bundled
Custom app metrics (queue depth, etc.)  → User-workload OR bundled
```

Key queries per workload — run against the appropriate tier (substitute `NAMESPACE`, `DEPLOYMENT`, `HPA_NAME`):

```promql
# CPU utilization p95 — run against Cluster or bundled
quantile_over_time(0.95,
  rate(container_cpu_usage_seconds_total{
    namespace="NAMESPACE", pod=~"DEPLOYMENT.*", container!="", container!="POD"}[5m])[3h:1m])

# CPU throttle rate — run against Cluster or bundled
sum by(container)(rate(container_cpu_cfs_throttled_seconds_total{
  namespace="NAMESPACE", pod=~"DEPLOYMENT.*", container!="", container!="POD"}[3h]))

# Memory working set p95 — run against Cluster or bundled
quantile_over_time(0.95,
  container_memory_working_set_bytes{
    namespace="NAMESPACE", pod=~"DEPLOYMENT.*", container!="POD"}[3h])

# HPA scale event count — Cluster only
changes(kube_horizontalpodautoscaler_status_current_replicas{
  namespace="NAMESPACE", horizontalpodautoscaler="HPA_NAME"}[3h])

# HPA max replicas reached — Cluster only
max_over_time(kube_horizontalpodautoscaler_status_current_replicas{
  namespace="NAMESPACE", horizontalpodautoscaler="HPA_NAME"}[3h])

# HTTP request rate — User-workload or bundled
rate(http_server_request_duration_seconds_count{namespace="NAMESPACE"}[5m])

# OOMKill restarts — Cluster only
increase(kube_pod_container_status_restarts_total{
  namespace="NAMESPACE", pod=~"DEPLOYMENT.*"}[3h])
```

**If a tier is unavailable:** document `confidence: low` for that metric family in the Canvas Confidence Notes. Fall back to `oc adm top` for real-time CPU/mem and `oc get events` for HPA scaling events.

### 2c. VPA recommendation vs current requests

```bash
# For each workload, extract the delta between VPA target and current request
oc get vpa -n NAMESPACE -o json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for v in d.get('items', []):
    deploy_name = v['spec']['targetRef']['name']
    for cr in v.get('status',{}).get('recommendation',{}).get('containerRecommendations',[]):
        c = cr['containerName']
        tgt = cr.get('target',{})
        ub = cr.get('upperBound',{})
        lb = cr.get('lowerBound',{})
        print(f'{deploy_name}/{c}: target={tgt.get(\"cpu\",\"?\")} mem={tgt.get(\"memory\",\"?\")} | upper={ub.get(\"cpu\",\"?\")} | lower={lb.get(\"cpu\",\"?\")}')
"
```

### 2d. Check benchmark event data

```bash
# Use measured latencies if available
for f in results/*/events.jsonl; do
  if [[ -f "$f" ]]; then
    python3 -c "
import json
with open('$f') as fp:
  events = [json.loads(l) for l in fp if l.strip()]
latency_events = [e for e in events if 'latency' in e.get('event','').lower()
                  or e.get('phase','') in ('scale_up','provision','cas_triggered')]
for e in latency_events[-10:]:
  print(e.get('ts',''), e.get('event',''), e.get('elapsed_s',''))
"
  fi
done
```

---

## Phase 3 — Reasoning and Recommendations

Answer the seven classification questions per workload, then map to recommendations.

### Classification questions

For each workload, answer in your reasoning:

```
Q1 (right-sizing):    current_request / p95_actual > 2.0 → over; < 1.1 or OOMKill → under
                      ALSO check cpu_request/cpu_limit ratio: ratio < 0.5 means HPA fires
                      at a CPU% that is well below the actual container capacity, making
                      scale-out premature (request too low inflates % utilization).
                      ALSO check throttle rate: > 100ms/s → high-confidence under-limit;
                      > 1000ms/s → critical (container always hitting CPU ceiling).
Q2 (HPA headroom):    threshold > 70% with latency SLA, or maxReplicas hit while pending
Q3 (overflow):        FailedScheduling or NotTriggerScaleUp events in last 7d
                      — on CAS: NotTriggerScaleUp = autoscaler refused (wrong type/quota/cap)
                      — on Karpenter: NotTriggerScaleUp = provisioning gap (node not yet Ready);
                        check NodeClaim Launched→Ready latency; normal if < 10 min
Q4 (latency budget):  provisioning_time vs acceptable degradation window
Q5 (pattern):         CoV < 0.2 steady | 0.2–0.5 moderate | > 0.5 spike-prone
Q6 (interruption):    stateless check + no PDB + no spot configured
Q7 (multi-arch):      image manifest has both amd64 and arm64 layers
Q8 (missing HPA):     deployment with no HPA, p95 CPU > 30% of request under observed load
                      — these are unprotected bottlenecks; flag for HPA addition
```

### Compound failure chain — escalate to critical

When a single workload simultaneously hits **all three** of the following, collapse them into one **critical** card (not three separate medium findings):

1. CPU throttle rate > 100ms/s (Q1 — CPU limit too low)
2. HPA at `maxReplicas` while pods are pending (Q2 — replica cap hit)
3. `NotTriggerScaleUp` events for the same deployment (Q3 — overflow)

This is a "capacity wall": the pod can't get more CPU, can't get more replicas, and can't get more nodes. The combined fix is R0 + R2 + R3, and the severity is **critical** regardless of each individual item's severity.

### HPA scale history fallback

When `kube_horizontalpodautoscaler_*` metrics are unavailable (e.g. bundled Prometheus without kube-state-metrics), reconstruct HPA scale history from events:

```bash
# All scale-up events
oc get events -n NAMESPACE \
  --field-selector reason=SuccessfulRescale \
  -o json | python3 -c "
import json, sys
d = json.load(sys.stdin)
for e in sorted(d.get('items',[]), key=lambda x: x.get('lastTimestamp','')):
    obj = e['involvedObject']['name']
    msg = e.get('message','')[:80]
    ts  = e.get('lastTimestamp','?')
    print(f'[{ts}] {obj}: {msg}')
"
```

Mark findings derived from events as `confidence: medium` (events have no replica-count history between scale steps).

### Recommendation catalog

| Rec | Condition | YAML change |
|-----|-----------|-------------|
| R0 | Q1: over/under-provisioned **or throttle > 100ms/s** | Update `resources.requests.cpu/memory` and/or `limits.cpu` |
| R1 | Q2: threshold ≥ 70% + latency SLA | Lower HPA `averageUtilization` to 50–60% |
| R2 | Q2: HPA at maxReplicas with pending pods | Raise `maxReplicas` |
| R3 | Q3 + Q5: overflow + high variance | Add pause-pod balloon Deployment + PriorityClass |
| R4 | R3 present: size the balloon correctly | Set balloon replicas = `ceil(provision_s/60 * burst_rate)` |
| R5 | Q4: CAS latency > SLA budget | Migrate to AutoNode (Karpenter) |
| R6 | Q5: event/queue-driven | Replace HPA with KEDA ScaledObject |
| R7 | Q5: predictable daily peak | Add KEDA cron scaler or HPA pre-scale CronJob |
| R8 | Q6: stateless, interruption-tolerant | Add spot instance MachineSet/NodePool |
| R9 | Q7: multi-arch confirmed | Add ARM64 pool with node affinity |
| R10 | Q3 on CAS: NotTriggerScaleUp present | Fix pool instance type or HPA `maxReplicas` cap |
| R11 | Q8: deployment missing HPA, material CPU under load | Add HPA targeting CPU at 60% of request |
| R12 | Balloon pods present with static replicas + no CPA managing them | Add Cluster Proportional Autoscaler to scale balloon count with cluster size |

### R3/R4 — Balloon pod implementation

When R3 or R4 applies, read `.cursor/skills/autoscaling-advisor/balloon-pods.md` for the
complete YAML template, sizing formula, and common mistakes. Key points:

- Mechanism works on **both CAS and Karpenter**: balloons hold pre-warmed capacity; real
  pods preempt them instantly (<1 s); the now-pending balloon triggers the autoscaler to
  provision a replacement node in the background.
- PriorityClass `value` must be **negative** (e.g. `-10`) to avoid displacing system pods.
- Add `terminationGracePeriodSeconds: 0` — pause has no SIGTERM handler.
- Set `resources.requests` to match the node's spare capacity; **no limits**.
- Include the **toleration** for any node pool taint (e.g. `workload=otel-demo:NoSchedule`).
- Sizing: `ceil(provision_s / 60 * pods_per_minute_at_burst)` — use Phase 1 NodeClaim or
  CAS scale-up latency as `provision_s`.

### R12 — Cluster Proportional Autoscaler for balloon pods

When R12 applies, read `.cursor/skills/autoscaling-advisor/balloon-pods.md` (CPA section)
for the full YAML. Key points:

- Static balloon replicas become stale as the cluster grows or shrinks. CPA reads the
  live node/core count and updates the balloon Deployment replicas automatically via a
  **ladder ConfigMap** (e.g. 1 balloon per 2 nodes, capped at 10).
- CPA is a separate Deployment that watches cluster size; it does **not** replace the
  balloon Deployment or PriorityClass — it only manages the replica count.
- Condition for R12: Phase 1e found balloon pods with static replicas **and** no CPA
  deployment targeting them. Also fire if R3 is being freshly recommended alongside R4 on
  a cluster where node count is expected to change over time.

### Output format per finding card

For each workload with findings, produce a structured card:

```
┌─────────────────────────────────────────────────────────────┐
│ namespace/deployment-name                    [severity]      │
├─────────────────────────────────────────────────────────────┤
│ Finding:  <what is wrong>                                    │
│ Evidence: <metric or event observed>                         │
│ Fix:      <recommendation R#>                                │
│ Expected: <quantified improvement>                           │
│ Confidence: high/medium/low — <why>                          │
├─────────────────────────────────────────────────────────────┤
│ YAML delta:                                                  │
│   <exact patch>                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Canvas output

Produce a Canvas with these sections:

1. **Infrastructure Summary** — autoscaler type, node count, pool topology, cluster type
2. **Structural Findings** — severity-sorted table of F-* findings
3. **Workload Finding Cards** — one card per workload with material findings
4. **Cluster-wide Recommendations** — balloon pod strategy, spot viability, ARM64 viability
5. **Confidence Notes** — which Prometheus tier(s) were reachable, which metric families came from each, and what was unavailable (drives per-finding confidence: high/medium/low)

If running against the OTel demo (`otel-demo` namespace): cross-reference the
HPA configs in `load-test/manifests/autoscaling/` to validate advisor output
against the known misconfiguration matrix.

---

## Standalone agent

For non-interactive runs:

```bash
cd advisor
pip install -r requirements.txt -q
python3 agent.py \
  --cluster-type classic \
  --kubeconfig ../tmp/kubeconfig.classic-bench.yaml \
  --output html \
  --out-dir ../reports/advisor/
```

See `advisor/README.md` for full CLI reference.
