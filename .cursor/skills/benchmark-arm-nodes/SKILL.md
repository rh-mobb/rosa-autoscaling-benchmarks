---
name: benchmark-arm-nodes
description: >-
  Benchmark ARM64 (AWS Graviton) node provisioning on ROSA Classic, HCP, and
  HCP AutoNode (test 16). Measures the end-to-end provisioning chain from
  workload deployment to pods Running on Graviton instances, then compares
  against the equivalent x86_64 on-demand run (test 03 for Classic/HCP, test
  10 for AutoNode). On HCP AutoNode the ec2nodeclass/default already carries
  the RHCOS aarch64 AMI alongside x86_64 — no custom NodeClass is needed.
  Delivers a Cursor Canvas with an ARM vs x86 comparison table and
  provisioning timeline. Use when the user wants to validate ARM64 support,
  measure Graviton provisioning latency, or compare ARM vs x86 boot time.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**Cursor Canvas** with ARM vs x86 comparison). Do not end after `make run-test-16` alone. If blocked or partial, still deliver the Canvas with a failed/partial narrative.

# Benchmark: ARM64 (Graviton) Node Provisioning (Test 16)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa` for Classic/HCP pool operations, tmux MCP tools, local `tmux`, and cluster auth).
Require Python 3.11+ for harness scripts (`record-event.py` uses `datetime.UTC`).

Prefer the repo virtual environment before running the test:

```bash
source .venv/bin/activate
python3 -V   # expect 3.11+
```

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Measure end-to-end latency for autoscaling onto EC2 ARM64 (Graviton) instances.

## Supported cluster types

| Cluster type | Support |
|---|---|
| `classic` | **Run** — ROSA CAS with `m6g.xlarge` machine pool |
| `hcp` | **Run** — ROSA HCP CAS with `m6g.xlarge` machine pool |
| `hcp-autonode` | **Run** — Karpenter NodePool with `kubernetes.io/arch: arm64`, m6g.xlarge / c6g.xlarge |

## Key insight: AutoNode already has the ARM64 AMI

On HCP AutoNode, the `ec2nodeclass/default` carries **both** RHCOS AMIs in
`status.amis` — Karpenter selects the correct one automatically based on the
`kubernetes.io/arch` requirement in the NodePool:

```
ami-0f684b45a6e89dce2  rhcos-9.6.20260112-0-aarch64  [kubernetes.io/arch=arm64]
ami-0e0850e74100f0f31  rhcos-9.6.20260112-0-x86_64   [kubernetes.io/arch=amd64]
```

No custom `EC2NodeClass` or `OpenshiftEC2NodeClass` is required.

## What is measured

```
workload applied
  ↓ workload_applied_to_failed_scheduling
FailedScheduling event
  ↓ failed_scheduling_to_scheduler_triggered
CAS TriggeredScaleUp  OR  Karpenter NodeClaim created
  ↓ scheduler_triggered_to_node_ready
First ARM64 node Ready
  ↓ node_ready_to_pods_running
Pods Running
════════════════════════════════════════════════
workload_applied_to_pods_running  (total headline metric)
```

**Classic/HCP-only milestone:**
- `pool_submitted_to_first_node_ready` — from `rosa create machinepool` to first Ready node

**AutoNode-only milestones:**
- `failed_scheduling_to_nodeclaim` — Karpenter's provisioning decision latency
- `nodeclaim_to_node_ready` — EC2 ARM64 launch → node Ready

**Comparison output (`x86_baseline_ms` in JSON result):**
When `--run-id` is provided, the script loads x86_64 on-demand milestones from
`events.jsonl` (test 03 for Classic/HCP, test 10 for AutoNode) and surfaces
them alongside ARM timing in the Canvas.

## Mandatory close-out (agents)

1. **Preflight:** Verify `oc whoami` succeeds and `KUBECONFIG` is set.
   For `hcp-autonode`: confirm `ec2nodeclass/default` is Ready AND has an
   arm64 AMI in `status.amis`.
