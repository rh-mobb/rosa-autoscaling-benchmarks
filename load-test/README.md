# Load-Test Harness

Realistic HTTP load-testing environment for validating autoscaling advisor
recommendations. Deploys the **OpenTelemetry Demo App** (19 microservices) on
ROSA with intentionally misconfigured HPAs, then drives traffic through
**k6** load scenarios to measure user-facing metrics (error rate, latency
percentiles) across autoscaling events.

> **Quick start:**
> ```bash
> CLUSTER_TYPE=classic ./load-test/deploy.sh install
> ./load-test/deploy.sh run-k6 sudden-spike BASELINE_RPS=30 SPIKE_RPS=300
> ```

---

## Why this exists

The benchmark suite's `cpu-burner` workload measures node provisioning speed
precisely, but it says nothing about how a real application behaves under
autoscaling. This harness provides:

1. **A diverse multi-runtime workload** — Go, .NET, Python, Node.js, Ruby, Java
   services with different startup times, memory profiles, and CPU behaviors
2. **Intentionally misconfigured HPAs** — so the autoscaling advisor has
   something meaningful to find and fix
3. **Controlled k6 scenarios** — reproducible spike, ramp, and daily patterns
   for measuring before/after deltas when advisor recommendations are applied
4. **Native Prometheus + Grafana** — every service exposes metrics; dashboards
   are deployed alongside the app

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| `helm` | ≥ 3.x | Deploy the OTel demo chart |
| `oc` | any | All in-cluster operations |
| `envsubst` | any | Render k6 Job templates |
| ROSA cluster | Classic or HCP | Authentication via `tmp/kubeconfig.<name>.yaml` |

No Kafka, no OpenSearch, no KEDA, no VPA operator required for the base deploy.
KEDA and VPA are detected at install time and their configs applied only if the
operator is present.

---

## Directory layout

```
load-test/
├── deploy.sh                        # All operations: install / status / run-k6 / uninstall
├── PLAN.md                          # Design rationale and milestones
├── ARCHITECTURE.md                  # System diagrams and service map
├── helm/
│   └── values-rosa.yaml             # ROSA-compatible Helm overrides for the OTel demo
├── manifests/
│   ├── namespace.yaml               # otel-demo namespace (labels only — let OpenShift set MCS)
│   ├── scc-otelcol.yaml             # anyuid/privileged CRBs for chart service accounts
│   └── autoscaling/
│       ├── frontend-hpa.yaml        # 80% CPU, max 5   — misconfigured (advisor target)
│       ├── cart-hpa.yaml            # 70% CPU, max 2   — misconfigured (cap too low)
│       ├── shipping-hpa.yaml        # 90% CPU, max 8   — misconfigured (threshold too high)
│       ├── checkout-hpa.yaml        # 60% CPU, max 10  — correctly configured
│       ├── product-catalog-hpa.yaml # 60% CPU, max 10  — correctly configured
│       ├── currency-hpa.yaml        # 50% CPU, max 8   — correctly configured
│       ├── email-keda.yaml          # Valkey queue scaler (requires KEDA operator)
│       └── vpa-all-services.yaml    # VPA Off mode for all services (requires VPA operator)
└── k6/
    ├── lib/
    │   └── thresholds.js            # Shared SLO thresholds + endpoint weights
    ├── scenarios/
    │   ├── sudden-spike.js          # Baseline → 10× burst → recovery
    │   ├── ramp.js                  # Linear ramp to 5× over 10 min
    │   ├── daily-pattern.js         # Compressed 24h traffic pattern (35 min)
    │   ├── sustained-high.js        # 3× for 20 min → scale-down observation
    │   └── burst-and-drop.js        # 5× for 2 min → HPA scale-down behavior
    └── jobs/
        └── k6-job-template.yaml     # envsubst-rendered Kubernetes Job
```

---

## Deploy

```bash
# Resolve cluster from state file (default: classic)
CLUSTER_TYPE=classic ./load-test/deploy.sh install

# Or point at a specific kubeconfig
KUBECONFIG="$PWD/tmp/kubeconfig.an-bench.yaml" ./load-test/deploy.sh install
```

The install steps in order:

1. `oc create namespace otel-demo` — lets OpenShift auto-generate SCC MCS labels
2. Apply `manifests/scc-otelcol.yaml` — binds chart service accounts to anyuid/privileged SCC
3. `helm upgrade --install` with `helm/values-rosa.yaml` — deploys the OTel demo
4. Apply autoscaling configs (HPA always; KEDA and VPA only if operators present)
5. Create `k6-scenarios` and `k6-lib` ConfigMaps for Job mounting
6. Wait for `frontend-proxy` Deployment to be Available

