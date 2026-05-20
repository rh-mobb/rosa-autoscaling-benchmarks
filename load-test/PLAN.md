# Load Test Harness — Plan

## Purpose

Replace the synthetic `cpu-burner` workload with a realistic multi-service
application under real HTTP load, so that:

1. The autoscaling advisor has a credible, diverse workload to analyze
2. Benchmark results are expressed in actual user-facing metrics (error rates,
   latency percentiles) rather than pod-readiness timings alone
3. The advisor evaluation loop can be closed: apply a recommendation, re-run
   the same load scenario, measure the delta

The harness is built on the **OpenTelemetry Demo Application** — a production-
grade e-commerce microservices reference app maintained by the CNCF — augmented
with intentional autoscaling configurations (some correct, some deliberately
wrong) and **k6** load scenarios for controlled spike and ramp patterns.

---

## Why the OpenTelemetry Demo App

The OTel demo ships with:
- ~15 services across Go, Python, .NET, Node.js, and Ruby
- Native Prometheus metric exposition on every service
- A Grafana dashboard suite (pre-built, SLO-ready)
- A Jaeger tracing backend (cross-service latency decomposition)
- A built-in Locust load generator (realistic shopping behavior)
- Feature flags via `flagd` (inject failures without code changes)

For our purposes, the diversity of runtimes is the key feature. Each runtime
class has different startup time, memory profile, and scaling behavior:

| Runtime | Services | Startup time | Scaling characteristic |
|---------|----------|--------------|----------------------|
| Go | frontend, checkout, shipping, currency, product catalog | ~1s | Fast startup, CPU-bound |
| .NET | cart | ~10–20s | JIT warmup; balloon pods matter here |
| Python | recommendation, load generator | ~3–5s | Memory growth under load |
| Node.js | frontend-proxy, ad | ~2–5s | Event loop saturation before CPU fires |
| Ruby | email | ~5–10s | Slow start; good KEDA queue-consumer candidate |

This means the advisor will encounter fast and slow startup, different HPA
triggers, and at least three distinct optimal autoscaling strategies on a single
cluster — which is a realistic production scenario.

---

## Scope

This harness delivers three things:

1. **OTel demo deployed to ROSA** with OpenShift SCC compatibility and a
   `values.yaml` tuned for the benchmark cluster's resource budget
2. **Autoscaling configuration matrix** layered on top: some services correctly
   configured, some deliberately misconfigured for the advisor to find
3. **k6 load scenarios** for controlled, reproducible traffic patterns that
   produce measurable HTTP error rates and latency histograms

The existing `docs/http-stress-test-plan.md` already specifies the k6 Job
manifest pattern and `result.extra` schema. This harness extends that design to
the full OTel service mesh rather than a single `cpu-burner` service.

---

## Phase 1 — OTel Demo Deployed (baseline metrics visible)

### Deliverables
- `load-test/helm/values-rosa.yaml` — OTel demo Helm values tuned for ROSA
- `load-test/manifests/namespace.yaml` — `otel-demo` namespace with SCC
  annotations
- `load-test/deploy.sh` — idempotent deploy/update script
- Verification: all 15 services Running, Prometheus scraping, Grafana accessible

### OpenShift SCC compatibility

The OTel demo containers were not built for OpenShift's non-root security model.
The `values-rosa.yaml` must address:

```yaml
# Global security context override for containers that run as root upstream
global:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault

# Per-component overrides where upstream image uses a fixed UID
components:
  frontend:
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: [ALL]
  # ... repeated for any component that fails with default restricted SCC
```

The `otel-demo` namespace should be given the `restricted-v2` SCC by default.
Components that need relaxed permissions (e.g., the OpenTelemetry Collector)
get a dedicated `ServiceAccount` bound to `anyuid` SCC via a
`RoleBinding` scoped to that namespace only.

### Resource budget

The chart requires ~6 GB RAM minimum. On the benchmark cluster, dedicate a
machine pool specifically for the OTel demo workload:

```bash
rosa create machinepool \
  --cluster "$CLUSTER_NAME" \
  --name otel-demo \
  --instance-type m5.2xlarge \   # 8 vCPU / 32 GB
  --replicas 2 \
  --labels workload=otel-demo
```

All OTel demo pods target this pool via `nodeSelector: workload: otel-demo`.
Benchmark workloads (`cpu-burner`, etc.) continue to target `pool-type: standard`.

### Success criteria
- All 15 OTel demo services in `Running` state
- Prometheus scraping OTel metrics (verify via Grafana → OpenTelemetry Demo dashboard)
- Locust load generator producing traffic (web store accessible)
- No SCCViolation events in `oc get events -n otel-demo`