2. **Execution:** Run `make run-test-16` to completion.
   The test creates and deletes its own resources; it is safe to re-run.
3. **Canvas:** After the test, render a Canvas with an ARM vs x86 comparison
   table, provisioning timeline, and findings (see **Step 4** below).
4. **Checkpoint/events:** Update `checkpoint.py` and `record-event.py` per
   **Checkpoint & Resume** below when a `RUN_ID` is in play.

## Checkpoint & Resume

```bash
python3 scripts/record-event.py ls
STATUS=$(python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 16-arm-nodes)
# If "completed", load results from events.jsonl and skip to Canvas rendering
```

Mark progress:
```bash
python3 scripts/checkpoint.py start    --run-id "$RUN_ID" --test 16-arm-nodes
# ... run the test ...
python3 scripts/checkpoint.py complete --run-id "$RUN_ID" --test 16-arm-nodes
# On failure:
python3 scripts/checkpoint.py fail     --run-id "$RUN_ID" --test 16-arm-nodes --reason "m6g.xlarge unavailable in AZ"
```

## Preflight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.<CLUSTER_NAME>.yaml"
oc whoami   # must succeed before running the test

# hcp-autonode only — verify AutoNode and arm64 AMI are ready
oc get ec2nodeclass default -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# expected: True

oc get ec2nodeclass default -o json | python3 -c "
import sys,json; d=json.load(sys.stdin)
arm=[a for a in d['status']['amis'] if any(r.get('values',[])==['arm64'] for r in a.get('requirements',[]))]
print('arm64 AMIs:', arm)
"
# expected: list with at least one entry
```

## Step 1 — Run the test

```bash
make run-test-16 CLUSTER=<name> TYPE=<classic|hcp|hcp-autonode> \
  [RUN_ID=<run-id>]
```

Alternative direct invocation:
```bash
python3 scripts/run-test-16-arm-nodes.py \
    --cluster-name <name> \
    --cluster-type <classic|hcp|hcp-autonode> \
    [--run-id <RUN_ID>] \
    [--nodepool-name autonode-arm64]     # hcp-autonode only
    [--timeout 1800]
