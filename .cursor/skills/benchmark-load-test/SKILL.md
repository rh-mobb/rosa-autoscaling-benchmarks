---
name: benchmark-load-test
description: >-
  Deploy, run, and tear down the OTel Demo + k6 load-test harness on a ROSA
  cluster. Provisions the OpenTelemetry Demo App (19 microservices including
  frontend, checkout, cart, product-catalog, Prometheus, Grafana) with
  intentionally misconfigured HPAs for advisor validation, then runs k6 load
  scenarios (sudden-spike, ramp, daily-pattern, sustained-high, burst-and-drop)
  as in-cluster Jobs. Use when the user wants to deploy realistic HTTP load
  against the cluster, generate autoscaling advisor test data, run a k6
  scenario, validate HPA behavior, or clean up the otel-demo namespace.
---

# Load-Test Harness (OTel Demo + k6)

All files live under `load-test/`. The entry point is `load-test/deploy.sh`.

## Prerequisites

- `helm` ≥ 3, `oc` authenticated, `envsubst` in PATH
- Classic or HCP cluster running (kubeconfig resolved from `tmp/cluster.${CLUSTER_TYPE}.json`)
- For CAS/HCP pool creation: `rosa` CLI authenticated (`rosa whoami`)

```bash
export CLUSTER_TYPE=classic   # or: hcp | hcp-autonode
# KUBECONFIG is resolved automatically from tmp/cluster.${CLUSTER_TYPE}.json
# Override manually: export KUBECONFIG="$PWD/tmp/kubeconfig.<name>.yaml"
```

## Node isolation

`install` provisions a dedicated node pool **before** Helm so all OTel Demo microservices land on isolated nodes from the start. k6 Job pods intentionally have no nodeSelector and run on default worker nodes.

| Autoscaler detected | What `install` creates | Wait behavior |
|---|---|---|
| Karpenter CRDs present | `NodePool/otel-demo` (applies `manifests/karpenter-nodepool.yaml`) | Non-blocking — Karpenter provisions on demand when pods pend |
| No Karpenter + `rosa` available | `rosa create machine-pool otel-demo --labels workload=otel-demo --taints workload=otel-demo:NoSchedule` | Blocks up to 10 min for nodes to be Ready |
| Neither available | Warning; deploys without node isolation | — |

All OTel Demo pods (scheduled by Helm) carry:
- `nodeSelector: workload=otel-demo` — stay on the dedicated pool
- `toleration: workload=otel-demo:NoSchedule` — tolerate the pool's taint

k6 Job pods carry **neither**, so they run on default workers and do not consume benchmark node capacity.

`uninstall` deletes the node pool (Karpenter NodePool or ROSA machine pool) so the underlying EC2 instances terminate.

## Commands

```bash
# Deploy everything (namespace → SCC → Helm → HPAs → k6 ConfigMaps)
CLUSTER_TYPE=classic ./load-test/deploy.sh install

# Check pod/HPA/VPA/KEDA status
CLUSTER_TYPE=classic ./load-test/deploy.sh status

# Run a k6 scenario (creates a Job, tails output)
./load-test/deploy.sh run-k6 sudden-spike BASELINE_RPS=30 SPIKE_RPS=300
./load-test/deploy.sh run-k6 ramp          BASELINE_RPS=30 PEAK_RPS=150
./load-test/deploy.sh run-k6 burst-and-drop BASELINE_RPS=30 BURST_RPS=150
./load-test/deploy.sh run-k6 sustained-high BASELINE_RPS=30 SUSTAINED_RPS=90
./load-test/deploy.sh run-k6 daily-pattern

# Fetch k6 CSV results after Job completes
./load-test/deploy.sh fetch-results <scenario> <timestamp>

# Tear down everything (prompts for confirmation)
CLUSTER_TYPE=classic ./load-test/deploy.sh uninstall
```

## What gets deployed

**OTel Demo v2.2.0** (chart `open-telemetry/opentelemetry-demo:0.40.8`):

| Service | Language | HPA config | Advisor label |
|---------|----------|------------|---------------|
| frontend × 2 | Next.js | 2–5 replicas, **80% CPU** | misconfigured (too high) |
| frontend-proxy | Envoy | — | entry point for k6 |
| checkout | Go | 1–10, 60% | correct |
| cart | .NET | 1–**2**, 70% | misconfigured (cap too low) |
| product-catalog | Go | 1–10, 60% | correct |
| recommendation | Python | — | — |
| payment | Node.js | — | — |
| shipping | Go | 1–8, **90% CPU** | misconfigured (too high) |
| currency | Go | 1–8, 50% | correct |
| ad | Java | — | — |
| email | Ruby | — | KEDA-ready |
| valkey-cart | Valkey | — | cart backend |
| postgresql | PostgreSQL | — | required by product-catalog v2.x |
| prometheus | — | — | scrapes all services |
| grafana | — | — | dashboards at `/grafana` |
| otel-collector | — | deployment mode | no host-level presets |

