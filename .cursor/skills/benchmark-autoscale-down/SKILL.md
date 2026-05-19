---
name: benchmark-autoscale-down
description: >-
  Benchmark Cluster Autoscaler scale-down on ROSA. Removes the workload that
  triggered scale-up (test 03), then measures how long CAS takes to identify
  underutilized nodes, cordon and drain them, and terminate the underlying EC2
  instances. Shows CAS scale-down events, the cooldown period, and final node
  count. Use when the user wants to measure or demonstrate how long cluster
  scale-down takes and understand the CAS cooldown behavior.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill's close-out plus **suite HTML** under **`reports/`**). Do not end after the script invocation. If blocked or partial, still deliver the report or Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Cluster Autoscale Down (Test 04)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa` where used, tmux MCP tools, local `tmux`, and cluster auth).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Remove the scale-up workload and observe CAS scale-down: underutilized node
detection, cordon/drain sequence, and node termination — including the mandatory
CAS cooldown period.

## Key CAS Scale-Down Behavior

CAS only removes a node when ALL of the following are true:
1. Node CPU utilization < 50% for `scale-down-unneeded-time` (default: 10 min)
2. All pods on the node can be rescheduled elsewhere
3. No PodDisruptionBudget violations would occur
4. `scale-down-delay-after-add` has elapsed (default: 10 min after any scale-up)

**Expected total wait: 10–25 minutes** after workload removal.

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 04-autoscale-down
```

## Tmux context

When running as part of `benchmark-run-all`, execute this test in the **`04-autoscale-down` window** of the `benchmark-<classic|hcp>` session (socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set from session creation — do not re-export unless running this skill standalone. Use `create-window` → `execute-command` → `get-command-result` (with `capture-pane` for progress during the 10–25 min cooldown wait) per the harness in `benchmark-run-all`.

## Prerequisites

- Test 03 has been run; `bench-standard` pool exists with extra nodes from the scale-up
- `cas-trigger` deployment exists in `benchmark` namespace (scaled to 0 after test 03)
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
oc get nodes   # confirm extra nodes from test 03 are still present
```

## Run

```bash
python3 scripts/run-test-04-autoscale-down.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --timeout 2400
```

Optional: pass `--baseline-count N` if you know the exact pre-test-03 node count.

The script:
1. Records current node count (post test-03, with extra nodes)
2. Deletes `deployment/cas-trigger` in `benchmark`
3. Polls for the first node to be cordoned (SchedulingDisabled)
4. Polls until node count drops to target (current − 1, or `--baseline-count`)
5. Writes milestones to `results/$RUN_ID/events.jsonl`
6. Prints JSON summary to stdout

Expected runtime: **15–25 minutes** (CAS cooldown dominates).

## Recovery

```bash
# Re-run — idempotent; deletes cas-trigger again (ignore-not-found) and polls:
python3 scripts/run-test-04-autoscale-down.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --timeout 2400
```

If the timeout is exceeded: CAS may still be in its cooldown window. Wait 5 minutes and re-run.

## Cleanup

After the Canvas is delivered, delete the `bench-standard` pool that was created
by test 03:

```bash
make remove-pool NAME=bench-standard CLUSTER="$CLUSTER_NAME"
```

AWS terminates the EC2 instances asynchronously. The cluster returns to the
baseline `worker` pool. Subsequent tests (05, 08, 09, 11–13) each create their
own `bench-standard` pool at the start of that test.

## Report (Cursor Canvas)

| Event | Time | Elapsed from workload removal |
|-------|------|-------------------------------|
| Workload removed | — | 0 |
| First node cordoned | — | delta |
| Pods drained | — | delta |
| First node removed | — | delta |
| Cluster back to baseline | — | delta |

Include:
- Before/after node count (`Stat` components)
- Explanation of CAS cooldown period and why it exists
- Comparison of scale-down time to scale-up time from test 03

## Retrospective

After this test completes, append to `docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`.

```markdown
## Test 04 — CAS Scale-Down

**Status:** completed / partial / failed  
**Total time (workload removal → node gone):** <X>m <Y>s

### Issues Encountered
- <List any problems and resolution status. If none, write: _None._>

### Key Insights
- <How much of the scale-down time was cooldown vs drain, whether the default 10-min cooldown dominated, comparison to scale-up time from test 03.>
```
