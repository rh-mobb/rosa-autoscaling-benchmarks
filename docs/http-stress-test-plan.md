# HTTP Stress Test Plan — Test 12-HTTP

Extends the sudden-spike benchmark (Test 12) with a real HTTP load generator
so the degradation window is measured in actual error rates and latency
percentiles rather than derived from pod-readiness timing.

## Motivation

The current Test 12 (`benchmark-sudden-spike`) measures the autoscaling
infrastructure chain — HPA decision, pod scheduling, node provisioning — and
derives estimated user impact from those timings. This is sufficient for
executive demos but does not capture:

- TCP connection backlog exhaustion before pods go `Pending`
- P99/P999 latency degradation that precedes full saturation
- Load balancer queuing and retry behaviour
- Pod startup latency under real incoming load
- Cascading failures from upstream timeouts
- Revenue impact of slow-but-successful responses (vs. outright errors)

The HTTP stress test replaces those probabilistic estimates with empirical
per-second 2xx/5xx counts and latency histograms across both phases of the
spike scenario.

## Scope

This plan covers three additions to the existing benchmark:

1. Replace the `cpu-burner` workload with an HTTP-serving equivalent
2. Deploy a `k6` load generator as an in-cluster Kubernetes Job
3. Instrument `run-test-12-sudden-spike.py` to parse and record HTTP metrics

No changes to the HPA trigger, balloon pod setup, CAS/Karpenter chain, or
Canvas report structure. The new HTTP milestones slot into `result.extra`
alongside the existing pod-readiness milestones.

---

## Step 1 — Replace `cpu-burner` with an HTTP workload

### What changes

The current `cpu-burner` container runs `yes > /dev/null` — it burns CPU but
serves no HTTP. Replace it with a small server that:

- Exposes `GET /burn?ms=N` — each request sleeps `N` ms (configurable via env)
  to simulate application work under load, consuming proportional CPU
- Exposes `GET /healthz` — used by the readiness probe (unchanged)
- Exposes `GET /metrics` — Prometheus counter of requests served, 5xx errors,
  and a histogram of response latency

### Implementation

