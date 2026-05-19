---
name: benchmark-hpa
description: >-
  Benchmark Horizontal Pod Autoscaler (HPA) response time on ROSA. Deploys the
  cpu-burner workload with an HPA, generates CPU load that breaches the scale
  threshold, then measures time from metric breach to new pods Running. Also
  deploys VPA in advise-only mode alongside HPA to collect resource
  recommendations. Use when the user wants to measure HPA scale-up latency or
  understand the sequence of events when HPA fires.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill's close-out plus **suite HTML** under **`reports/`**). Do not end after the script invocation. If blocked or partial, still deliver the report or Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Horizontal Pod Autoscaler (Test 06)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, tmux MCP tools, local `tmux`, and cluster auth; include `rosa` if machine-pool checks are needed).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Deploy a CPU-intensive workload with HPA at 50% CPU threshold, observe HPA fire
and scale, measure the time from metric breach to all new pods running.
VPA runs in `Off` (advise-only) mode alongside HPA.

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 06-hpa
```

## Tmux context

When running as part of `benchmark-run-all`, execute this test in the **`06-hpa` window** of the `benchmark-<classic|hcp>` session (socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set from session creation — do not re-export unless running this skill standalone. Use `create-window` → `execute-command` → `get-command-result` (with `capture-pane` during the load generation and metric-breach wait) per the harness in `benchmark-run-all`.

## Prerequisites

- Cluster running with at least 2 worker nodes (enough capacity so HPA does not
  trigger CAS — that scenario is covered in test 08)
- VPA operator installed (the script will install it via OLM if missing)
- `oc` logged in; `KUBECONFIG` set

## Resolve RUN_ID

The same `RUN_ID` established during test 01 (cluster-install) must be used for all subsequent tests so that all milestone data lands in the same `results/<RUN_ID>/` directory and the HTML reports share the same filename prefix.

Read it directly from the persistent cluster state file written by `make create-*`:

```bash
# All cluster state — run_id, api_url, username, password, kubeconfig — is in:
cat tmp/cluster.${CLUSTER_TYPE}.json

# Extract just the run ID:
RUN_ID=$(python3 -c "
import json
d = json.load(open('tmp/cluster.${CLUSTER_TYPE}.json'))
print(d['run_id'])
")
```

If the state file is absent, check `python3 scripts/record-event.py ls` for any in-progress runs.

## Pre-flight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami

# Check if VPA operator is already installed:
oc get pods -n openshift-vertical-pod-autoscaler 2>/dev/null | grep vpa || \
  echo "VPA not found — script will install via manifests/autoscaling/vpa-operator-subscription.yaml"
```

## Run

```bash
python3 scripts/run-test-06-hpa.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID"
```

The script:
1. Verifies / installs VPA operator (via `manifests/autoscaling/vpa-operator-subscription.yaml`)
2. Applies `manifests/workloads/cpu-burner.yaml`, `manifests/autoscaling/hpa.yaml`, `manifests/autoscaling/vpa.yaml`
3. Waits for initial pod Ready
4. Records baseline CPU% from HPA status
5. Polls HPA until `averageUtilization > 50%` (metric breach)
6. Polls until `desiredReplicas > 1` (scale decision)
7. Polls until all new pods are Running
8. Reads VPA recommendations
9. Scales cpu-burner back to 1 (HPA and VPA left in place for test 08)
10. Prints JSON summary with milestones and VPA recommendations

Expected runtime: **15–25 minutes** (cpu-burner needs time to accumulate metrics).

## Recovery

```bash
python3 scripts/run-test-06-hpa.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID"
```

Common failure modes:
- **CPU never breaches 50%**: confirm `stress-ng` is running in pods (`oc exec -n benchmark <pod> -- pgrep stress-ng`). The `readinessProbe` uses `pgrep stress-ng` so a non-Running pod means stress-ng is not yet installed.
- **HPA scale decision not observed**: check `oc get hpa cpu-burner-hpa -n benchmark` — confirm `metrics-server` is available (`oc get apiservice v1beta1.metrics.k8s.io`).

## Report (Cursor Canvas)

| Event | Time | Elapsed |
|-------|------|---------|
| Workload applied | — | 0 |
| Initial pod Ready | — | delta |
| CPU breach (>50%) | — | delta |
| HPA scale decision | — | delta |
| All new pods Running | — | delta |

Include:
- **Stat row**: Initial replicas → peak replicas, time to scale
- **HPA events** verbatim (`SuccessfulRescale` messages)
- **VPA Recommendations** table: Container | Requested CPU | VPA Target | Requested Memory | VPA Target Memory
- **Narrative**: HPA polling interval, metric aggregation window, why there is a delay between load start and HPA firing

## Retrospective

After this test completes, append to `docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`.

```markdown
## Test 06 — HPA Response

**Status:** completed / partial / failed  
**Time (metric breach → pods Ready):** <X>s

### Issues Encountered
- <List any problems and resolution status. If none, write: _None._>

### Key Insights
- <HPA decision latency, whether existing node capacity was sufficient, replica scale ratio, any workload or image issues encountered.>
```