**Disabled** (saves ~2 GB): kafka, fraud-detection, accounting, opensearch, jaeger, llm, product-reviews, image-provider, load-generator.

**`recommendation` has no HPA by design.** Under spike load it becomes a CPU bottleneck (Python GIL + no scale-out), causing `/api/recommendations` timeouts. This is an intentional advisor test case — the advisor should flag it for HPA addition and CPU right-sizing.

### Bundled Prometheus limitations

The OTel Demo Prometheus only scrapes cAdvisor (`container_*` metrics). It does **not** include kube-state-metrics, so `kube_hpa_*` metrics (HPA replica counts, scale events) are absent. The autoscaling advisor must fall back to `oc get events --field-selector reason=SuccessfulRescale` for HPA scale history when running against this namespace. See the advisor skill Phase 2b for the multi-source Prometheus strategy.

## k6 scenarios

| Scenario | Pattern | Duration | Key validation |
|----------|---------|----------|----------------|
| `sudden-spike` | baseline → burst → recovery | ~8 min | HPA fire time, error window |
| `ramp` | linear ramp to 5× over 10 min | ~20 min | HPA threshold calibration |
| `daily-pattern` | compressed 24h traffic | ~30 min | pre-warm effectiveness |
| `sustained-high` | 3× for 20 min → baseline | ~34 min | CAS scale-down cooldown |
| `burst-and-drop` | 5× for 2 min → baseline | ~10 min | HPA stabilizationWindowSeconds |

All scenarios write a JSON summary to `/results/` inside the Job pod, accessible via `fetch-results`.

### k6 job "Error" status is expected

All k6 jobs will show `Failed` / `Error` in `oc get jobs` when the workload is intentionally misconfigured. **This is correct and desired** — k6 exits non-zero whenever a defined threshold (e.g. error rate > 5%) is breached, which is exactly what the misconfigured HPAs cause.

**Do not treat job `Error` as a test failure.** Check the pod logs for phase completion markers:

```
baseline ✓ [ 100% ]   ← completed
spike    ✓ [ 100% ]   ← completed
recovery ✓ [ 100% ]   ← completed
level=error msg="thresholds on metrics 'errors' have been crossed"  ← expected
```

All three `✓ [ 100% ]` = successful run. The threshold crossing IS the advisor signal — it proves the application degraded under load. If a phase shows `↓` and never reaches 100%, the pod likely OOMKilled.

### Safe RPS limits

The k6 pod memory limit is 1Gi (raised from 512Mi after an OOMKill at 300 RPS on a 2-node cluster):

| Param | Script default | Tested safe (2-node cluster) |
|-------|---------------|------------------------------|
| `SPIKE_RPS` | 300 | **150** — 300 OOMKills the k6 pod |
| `PEAK_RPS` | 150 | 150 |
| `SUSTAINED_RPS` | 90 | 90 |
| `BURST_RPS` | 150 | 150 |

Scale up from 150 only on clusters with ≥ 4 workers or after confirming k6 pod memory headroom with `oc adm top pod`.

### Sequential scenario runs

`run-k6` tails the pod log and waits for the Job to complete before returning, so calling it multiple times in a shell chain (`&&`) runs scenarios sequentially. It retries pod discovery for up to 60 s before giving up.

If you see all scenarios submitting in rapid succession (old behaviour), you are on an outdated `deploy.sh` — pull the latest and re-run.

## Endpoints tested

```
GET /                    40% — homepage
GET /api/products        30% — product catalog
GET /api/cart            20% — cart read
GET /api/recommendations 10% — recommendation widget
```

## Access the web store

```bash
oc port-forward -n otel-demo svc/frontend-proxy 8080:8080 &
open http://localhost:8080          # web store
open http://localhost:8080/grafana  # dashboards
```

## ROSA SCC notes

The install applies `load-test/manifests/scc-otelcol.yaml` which binds:

- `otel-demo` SA → `anyuid` (all microservice pods)
- `grafana` SA → `privileged` (legacy seccomp pod annotations)
- `prometheus` SA → `anyuid`
- `otel-collector` SA → `anyuid`
- `postgresql` SA → `anyuid`

Namespace is created via `oc create namespace` (not `oc apply`) so OpenShift auto-generates the `openshift.io/sa.scc.mcs` annotation. SCC bindings are applied before `helm install` so the chart's service accounts inherit them on creation.

## Optional add-ons

**VPA** (advise-only mode for all services):
```bash
# Install VPA operator first, then:
oc apply -f load-test/manifests/autoscaling/vpa-all-services.yaml
```

**KEDA** (email service queue scaler):
```bash
# Install KEDA operator first, then:
oc apply -f load-test/manifests/autoscaling/email-keda.yaml
```

## Cleanup

```bash
CLUSTER_TYPE=classic ./load-test/deploy.sh uninstall
# Prompts: "Type 'yes' to confirm"
# Removes: Helm release, autoscaling configs, SCC CRBs, namespace
```
