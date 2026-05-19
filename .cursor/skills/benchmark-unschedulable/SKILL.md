---
name: benchmark-unschedulable
description: >-
  Demonstrate what happens when a workload exceeds the capacity of the
  configured autoscaler. On Classic/HCP (CAS) clusters: shows FailedScheduling
  and NotTriggerScaleUp — CAS refuses to scale because its machine pool is
  locked to m5.xlarge and cannot change instance types. On hcp-autonode
  (Karpenter) clusters: runs test 05b instead — the same workload sized to
  exceed m5.xlarge but fit r5.8xlarge, showing that Karpenter dynamically
  selects the right instance type and schedules the pod successfully. Use when
  the user wants to understand or demonstrate static vs dynamic instance
  selection, or the CAS NotTriggerScaleUp behaviour.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill's close-out plus **suite HTML** under **`reports/`**). Do not end after the script invocation. If blocked or partial, still deliver the report or Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

## Cluster-type routing

| Cluster type | Test to run | Script |
|---|---|---|
| `classic` or `hcp` (CAS) | **Test 05** — CAS refuses with `NotTriggerScaleUp` | `run-test-05-unschedulable.py` |
| `hcp-autonode` (Karpenter) | **Test 05b** — Karpenter selects r5.8xlarge and succeeds | `run-test-05b-dynamic-instance.py` |