---

## Phase 2 — Autoscaling Configs + k6 Scenarios

### Autoscaling configuration matrix

Layered on top of the OTel demo. The matrix intentionally includes both correct
and misconfigured examples so the advisor has something to find.

| Service | Scaler | Trigger metric | Configuration | Intended finding |
|---------|--------|---------------|---------------|-----------------|
| `frontend` | HPA | CPU utilization | threshold: 80%, max: 5 | R1: threshold too high for latency SLA |
| `checkout` | HPA | Custom: `http_requests_total` rate | threshold: 100 RPS/pod | Correctly configured (baseline) |
| `product-catalog` | HPA | CPU utilization | threshold: 60%, max: 10 | Correctly configured |
| `recommendation` | VPA | advise-only | — | R0: over-provisioned requests (Python overhead) |
| `cart` | HPA | CPU utilization | max: 2 (too low) | R2: maxReplicas too low for .NET JIT burst |
| `email` | KEDA | Redis queue depth | threshold: 10 msgs | Correctly configured queue-based scaler |
| `ad` | None | — | — | F-NO-AUTOSCALE: no scaler on bursty service |
| `currency` | HPA | CPU utilization | threshold: 50%, max: 8 | Correctly configured |
| `shipping` | HPA | CPU utilization | threshold: 90% (too high) | R1: threshold way too high |
| `payment` | None | — | — | F-NO-AUTOSCALE + F-NO-PDB: no scaler, no PDB |

Deliberately misconfigured services (`frontend`, `cart`, `ad`, `shipping`,
`payment`) are the advisor's primary validation targets.

### VPA deployment

VPA operator is installed (same path as test 07) and a VPA object in `Off`
(advise-only) mode is applied to every service in the matrix. This gives the
advisor VPA recommendation data without VPA ever modifying pods.

```yaml
# Applied per service; name follows <service>-vpa convention
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: recommendation-vpa
  namespace: otel-demo
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: recommendation
  updatePolicy:
    updateMode: "Off"
```

### k6 scenario catalog

Five scenarios covering the traffic patterns that matter for autoscaling
recommendation validation. All run as Kubernetes Jobs in the `otel-demo`
namespace, targeting `frontend-proxy:8080`.

| Scenario | Description | Key metric | What it validates |
|----------|-------------|-----------|-------------------|
| `sudden-spike` | 0 → 10× in 30s, hold 5 min | Error rate during spike | R3/R4 (balloon pods), R5 (Karpenter) |
| `ramp` | Linear increase over 10 min to 5× | When HPA fires vs when latency degrades | R1 (threshold tuning) |
| `daily-pattern` | Sinusoidal over 30 min, 3× peak | Pre-warm effectiveness | R7 (proactive pre-warm) |
| `sustained-high` | 3× baseline for 20 min | CAS scale-down after load drops | R3/R4 sizing, scale-down behavior |
| `burst-and-drop` | 5× for 2 min then immediate drop | HPA stabilization window, over-scaling | R1 (stabilization window) |

Each scenario records per-second:
- `http_req_failed` rate (5xx / total)
- `http_req_duration{p95}`, `http_req_duration{p99}`
- `http_reqs` rate (total throughput)

Output written to `/results/k6-<scenario>-<timestamp>.csv` via k6 `--out csv`
and retrieved with `oc cp`.

---

## Phase 3 — Advisor Evaluation Loop

The evaluation loop closes the feedback cycle: the advisor recommends, the
operator applies, the load test re-runs, the delta is measured.

```
1. Deploy OTel demo (Phase 1)
2. Apply baseline (misconfigured) autoscaling matrix (Phase 2)
3. Run load scenario against baseline config → record baseline metrics
4. Run advisor → produce recommendations
5. Apply advisor recommendations (YAML deltas)
6. Re-run same load scenario → record post-recommendation metrics
7. Compute delta: error rate, p99 latency, degradation window
8. Record delta in advisor's per-workload finding card
```

This loop runs per scenario × per workload cluster type (Classic, HCP,
AutoNode) to build a validation matrix:

| Scenario | Cluster type | Baseline error rate | Post-rec error rate | Improvement |
|----------|-------------|--------------------|--------------------|-------------|
| `sudden-spike` | Classic + CAS | TBD | TBD | TBD |
| `sudden-spike` | HCP + AutoNode | TBD | TBD | TBD |
| `ramp` | Classic + CAS | TBD | TBD | TBD |
| ... | ... | ... | ... | ... |

These measured deltas replace the probabilistic estimates in the advisor's
`expected_improvement` fields with empirical evidence.