```

**Expected run times:**
- Classic/HCP: 8–20 min (same three-phase boot as x86; m6g.xlarge is broadly
  available in us-east-1 but may be less common in smaller AZs)
- AutoNode: 4–8 min (Karpenter EC2 Fleet API, arm64 path identical to x86)

## Step 2 — What to observe during the run

| Phase | What to watch |
|---|---|
| Classic pool creation | `rosa describe machinepool -c <name> --machinepool bench-arm64` |
| FailedScheduling | `oc get events -n arm64-test --sort-by=.lastTimestamp` |
| CAS trigger (Classic/HCP) | `oc get events -n openshift-machine-api --sort-by=.lastTimestamp` |
| NodeClaim (AutoNode) | `oc get nodeclaims -l karpenter.sh/nodepool=autonode-arm64` |
| Node arch label | `oc get node <name> -o jsonpath='{.metadata.labels.kubernetes\.io/arch}'` |
| Instance type | `oc get node <name> -o jsonpath='{.metadata.labels.node\.kubernetes\.io/instance-type}'` |

## Step 3 — Key result fields

```json
{
  "milestones": {
    "workload_applied_to_failed_scheduling": { "elapsed_ms": ... },
    "failed_scheduling_to_scheduler_triggered": { "elapsed_ms": ... },
    "scheduler_triggered_to_node_ready": { "elapsed_ms": ... },
    "node_ready_to_pods_running": { "elapsed_ms": ... },
    "workload_applied_to_pods_running": { "elapsed_ms": ... },
    // Classic/HCP only:
    "pool_submitted_to_first_node_ready": { "elapsed_ms": ... },
    // AutoNode only:
    "failed_scheduling_to_nodeclaim": { "elapsed_ms": ... },
    "nodeclaim_to_node_ready": { "elapsed_ms": ... }
  },
  "extra": {
    "arch": "arm64",
    "instance_type": "m6g.xlarge",
    "scheduler": "cas | autonode",
    "nodeclaim_arch": "arm64",          // AutoNode: label from NodeClaim
    "nodeclaim_instance_type": "m6g.xlarge",
    "first_arm_node": "<node-name>",
    "x86_baseline_ms": {
      "03-autoscale-up.workload_applied_to_pods_running": ...,  // Classic/HCP
      "10-autonode-scale.initial.pending_to_pods_running": ...  // AutoNode
    }
  }
}
```

## Step 4 — Render Canvas

Create a Canvas with:

1. **Headline metrics** — `workload_applied_to_pods_running` for ARM64 and x86_64
   side-by-side. Highlight the delta (expected: near-zero — boot chain is identical).

2. **Provisioning timeline** — a step-by-step breakdown table:

   | Phase | ARM64 | x86_64 baseline | Δ |
   |---|---|---|---|
   | Workload → FailedScheduling | ... | ... | ... |
   | FailedScheduling → Scheduler decision | ... | ... | ... |
   | Scheduler decision → Node Ready | ... | ... | ... |
   | Node Ready → Pods Running | ... | ... | ... |
   | **Total** | **...** | **...** | **...** |

3. **ARM-specific observations** (AutoNode):
   - Confirmed `kubernetes.io/arch=arm64` label on NodeClaim and node
   - Instance type selected by Karpenter (m6g.xlarge or c6g.xlarge fallback)
   - ARM64 AMI ID (`ami-0f684b45a6e89dce2` = `rhcos-9.6.20260112-0-aarch64`)

4. **Narrative** — 3–5 sentences explaining:
   - Whether ARM was meaningfully slower or faster than x86 in this run
   - The cost trade-off (Graviton instances typically 10–20% cheaper than
     equivalent x86 for the same performance class)
   - That `registry.k8s.io/pause:3.9` is multi-arch — no special image handling
     was required for this benchmark workload
   - For AutoNode: that switching between x86 and arm64 is a single NodePool
     field change; no custom NodeClass is needed

## Classic / HCP: ARM machine pool details

The test creates a machine pool named `bench-arm64` with:
```
--instance-type m6g.xlarge
--enable-autoscaling
--min-replicas 0
--max-replicas 6
--labels benchmark=true,pool-type=arm64
```
(`max-replicas` is **6** so multi-AZ clusters satisfy ROSA’s “multiple of 3” requirement.)

The pool starts at `min=0` so the benchmark captures the complete cold-start
provisioning chain. The `bench-arm64` pool is deleted at the end of the test.

## AutoNode: ARM64 NodePool details

The test applies `manifests/autonode/nodepool-arm64.yaml` which configures:
```yaml
requirements:
  - key: node.kubernetes.io/instance-type
    operator: In
    values: [m6g.xlarge, c6g.xlarge]   # Karpenter picks the cheapest available
  - key: kubernetes.io/arch
    operator: In
    values: [arm64]
  - key: karpenter.sh/capacity-type
    operator: In
    values: [on-demand]
```

Two instance types allow Karpenter to fall back to `c6g.xlarge` if `m6g.xlarge`
is unavailable in the target AZ, following Graviton best-practice for resilience.

## Cleanup

The test script deletes its own resources on completion and on SIGINT:
- `arm64-test` namespace (all cluster types)
- `bench-arm64` machine pool (Classic/HCP)
- `autonode-arm64` NodePool (AutoNode)

If the test exits mid-run without cleanup, run:
```bash
# Classic / HCP
oc delete namespace arm64-test --ignore-not-found
rosa delete machinepool -c <name> --machinepool bench-arm64 --yes

# AutoNode
oc delete namespace arm64-test --ignore-not-found
oc delete nodepool autonode-arm64 --ignore-not-found
```