A ~50-line Go HTTP handler is sufficient. Alternatively, use
[`wrk2`](https://github.com/giltene/wrk2) with a compatible Lua script if
you prefer not to build a custom image.

```go
// cmd/http-burner/main.go
package main

import (
    "net/http"
    "os"
    "strconv"
    "time"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

func burnHandler(w http.ResponseWriter, r *http.Request) {
    ms, _ := strconv.Atoi(r.URL.Query().Get("ms"))
    if ms > 0 {
        time.Sleep(time.Duration(ms) * time.Millisecond)
    }
    w.WriteHeader(http.StatusOK)
}

func main() {
    burnMs := os.Getenv("BURN_MS") // default 50 — simulates ~20 RPS/core
    _ = burnMs
    http.HandleFunc("/burn", burnHandler)
    http.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
        w.WriteHeader(http.StatusOK)
    })
    http.Handle("/metrics", promhttp.Handler())
    http.ListenAndServe(":8080", nil)
}
```

Build and push to the project's container registry, then update
`manifests/benchmark/cpu-burner.yaml`:

```yaml
containers:
  - name: cpu-burner
    image: <registry>/http-burner:latest
    ports:
      - containerPort: 8080
    env:
      - name: BURN_MS
        value: "50"   # tune per instance type to reach target CPU %
    readinessProbe:
      httpGet:
        path: /healthz
        port: 8080
```

A `Service` of type `ClusterIP` is sufficient — the k6 generator runs
in-cluster.

---

## Step 2 — Deploy `k6` as an in-cluster Job

### What changes

`k6` runs as a Kubernetes `Job` in the `benchmark` namespace, generating a
constant baseline RPS before the spike trigger, then stepping up to spike RPS
at T=0.

### k6 script

```javascript
// manifests/benchmark/k6-spike-script.js
import http from 'k6/http';
import { sleep } from 'k6';

const BASE_URL = `http://${__ENV.TARGET_SVC}/burn?ms=50`;
const BASELINE_RPS = parseInt(__ENV.BASELINE_RPS, 10) || 100;
const SPIKE_RPS    = parseInt(__ENV.SPIKE_RPS,    10) || 400;
const SPIKE_AT_S   = parseInt(__ENV.SPIKE_AT_S,   10) || 60;
const TOTAL_S      = parseInt(__ENV.TOTAL_S,      10) || 600;

export const options = {
  scenarios: {
    baseline: {
      executor: 'constant-arrival-rate',
      rate: BASELINE_RPS,
      timeUnit: '1s',
      duration: `${SPIKE_AT_S}s`,
      preAllocatedVUs: BASELINE_RPS * 2,
    },
    spike: {
      executor: 'constant-arrival-rate',
      rate: SPIKE_RPS,
      timeUnit: '1s',
      startTime: `${SPIKE_AT_S}s`,
      duration: `${TOTAL_S - SPIKE_AT_S}s`,
      preAllocatedVUs: SPIKE_RPS * 2,
    },
  },
  summaryTrendStats: ['avg', 'p(95)', 'p(99)', 'p(99.9)'],
};

export default function () {
  http.get(BASE_URL);
  sleep(0);
}
```

### Job manifest

```yaml
# manifests/benchmark/k6-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: k6-spike-load
  namespace: benchmark
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: k6
          image: grafana/k6:latest
          args:
            - run
            - --out
            - csv=/results/k6-output.csv
            - /scripts/k6-spike-script.js
          env:
            - name: TARGET_SVC
              value: "cpu-burner:8080"
            - name: BASELINE_RPS
              value: "100"
            - name: SPIKE_RPS
              value: "400"
            - name: SPIKE_AT_S
              value: "60"
            - name: TOTAL_S
              value: "660"
          volumeMounts:
            - name: scripts
              mountPath: /scripts
            - name: results
              mountPath: /results
      volumes:
        - name: scripts
          configMap:
            name: k6-spike-script
        - name: results
          emptyDir: {}
```

The benchmark script `exec`s `kubectl cp` to retrieve `/results/k6-output.csv`
after the Job completes.

---

## Step 3 — Instrument `run-test-12-sudden-spike.py`

### Changes to the script

Add a `--http-load` flag (default `False`) that:

1. Creates the `k6-spike-script` ConfigMap before Phase 1
2. Launches the `k6-job` Job at the same moment the HPA is applied (`t_surge`)
3. Streams k6 stdout (per-second CSV) to a temp file
4. After each phase completes, parses the CSV and records into `result.extra`:

```python
# HTTP metrics recorded per phase
result.extra["phase1.total_requests"]  = ...
result.extra["phase1.total_5xx"]       = ...
result.extra["phase1.error_rate_pct"]  = ...
result.extra["phase1.p99_ms"]          = ...
result.extra["phase1.degradation_window_s"] = ...  # seconds until error_rate < 1%

result.extra["phase2.total_requests"]  = ...
result.extra["phase2.total_5xx"]       = ...
result.extra["phase2.error_rate_pct"]  = ...
result.extra["phase2.p99_ms"]          = ...
result.extra["phase2.degradation_window_s"] = ...
```

No schema changes — `result.extra` already accepts arbitrary keys. The Canvas
closes the loop: when these keys are present it renders measured values instead
of the probabilistic model.

### Invocation with HTTP load

```bash
python3 scripts/run-test-12-sudden-spike.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --target-replicas 10 \
  --balloon-replicas 5 \
  --http-load \
  --baseline-rps 100 \
  --spike-rps 400 \
  --timeout 3600
```

---

## What you get after the HTTP run

| Metric | Phase 1 — no prep | Phase 2 — balloon pods |
|--------|-------------------|------------------------|
| Total HTTP requests | measured | measured |
| Total 5xx errors | **measured** | **measured** |
| Peak error rate | **measured** | **measured** |
| P99 latency | **measured** | **measured** |
| Degradation window | measured (seconds until <1% error rate) | measured |
| Revenue at risk | computed from measured error count | computed |

These replace the probabilistic estimates in the End-User Impact Model canvas.

---

## Effort estimate

| Task | Effort |
|------|--------|
| Build and push `http-burner` image | ~2 h |
| Write and test k6 script + Job manifest | ~1 h |
| Instrument `run-test-12-sudden-spike.py` | ~3 h |
| Re-run Test 12 with `--http-load` | ~2 h |
| **Total** | **~1–2 days** |

---

## Decision guide

| Audience | Recommendation |
|----------|----------------|
| Executive / customer demo | Probabilistic model (current) is sufficient |
| Engineering review | HTTP stress test — exact 5xx counts and latency distributions |
| SLA validation | HTTP stress test — required for SLA threshold evidence |
| CAS vs Karpenter comparison | Either — pod-readiness delta is the same regardless of traffic model |
