---
name: benchmark-spot-instances
description: >-
  Benchmark spot instance autoscaling on ROSA Classic and ROSA HCP AutoNode
  (test 15). Measures the end-to-end provisioning chain from workload deployment
  to pods Running on EC2 Spot capacity, then compares against the equivalent
  on-demand run (test 03 for Classic, test 10 for AutoNode). Skipped
  automatically on standard HCP (no spot support without AutoNode). Delivers a
  Cursor Canvas with a spot vs. on-demand comparison table and provisioning
  timeline. Use when the user wants to understand spot provisioning latency,
  validate spot support, or compare spot vs. on-demand cost/speed trade-offs.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**Cursor Canvas** with spot vs. on-demand comparison). Do not end after `make run-test-15` alone. If blocked or partial, still deliver the Canvas with a failed/partial narrative.

# Benchmark: Spot Instance Autoscaling (Test 15)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa` for Classic flows, tmux MCP tools, local `tmux`, and cluster auth).
Require Python 3.11+ for harness scripts (`record-event.py` uses `datetime.UTC`).

Prefer the repo virtual environment before running the test:

```bash
source .venv/bin/activate
python3 -V   # expect 3.11+
```

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Measure end-to-end latency for autoscaling onto EC2 Spot instances.

## Supported cluster types

| Cluster type | Support |
|---|---|
| `classic` | **Run** — ROSA CAS with `--use-spot-instances` machine pool |
| `hcp-autonode` | **Run** — Karpenter NodePool with `capacity-type: spot` |
| `hcp` | **Skip** — standard ROSA HCP does not expose spot via machine pools |

## What is measured

```
workload applied
  ↓ workload_applied_to_failed_scheduling
FailedScheduling event
  ↓ failed_scheduling_to_scheduler_triggered
CAS TriggeredScaleUp  OR  Karpenter NodeClaim created
  ↓ scheduler_triggered_to_node_ready
First spot node Ready
  ↓ node_ready_to_pods_running
Pods Running
════════════════════════════════════════════════
workload_applied_to_pods_running  (total headline metric)
```

**Classic-only milestone:**
- `pool_submitted_to_first_node_ready` — from `rosa create machinepool` to first Ready node
  (the pool starts at `min-replicas=0`, so this spans the entire scale-from-zero path)

**AutoNode-only milestones:**
- `failed_scheduling_to_nodeclaim` — Karpenter's provisioning decision latency
- `nodeclaim_to_node_ready` — EC2 spot Fleet launch → node Ready

**Comparison output (`on_demand_baseline_ms` in JSON result):**
When `--run-id` is provided, the script loads equivalent on-demand milestones
from `events.jsonl` (test 03 for Classic, test 10 for AutoNode) and surfaces
them alongside spot timings in the Canvas.

## Mandatory close-out (agents)

1. **Preflight:** Verify `oc whoami` succeeds and `KUBECONFIG` is set to
   `tmp/kubeconfig.<CLUSTER_NAME>.yaml`. If not, `oc login` first.
2. **Execution:** Run `make run-test-15` to completion (success or timeout).
   The test creates and deletes its own resources; it is safe to re-run.
3. **Canvas:** After the test, render a Canvas (see **Step 4** below) with a
   spot vs. on-demand comparison table, provisioning timeline, and narrative.
4. **Checkpoint/events:** Update `checkpoint.py` and `record-event.py` per
   **Checkpoint & Resume** below when a `RUN_ID` is in play.

## Checkpoint & Resume

```bash
python3 scripts/record-event.py ls
STATUS=$(python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 15-spot-instances)
# If "completed", load results from events.jsonl and skip to Canvas rendering
```

Mark progress:
```bash
python3 scripts/checkpoint.py start    --run-id "$RUN_ID" --test 15-spot-instances
# ... run the test ...
python3 scripts/checkpoint.py complete --run-id "$RUN_ID" --test 15-spot-instances
# On failure:
python3 scripts/checkpoint.py fail     --run-id "$RUN_ID" --test 15-spot-instances --reason "spot capacity unavailable"
```

## Preflight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.<CLUSTER_NAME>.yaml"
oc whoami   # must succeed before running the test

# hcp-autonode only — verify AutoNode is ready
oc get ec2nodeclass default -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# expected: True
```

## Step 1 — Run the test

```bash
make run-test-15 CLUSTER=<name> TYPE=<classic|hcp-autonode> \
  [RUN_ID=<run-id>] \
  [SPOT_MAX_PRICE=0.20]   # classic only; omit to cap at on-demand price
```

Alternative direct invocation:
```bash
python3 scripts/run-test-15-spot-instances.py \
    --cluster-name <name> \
    --cluster-type <classic|hcp-autonode> \
    [--run-id <RUN_ID>] \
    [--nodepool-name autonode-spot]      # hcp-autonode only
    [--spot-max-price 0.20]              # classic only
    [--timeout 1800]