**Expected time:** ~5 minutes for image pulls on first deploy, ~90 seconds on subsequent runs.

---

## Check status

```bash
CLUSTER_TYPE=classic ./load-test/deploy.sh status
```

Shows: pods (name / status / restarts), HPAs, KEDA ScaledObjects, VPAs, and
any recent SCC violation events.

---

## Run a k6 scenario

```bash
# sudden-spike: baseline → 10× burst → recovery
./load-test/deploy.sh run-k6 sudden-spike BASELINE_RPS=30 SPIKE_RPS=300

# ramp: linear ramp to 5×, hold, ramp down
./load-test/deploy.sh run-k6 ramp BASELINE_RPS=30 PEAK_RPS=150

# burst-and-drop: 5× for 2 min, then watch HPA scale back down
./load-test/deploy.sh run-k6 burst-and-drop BASELINE_RPS=30 BURST_RPS=150

# sustained-high: 3× for 20 min, then scale-down observation window
./load-test/deploy.sh run-k6 sustained-high BASELINE_RPS=30 SUSTAINED_RPS=90 HOLD_DURATION=20

# daily-pattern: compressed 24h traffic (35 min wall time)
./load-test/deploy.sh run-k6 daily-pattern BASELINE_RPS=10 MORNING_PEAK_RPS=80 AFTERNOON_PEAK_RPS=120
```

The command creates a k6 Job in the `otel-demo` namespace and tails its logs.
Job name: `k6-<scenario>-<timestamp>` (timestamp format: `YYYYMMDDtHHMMSS`).

### Retrieve results

```bash
# After the Job shows Completed:
./load-test/deploy.sh fetch-results sudden-spike 20260519t143000
# Copies /results/k6-output.csv and /results/k6-<scenario>-summary.json
# to load-test/results/k6-<scenario>-<timestamp>/
```

---

## Services and HPA configuration

| Service | Language | Runtime notes | HPA | Advisor label |
|---------|----------|--------------|-----|---------------|
| frontend × 2 | Next.js | ~3s startup | 2–**5** replicas, **80% CPU** | misconfigured |
| frontend-proxy | Envoy | <1s | — | k6 entry point |
| checkout | Go | ~1s | 1–10, 60% | correct |
| cart | .NET | **10–20s JIT** | 1–**2**, 70% | misconfigured (cap) |
| product-catalog | Go | ~1s, uses PostgreSQL | 1–10, 60% | correct |
| recommendation | Python | ~3–5s | — | — |
| payment | Node.js | ~2s | — | — |
| shipping | Go | ~1s | 1–8, **90% CPU** | misconfigured |
| currency | Go | ~1s | 1–8, 50% | correct |
| ad | Java | ~5s JVM warmup | — | — |
| email | Ruby | ~5–10s | — | KEDA-ready |
| flagd | Go | ~1s | — | feature flags |
| quote | PHP | ~2s | — | — |
| valkey-cart | Valkey | — | — | cart backend |
| postgresql | PostgreSQL | — | — | product-catalog v2.x |
| prometheus | — | — | — | scrapes all services |
| grafana | — | — | — | dashboards at `/grafana` |
| otel-collector | — | deployment mode | — | no host-level presets |

**Disabled** (saves ~2 GB RAM): kafka, fraud-detection, accounting, opensearch,
jaeger, llm, product-reviews, image-provider, load-generator.

---

## k6 scenario reference

### sudden-spike

```
Phase 1 (0–60s):   BASELINE_RPS   (default 30)
Phase 2 (60–360s): SPIKE_RPS      (default 300, i.e. 10×)
Phase 3 (360–480s): ramp down to baseline
```

Validates: HPA fire time, degradation window duration, whether balloon pods
collapse the error window.

### ramp

```
0–10 min: ramp from BASELINE_RPS → PEAK_RPS
10–15 min: hold at PEAK_RPS
15–20 min: ramp back to BASELINE_RPS
```

Validates: whether HPA threshold fires before or after p99 latency breaches
SLO (threshold calibration finding R1).

### daily-pattern

```
Compressed 24h in 35 minutes:
  overnight quiet → morning ramp → midday dip → afternoon peak → wind-down
```

Validates: proactive pre-warm effectiveness; whether autocorrelation is
detectable in Prometheus history for advisor classification.

