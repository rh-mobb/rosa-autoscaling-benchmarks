---
name: benchmark-hpa-triggers-cas
description: >-
  Benchmark the end-to-end scenario where HPA fires but there is insufficient
  cluster capacity, forcing Cluster Autoscaler to provision new nodes before
  pods can run. Measures the total time from CPU metric breach to final pod
  Running state, and shows every step in the chain: HPA scale decision,
  pod Pending, CAS TriggeredScaleUp, new node Ready, pod scheduled. Use when
  the user wants to understand or demonstrate the HPA-to-CAS cascade and
  measure its total latency.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill's close-out plus **suite HTML** under **`reports/`**). Do not end after the script invocation. If blocked or partial, still deliver the report or Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: HPA Triggers Cluster Autoscaler (Test 08)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, tmux MCP tools, local `tmux`, and cluster auth; include `rosa` if machine-pool checks are needed).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

This is the most operationally realistic scenario: HPA decides to scale the
application, but the cluster has no spare capacity, so CAS must provision new
nodes before the pods can run.

Measure the full end-to-end time: scale trigger → HPA fires → pods Pending →
CAS triggered → new node Ready → pods Running.

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 08-hpa-triggers-cas
```

## Tmux context

When running as part of `benchmark-run-all`, execute this test in the **`08-hpa-cas` window** of the `benchmark-<classic|hcp>` session (socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set from session creation — do not re-export unless running this skill standalone. Use `create-window` → `execute-command` → `get-command-result` (with `capture-pane` during the CAS provisioning wait, which can take 10–15 min) per the harness in `benchmark-run-all`.

## Prerequisites

- Cluster running (only the default `worker` pool is required — this test creates its own `bench-standard` pool)
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
oc get nodes    # note current node count
```

Create the `bench-standard` pool for this test. `capacity-filler.yaml` and
`cpu-burner.yaml` both target `nodeSelector: pool-type: standard`, so all
workload pods land exclusively on this pool's nodes:

```bash
make add-pool TYPE=standard CLUSTER="$CLUSTER_NAME"
```

## Run

```bash
python3 scripts/run-test-08-hpa-triggers-cas.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --timeout 2400
```

Optional: `--cpu-burner-replicas 3` (default: 3).

The script:
1. Records baseline node names
2. Applies `manifests/workloads/capacity-filler.yaml` (10 pause pods, 400m/400Mi) to saturate cluster
3. Ensures `cpu-burner` + HPA are deployed
4. Scales `cpu-burner` to target replicas (manual HPA trigger)
5. Polls for `FailedScheduling` (pods Pending)
6. Polls `openshift-machine-api` for `TriggeredScaleUp`
7. Polls for a new Ready node
8. Polls until all `cpu-burner` pods are Running
9. Collects `FailedScheduling` event messages
10. Scales `capacity-filler` to 0 and `cpu-burner` to 1 (cleanup)
11. Prints JSON summary with full cascade milestones

Expected runtime: **15–30 minutes** (node provisioning dominates).

## Recovery

```bash
python3 scripts/run-test-08-hpa-triggers-cas.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --timeout 2400
```

Common failure modes:
- **No FailedScheduling**: cluster had spare capacity beyond capacity-filler. The script logs a warning and continues; if a new node was still provisioned the cascade timings are valid.
- **TriggeredScaleUp not observed**: CAS may use a different namespace or event reason. Script logs a warning and continues watching for a new node.
- **New node timeout**: check machine pool max-replicas and AWS quota.

## Cleanup

After the Canvas is delivered, delete the `bench-standard` pool:

```bash
make remove-pool NAME=bench-standard CLUSTER="$CLUSTER_NAME"
```

## Report (Cursor Canvas)

| Event | Time | Elapsed from baseline |
|-------|------|----------------------|
| Baseline recorded | — | 0 |
| HPA scale trigger | — | delta |
| Pods go Pending | — | delta |
| CAS TriggeredScaleUp | — | delta |
| New node Ready | — | delta |
| All pods Running | — | delta |

Include:
- **Stat row**: Total cascade time | CAS provisioning time | HPA→pending time
- **FailedScheduling** event messages verbatim
- **Narrative**: Multi-layer cascade and why total time = HPA decision + CAS provisioning + node init + pod startup
- **Comparison note**: Test 09 eliminates the CAS wait via overprovisioning

## Retrospective

After this test completes, append to `docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`.

```markdown
## Test 08 — HPA Triggers CAS

**Status:** completed / partial / failed  
**Total cascade time (HPA trigger → pods Ready):** <X>m <Y>s

### Issues Encountered
- <List any problems and resolution status. If none, write: _None._>

### Key Insights
- <Whether a cold or pre-warmed node was observed, breakdown of HPA decision vs CAS vs EC2 boot vs pod startup, how this compares to test 03 CAS scale-up baseline.>
```