---

## Connection to Existing Harness

The k6 HTTP metrics slot directly into the existing `result.extra` schema
defined in `docs/http-stress-test-plan.md`:

```python
result.extra["http.total_requests"]        = k6_csv["http_reqs"].sum()
result.extra["http.total_5xx"]             = k6_csv["http_req_failed"].sum()
result.extra["http.error_rate_pct"]        = ...
result.extra["http.p99_ms"]               = k6_csv["http_req_duration{p99}"].max()
result.extra["http.degradation_window_s"] = seconds_until_error_rate_below_1pct()
```

Existing benchmark scripts that already use `result.extra` (tests 08, 09, 12)
can adopt these keys when run with `--http-load` flag without schema changes.

---

## Milestones

### Milestone 1 — OTel Demo Running on ROSA

Deliverable: `load-test/helm/values-rosa.yaml` + `load-test/deploy.sh`; all 15
services Running; Prometheus scraping confirmed; Grafana accessible.

Success criteria:
- Zero SCCViolation events in `otel-demo` namespace
- Locust load generator hitting the web store successfully
- Grafana → OpenTelemetry Demo dashboard showing live data

### Milestone 2 — Autoscaling Matrix Applied

Deliverable: `load-test/manifests/autoscaling/` directory with one YAML per
service configuration; VPA operator installed; all HPA/KEDA/VPA objects
in expected state.

Success criteria:
- `oc get hpa -n otel-demo` shows all expected HPAs
- `oc get scaledobject -n otel-demo` shows email service KEDA scaler
- `oc get vpa -n otel-demo` shows advise-only VPA for each service
- Deliberately misconfigured services confirmed (frontend threshold: 80%,
  cart maxReplicas: 2, ad/payment with no scaler)

### Milestone 3 — k6 Scenarios Validated

Deliverable: `load-test/k6/` directory with one script per scenario; each
scenario runs successfully as a Kubernetes Job and produces parseable CSV.

Success criteria:
- `sudden-spike` produces measurable error rate during the spike window
- `ramp` shows HPA firing at the expected utilization point
- All scenarios produce CSV output retrievable via `oc cp`

### Milestone 4 — Advisor Evaluation Loop Complete

Deliverable: baseline vs post-recommendation metrics for at least two scenarios
(sudden-spike + ramp) on one cluster type.

Success criteria:
- Advisor recommendation applied changes at least one HPA threshold and
  adds balloon pods
- Post-recommendation `sudden-spike` error rate is measurably lower than baseline
- Delta recorded in advisor finding card `expected_improvement` field

---

## Directory Layout

```
load-test/
  PLAN.md                       ← this file
  ARCHITECTURE.md               ← detailed architecture
  deploy.sh                     ← idempotent OTel demo deploy/teardown
  helm/
    values-rosa.yaml            ← ROSA-compatible OTel demo Helm values
  manifests/
    namespace.yaml              ← otel-demo ns + SCC annotations
    machine-pool.yaml           ← otel-demo dedicated machine pool
    autoscaling/
      frontend-hpa.yaml         ← misconfigured (threshold: 80%)
      checkout-hpa.yaml         ← correctly configured
      product-catalog-hpa.yaml
      recommendation-vpa.yaml
      cart-hpa.yaml             ← misconfigured (maxReplicas: 2)
      email-keda.yaml           ← KEDA Redis queue scaler
      currency-hpa.yaml
      shipping-hpa.yaml         ← misconfigured (threshold: 90%)
      vpa-all-services.yaml     ← advise-only VPA for all services
  k6/
    scenarios/
      sudden-spike.js
      ramp.js
      daily-pattern.js
      sustained-high.js
      burst-and-drop.js
    jobs/
      k6-job-template.yaml      ← parameterized Job manifest
    lib/
      thresholds.js             ← shared SLO thresholds (p99 < 500ms, error < 1%)
```

---

## Non-Goals

- The OTel demo is not modified at the application code level. All changes are
  in the Helm values and the autoscaling manifests layered on top.
- The harness does not replace the existing `cpu-burner` benchmark scripts
  (tests 01–16). It runs in a separate namespace (`otel-demo`) on the same
  cluster. Tests 01–16 continue to use their existing workloads.
- The load generator does not target the benchmark namespace. k6 scenarios
  target `frontend-proxy.otel-demo.svc:8080` only.
- This harness does not test Cluster Autoscaler or Karpenter provisioning speed
  directly — that is the job of the existing benchmark suite. It tests whether
  autoscaling *configuration* (thresholds, balloon pods, KEDA triggers) is
  correct for a realistic workload.