```

**Expected run times:**
- Classic: 8–20 min (spot provisioning is usually within the on-demand range,
  but can be slower if capacity is thin in the target AZ)
- AutoNode: 4–8 min (Karpenter uses EC2 Fleet API — same fast path as on-demand
  but targeting the spot capacity pool)

## Step 2 — What to observe during the run

| Phase | What to watch |
|---|---|
| Classic pool creation | `rosa describe machinepool -c <name> --machinepool bench-spot` |
| FailedScheduling | `oc get events -n spot-test --sort-by=.lastTimestamp` |
| CAS trigger (Classic) | `oc get events -n openshift-machine-api --sort-by=.lastTimestamp` |
| NodeClaim (AutoNode) | `oc get nodeclaims -l karpenter.sh/nodepool=autonode-spot` |
| Node Ready | `oc get nodes -l pool-type=spot` (Classic) or `oc get nodes -l autonode-spot=true` (AutoNode) |
| Capacity type (AutoNode) | `oc get node <name> -o jsonpath='{.metadata.labels.karpenter\.sh/capacity-type}'` |

## Step 3 — Key result fields

After the test, the JSON result file (`results/<RUN_ID>/<TEST_ID>.json`) contains:

```json
{
  "milestones": {
    "workload_applied_to_failed_scheduling": { "elapsed_ms": ... },
    "failed_scheduling_to_scheduler_triggered": { "elapsed_ms": ... },
    "scheduler_triggered_to_node_ready": { "elapsed_ms": ... },
    "node_ready_to_pods_running": { "elapsed_ms": ... },
    "workload_applied_to_pods_running": { "elapsed_ms": ... },
    // Classic only:
    "pool_submitted_to_first_node_ready": { "elapsed_ms": ... },
    // AutoNode only:
    "failed_scheduling_to_nodeclaim": { "elapsed_ms": ... },
    "nodeclaim_to_node_ready": { "elapsed_ms": ... }
  },
  "extra": {
    "capacity_type": "spot",
    "scheduler": "cas | autonode",
    "nodeclaim_capacity_type": "spot",   // AutoNode: label from NodeClaim
    "first_spot_node": "<node-name>",
    "on_demand_baseline_ms": {
      "03-autoscale-up.workload_applied_to_pods_running": ...,  // Classic
      "10-autonode-scale.initial.pending_to_pods_running": ...  // AutoNode
    }
  }
}
```

## Step 4 — Render Canvas

Create a Canvas with:

1. **Headline metrics** — `workload_applied_to_pods_running` for spot and on-demand
   side-by-side (use `StatCard` or similar). Highlight the delta.

2. **Provisioning timeline** — a step-by-step breakdown table:

   | Phase | Spot (ms) | On-demand (ms) | Δ |
   |---|---|---|---|
   | Workload → FailedScheduling | ... | ... | ... |
   | FailedScheduling → Scheduler decision | ... | ... | ... |
   | Scheduler decision → Node Ready | ... | ... | ... |
   | Node Ready → Pods Running | ... | ... | ... |
   | **Total** | **...** | **...** | **...** |

3. **Spot-specific observations** (AutoNode):
   - Confirmed `capacity-type=spot` on the NodeClaim label
   - Instance type selected by Karpenter (m5.xlarge or r5.xlarge fallback)

4. **Capacity warning** (if spot provisioning failed or timed out):
   - Which AZ was targeted, what the error was, suggested mitigation
     (add more instance types to the NodePool, try a different region/AZ)

5. **Narrative** — 3–5 sentences explaining:
   - Whether spot was meaningfully slower than on-demand in this run
   - The cost trade-off (spot is typically 60–90 % cheaper than on-demand)
   - Whether spot is suitable for the workload type (interruptible / non-critical)
   - For AutoNode: that Karpenter handles spot interruption notices and
     automatically re-provisions on another instance type

## Classic: spot machine pool details

The test creates a machine pool named `bench-spot` with:
```
--use-spot-instances
--enable-autoscaling
--min-replicas 0
--max-replicas 6
--labels benchmark=true,pool-type=spot
```
(`max-replicas` is **6** so multi-AZ Classic clusters satisfy ROSA’s “multiple of 3” rule; single-AZ would accept smaller caps.)

The pool starts at `min=0` so the benchmark captures the complete cold-start
provisioning chain. The `bench-spot` pool is deleted at the end of the test.

**Optional SPOT_MAX_PRICE:** If `SPOT_MAX_PRICE` is set, ROSA passes
`--spot-max-price <value>` to cap the maximum hourly bid. Omit it to use the
on-demand price as the ceiling (ROSA default), which makes interruptions rarer
but more expensive.

## AutoNode: spot NodePool details

The test applies `manifests/autonode/nodepool-spot.yaml` which configures:
```yaml
requirements:
  - key: node.kubernetes.io/instance-type
    operator: In
    values: [m5.xlarge, r5.xlarge]   # two types → Karpenter picks the cheapest available
  - key: karpenter.sh/capacity-type
    operator: In
    values: [spot]
disruption:
  consolidationPolicy: WhenEmptyOrUnderutilized
  consolidateAfter: 30s
```

Allowing two instance types is intentional and follows the AWS spot best-practice
of diversifying across multiple instance families to reduce interruption frequency.
Karpenter selects the cheapest available spot instance at launch time.

## Cleanup

The test script deletes its own resources on completion and on SIGINT:
- `spot-test` namespace (both cluster types)
- `bench-spot` machine pool (Classic)
- `autonode-spot` NodePool (AutoNode)

If the test exits mid-run without cleanup, run:
```bash
# Classic
oc delete namespace spot-test --ignore-not-found
rosa delete machinepool -c <name> --machinepool bench-spot --yes

# AutoNode
oc delete namespace spot-test --ignore-not-found
oc delete nodepool autonode-spot --ignore-not-found
```

## Retrospective

After this test completes, append to
`docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`:

```markdown
## Test 15 — Spot Instance Autoscaling

**Status:** completed / partial / failed

### Issues Encountered
- <List any capacity-unavailable errors, AZ constraints, or unexpected timeouts. If none, write: _None._>

### Key Insights
- <Spot vs. on-demand provisioning delta, whether Karpenter selected the expected instance type, any interruption events observed.>
```