Run the appropriate test for the cluster type. Both tests share the same Canvas close-out structure (see [Report](#report-cursor-canvas) and [Report (05b)](#report-cursor-canvas-test-05b) below).

---

# Benchmark: Unschedulable Oversize Workload (Test 05)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa` where used, tmux MCP tools, local `tmux`, and cluster auth).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Apply a pod that requests more resources than any single node in the cluster
can provide, then observe and explain the CAS decision NOT to scale up.

The `oversize-workload` pod in `manifests/workloads/memory-hog.yaml` requests
**200 CPU / 1 TiB memory**. An m5.xlarge node has 4 vCPU / 16 GiB RAM. CAS
will emit `NotTriggerScaleUp` because no node group can satisfy the request.

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 05-unschedulable
```

## Tmux context

When running as part of `benchmark-run-all`, execute this test in the **`05-unschedulable` window** of the `benchmark-<classic|hcp>` session (socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set from session creation — do not re-export unless running this skill standalone. Use `create-window` → `execute-command` → `get-command-result` per the harness in `benchmark-run-all`.

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
```

Create the `bench-standard` pool for this test so CAS has an m5.xlarge node
group to evaluate against the oversize request:

```bash
make add-pool TYPE=standard CLUSTER="$CLUSTER_NAME"
```

## Run

```bash
python3 scripts/run-test-05-unschedulable.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID"
```

The script:
1. Records baseline node count
2. Applies `manifests/workloads/memory-hog.yaml` (creates `oversize-workload` pod and removes the competing `memory-hog` pod)
3. Polls `benchmark` events for `FailedScheduling` on `oversize-workload`
4. Searches `openshift-machine-api` / `kube-system` events for `NotTriggerScaleUp`
5. Waits 5 minutes then confirms node count is unchanged
6. Deletes `oversize-workload` pod (cleanup)
7. Prints JSON summary with event messages and node count confirmation

Expected runtime: **~8 minutes** (5 min confirm wait + event polling).

## Recovery

```bash
python3 scripts/run-test-05-unschedulable.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID"
```

The script is idempotent (re-applies manifest, ignores-not-found on delete).

## Cleanup

After the Canvas is delivered, delete the `bench-standard` pool:

```bash
make remove-pool NAME=bench-standard CLUSTER="$CLUSTER_NAME"
```

## Report (Cursor Canvas)

Present:
- Pod resource request vs largest available node (table comparison)
- `FailedScheduling` event message verbatim
- `NotTriggerScaleUp` event message verbatim with explanation of each part
- Node count before and after (confirms CAS did not scale)
- Narrative: CAS decision logic — why it cannot change instance types
- Recommendations: use a larger machine pool instance type, or split the workload

## Retrospective

After this test completes, append to `docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`.

```markdown
## Test 05 — Unschedulable (CAS NotTriggerScaleUp)

**Status:** completed / partial / failed  
**Time to NotTriggerScaleUp:** <X>s

### Issues Encountered
- <List any problems and resolution status. If none, write: _None._>

### Key Insights
- <Actual pod request vs node capacity, how quickly CAS recognised the situation, whether this was a realistic misconfiguration scenario.>
```

---

# Benchmark: Dynamic Instance Selection (Test 05b) — hcp-autonode only

Demonstrates the inverse of test 05: a workload that CAS **cannot** schedule
(because its machine pool is locked to m5.xlarge) but Karpenter **can** schedule
by dynamically selecting an `r5.8xlarge` from the flexible NodePool.

| | CAS (test 05) | Karpenter (test 05b) |
|---|---|---|
| Workload | 200 CPU / 1 TiB | 28 CPU / 200 GiB |
| Instance pool | m5.xlarge only | r5.8xlarge, r5.16xlarge, r5.24xlarge |
| Outcome | `NotTriggerScaleUp` — refuses | NodeClaim → r5.8xlarge → pod Running |
| Key insight | Machine pools are static contracts | Karpenter is a demand-driven instance broker |

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 05b-dynamic-instance
```

## Tmux context

Execute in the **`05b-dynamic-instance` window** of the `benchmark-hcp-autonode` session
(socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set.

## Prerequisites

- ROSA HCP cluster with AutoNode enabled (`ec2nodeclass/default` READY=True)
- `oc` logged in; `KUBECONFIG` set

## Pre-flight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami
oc get ec2nodeclass   # must show default READY=True
```

## Run

```bash
python3 scripts/run-test-05b-dynamic-instance.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type hcp-autonode \
  --run-id "$RUN_ID"
```

The script:
1. Records baseline node and NodeClaim counts
2. Applies `manifests/autonode/nodepool-flexible.yaml` (r5.8xlarge/r5.16xlarge/r5.24xlarge)
3. Applies `manifests/workloads/large-workload-cas-unschedulable.yaml` (28 CPU / 200 GiB)
4. Waits for `FailedScheduling` (pod is initially Pending)
5. Waits for a new `NodeClaim` to appear in the `autonode-flexible` pool
6. Waits for the new node to become Ready
7. Waits for the pod to reach `Running`
8. Records the instance type Karpenter selected
9. Cleans up the pod and NodePool

Expected runtime: **15–25 minutes** (cold EC2 provision for r5.8xlarge).

## Recovery

```bash
python3 scripts/run-test-05b-dynamic-instance.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type hcp-autonode \
  --run-id "$RUN_ID"
```

Common failure modes:
- **No NodeClaim appears**: confirm `ec2nodeclass/default` is READY=True and the
  `autonode-flexible` NodePool exists (`oc get nodepool autonode-flexible`)
- **Pod stays Pending after NodeClaim**: check node taints and the pod's tolerations
  (`oc describe pod large-workload -n benchmark`)

## Report (Cursor Canvas) — Test 05b

Present as a side-by-side contrast with the CAS test 05 result:

**Contrast table:**

| | CAS (test 05) | Karpenter (test 05b) |
|---|---|---|
| Workload request | 200 CPU / 1 TiB | 28 CPU / 200 GiB |
| Pool instance type | m5.xlarge (4 vCPU / 16 GiB) | flexible (r5 family) |
| Autoscaler decision | `NotTriggerScaleUp` | NodeClaim created |
| Instance selected | — | r5.8xlarge (32 vCPU / 256 GiB) |
| Pod outcome | Stays Pending forever | Running |

**Milestone timeline (05b):**

| Event | Time | Elapsed |
|---|---|---|
| Pod applied | — | 0 |
| FailedScheduling | — | delta |
| NodeClaim created (r5.8xlarge) | — | delta |
| Node Ready | — | delta |
| Pod Running | — | delta |

Include:
- Narrative explaining CAS machine pool constraints vs Karpenter's instance-type
  evaluation loop
- The `NotTriggerScaleUp` event message from test 05 verbatim alongside the
  NodeClaim creation event from test 05b
- Recommendation: for workloads with variable or unpredictable resource needs,
  Karpenter's dynamic instance selection removes the operational burden of
  pre-configuring the right machine pool

## Retrospective

After this test completes, append to `docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`.

```markdown
## Test 05b — Dynamic Instance Selection (Karpenter)

**Status:** completed / partial / failed  
**Time (pod Pending → Running):** <X>m<Y>s  
**Instance type selected:** <r5.8xlarge | other>

### Issues Encountered
- <List any problems and resolution status. If none, write: _None._>

### Key Insights
- <Whether Karpenter selected the expected instance type, how long EC2 provision took, any NodePool configuration issues.>
```