### sustained-high

```
0–2 min:  ramp to SUSTAINED_RPS (default 90)
2–22 min: hold
22–24 min: ramp down
24–34 min: baseline traffic during CAS/Karpenter scale-down observation
```

Validates: CAS scale-down cooldown (~10 min), balloon pod restoration,
R3/R4 balloon pod sizing.

### burst-and-drop

```
0–30s:    warm-up at BASELINE_RPS
30s–2m30s: BURST_RPS (default 150, i.e. 5×)
2m30s–10m30s: back to baseline (observe HPA scale-down)
```

Validates: `stabilizationWindowSeconds` tuning — too low causes HPA thrash,
too high wastes nodes.

---

## SLO thresholds (shared by all scenarios)

Defined in `k6/lib/thresholds.js`. Breaches are **recorded** but do not abort
the test — we want the full degradation window measured, not stopped.

| Metric | Threshold |
|--------|-----------|
| p99 latency | < 500 ms |
| p95 latency | < 300 ms |
| Error rate | < 1% |

---

## Access the web store

```bash
oc port-forward -n otel-demo svc/frontend-proxy 8080:8080 &
open http://localhost:8080            # OTel demo web store
open http://localhost:8080/grafana    # Grafana dashboards (anonymous admin)
```

Prometheus is at `http://prometheus.otel-demo.svc:9090` from inside the cluster,
or via port-forward on port 9090.

---

## ROSA-specific notes

### SCC bindings (`manifests/scc-otelcol.yaml`)

The OTel demo container images bake in upstream UIDs (101 for Envoy, 472 for
Grafana, 999 for Valkey, 1000/1001 for Go/Node services). ROSA's
`restricted-v2` SCC only permits UIDs within the namespace-assigned range
(e.g. `1001070000–1001079999`). The install binds chart service accounts:

| Service account | SCC | Reason |
|----------------|-----|--------|
| `otel-demo` | `anyuid` | All microservice pods |
| `grafana` | `privileged` | Legacy `container.seccomp.security.alpha.kubernetes.io/*` pod annotations |
| `prometheus` | `anyuid` | UID 65534 (nobody) |
| `otel-collector` | `anyuid` | Collector deployment |
| `postgresql` | `anyuid` | UID 999 (postgres) |

### Namespace creation

The namespace is created with `oc create namespace` (not `oc apply -f
namespace.yaml`) so OpenShift's namespace controller auto-generates the
`openshift.io/sa.scc.mcs` SELinux label. Applying a custom namespace manifest
that omits this annotation prevents pod admission entirely — the `namespace.yaml`
in this repo only adds labels and is applied as a patch after creation.

### OTel Collector mode

The chart default is DaemonSet with `hostMetrics`, `kubeletMetrics`, and
`clusterMetrics` presets — all require elevated SCC access. `values-rosa.yaml`
switches to Deployment mode and disables those presets. OpenShift's own
monitoring stack already provides node and cluster metrics.

### checkout init container

The OTel demo chart v0.40.8 ships a `wait-for-kafka` init container on
`checkout` by default. Since Kafka is disabled here, `values-rosa.yaml`
overrides `components.checkout.initContainers: []` to remove it.

---

## Optional add-ons

### VPA (advise-only for all services)

```bash
# After installing the VPA operator via OLM or manifests:
oc apply -f load-test/manifests/autoscaling/vpa-all-services.yaml -n otel-demo

# Read recommendations after 24h of load:
oc get vpa -n otel-demo -o yaml | grep -A 20 "containerRecommendations"
```

### KEDA (email service queue scaler)

```bash
# After installing KEDA operator:
oc apply -f load-test/manifests/autoscaling/email-keda.yaml -n otel-demo

# The email ScaledObject watches the 'email-jobs' list in valkey-cart
# and scales email pods based on queue depth
```

---

## Tear down

```bash
CLUSTER_TYPE=classic ./load-test/deploy.sh uninstall
# Prompts: "Type 'yes' to confirm"
```

Removes: Helm release, HPA/KEDA/VPA configs, SCC ClusterRoleBindings,
`otel-demo` namespace (and all its resources).

---

## Helm chart reference

| Property | Value |
|----------|-------|
| Chart | `open-telemetry/opentelemetry-demo` |
| Version | `0.40.8` |
| App version | `2.2.0` |
| Values file | `load-test/helm/values-rosa.yaml` |
| Repo | `https://open-telemetry.github.io/opentelemetry-helm-charts` |
