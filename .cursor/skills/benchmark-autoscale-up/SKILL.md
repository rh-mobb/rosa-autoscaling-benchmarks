---
name: benchmark-autoscale-up
description: >-
  Benchmark Cluster Autoscaler scale-up on ROSA. Deploys a workload that
  cannot be scheduled on existing nodes, then measures the time from
  FailedScheduling event to a new node being Ready and the pod running.
  Collects CAS decision events and node provisioning timeline. Use when the
  user wants to measure or demonstrate how long cluster scale-up takes.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill's close-out plus **suite HTML** under **`reports/`**). Do not end after the script invocation. If blocked or partial, still deliver the report or Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Cluster Autoscale Up (Test 03)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa` where used, tmux MCP tools, local `tmux`, and cluster auth).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Trigger a CAS scale-up event by deploying a workload that cannot fit on existing
nodes, then measure the full sequence of events from scheduling failure to pods
running.

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 03-autoscale-up
```

## Tmux context

When running as part of `benchmark-run-all`, execute this test in the **`03-autoscale-up` window** of the `benchmark-<classic|hcp>` session (socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set from session creation — do not re-export unless running this skill standalone. Use `create-window` → `execute-command` → `get-command-result` per the harness in `benchmark-run-all`.

## Prerequisites

- Cluster running (only the default `worker` pool is required — this test creates its own `bench-standard` pool)
- `oc` logged in; `export KUBECONFIG="$PWD/tmp/kubeconfig.<CLUSTER_NAME>.yaml"`

## Inputs

Ask the user:
- `CLUSTER_TYPE`: `classic` or `hcp`
- `CLUSTER_NAME`: the cluster name

## Resolve RUN_ID

The same `RUN_ID` established during test 01 (cluster-install) must be used for all subsequent tests so that all milestone data lands in the same `results/<RUN_ID>/` directory and the HTML reports share the same filename prefix.

Read it directly from the persistent cluster state file written by `make create-*`:

```bash
# All cluster state — run_id, api_url, username, password, kubeconfig — is in:
cat tmp/cluster.${CLUSTER_TYPE}.json

# Extract just the run ID:
RUN_ID=$(python3 -c "
import json, sys
d = json.load(open('tmp/cluster.${CLUSTER_TYPE}.json'))
print(d['run_id'])
")

# Or use the Python helper from bench.py:
RUN_ID=$(python3 -c "
import sys; sys.path.insert(0, 'scripts')
from lib.bench import read_cluster_state
print(read_cluster_state('${CLUSTER_TYPE}').get('run_id', ''))
")
```

If the state file is absent (cluster not yet created or already destroyed), check `python3 scripts/record-event.py ls` for any in-progress runs, or start a new one:

```bash
RUN_ID=$(python3 scripts/record-event.py init \
  --cluster-type "$CLUSTER_TYPE" --cluster-name "$CLUSTER_NAME")
```

## Pre-flight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami   # must succeed before running the script
```

Create the `bench-standard` pool for this test. All workload manifests in this
test use `nodeSelector: pool-type: standard` so they land exclusively on this
pool's nodes.

```bash
make add-pool TYPE=standard CLUSTER="$CLUSTER_NAME"
```

The pool is created with autoscaling enabled. On a multi-AZ cluster it starts
at 3 nodes (ROSA minimum); `cas-trigger.yaml` deploys 20 pause pods (500m/512Mi
each) which overflows those nodes and triggers CAS to scale up.

## Run

```bash
python3 scripts/run-test-03-autoscale-up.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID"
```

The script:
1. Records baseline node names
2. Applies `manifests/workloads/cas-trigger.yaml` (20 pause pods, 500m CPU / 512Mi each)
3. Polls `benchmark` events for `FailedScheduling`
4. Polls `openshift-machine-api` events for `TriggeredScaleUp`
5. Polls for a new Ready node
6. Polls until all `cas-trigger` pods are Running
7. Scales `cas-trigger` to 0 (test 04 deletes it)
8. Writes milestones to `results/$RUN_ID/events.jsonl`
9. Prints a JSON summary to stdout

Expected runtime: **10–20 minutes** (dominated by node provisioning time).

## Recovery

If the script exits non-zero:

```bash
# Check where it failed:
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 03-autoscale-up

# Re-run — the script is idempotent (re-applies manifests, re-polls):
python3 scripts/run-test-03-autoscale-up.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID"
```

Common failure modes:
- **FailedScheduling not observed**: the workload fit on existing nodes — the machine pool may already have extra capacity. Scale down the pool to `min-replicas` first.
- **TriggeredScaleUp not in openshift-machine-api**: CAS may emit this in a different namespace; the script logs a warning and continues to watch for a new node.
- **New node timeout**: check AWS quota, EC2 instance limits, and machine pool max-replicas.

## Report (Cursor Canvas)

Read `results/$RUN_ID/events.jsonl` (or the JSON printed to stdout) and render a Canvas with:

| Event | Time | Elapsed from workload apply |
|-------|------|----------------------------|
| Workload applied | — | 0 |
| First FailedScheduling | — | delta |
| CAS TriggeredScaleUp | — | delta |
| First new node Ready | — | delta |
| All pods Running | — | delta |

Include:
- Before/after node count (`Stat` components)
- CAS decision event message verbatim
- Narrative explaining each phase of the CAS workflow

## Retrospective

After this test completes, append to `docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`.

```markdown
## Test 03 — CAS Scale-Up

**Status:** completed / partial / failed  
**Total time (FailedScheduling → pods Running):** <X>m <Y>s

### Issues Encountered
- <List any problems and resolution status. If none, write: _None._>

### Key Insights
- <CAS decision latency vs EC2 boot time breakdown, any event name differences (e.g. ScaledUpGroup vs TriggeredScaleUp), how this compares to expected 5–8 min range.>
```
