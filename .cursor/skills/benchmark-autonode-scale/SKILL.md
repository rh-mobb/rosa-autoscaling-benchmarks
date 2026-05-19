---
name: benchmark-autonode-scale
description: >-
  Benchmark Karpenter (AutoNode) node provisioning speed and consolidation on a
  ROSA HCP cluster with AutoNode enabled. Measures the full chain — pod Pending
  → NodeClaim created → node Ready → pod Running — across three progressive load
  waves, then measures Karpenter consolidation after load is removed. Compares
  results against the CAS baseline from tests 03/04/08 when available in the
  same run. Use when the user wants to validate whether Karpenter provisions
  nodes faster than Cluster Autoscaler and whether balloon pods are still needed.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** — a **Cursor Canvas** with the Karpenter vs CAS comparison table, NodeClaim timeline, and balloon-pod recommendation. Do not end after the script invocation. If blocked or partial, still deliver the Canvas with a failure narrative. See `.cursor/rules/local/rosa-benchmark-invocation.mdc`.

# Benchmark: AutoNode (Karpenter) Scale-Up and Consolidation (Test 10)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa` when needed for cross-checks, tmux MCP tools, local `tmux`, and cluster auth).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Validates the key hypothesis from the AutoNode test plan
(`references/autonode/2026-04-07-autonode-karpenter-scaling-test.md`):
**does Karpenter provision nodes significantly faster than the 7–10 minute CAS
baseline, and does that speed eliminate the need for balloon pods?**

## Prerequisites

- ROSA HCP cluster provisioned with AutoNode enabled — use `benchmark-create-hcp-autonode`
- `ec2nodeclass/default` status `READY=True` (`oc get ec2nodeclass`)
- `oc` logged in; `KUBECONFIG` set to the cluster's kubeconfig
- No existing `autonode-test` namespace or `autonode-bench` NodePool on the cluster
  (script is idempotent via `apply` but avoids state surprises)

## Inputs

Ask the user (or infer from context):

- `CLUSTER_NAME`: AutoNode cluster name (e.g. from `autonode.env` or `oc whoami --show-server`)
- `RUN_ID`: existing run ID from `benchmark-create-hcp-autonode` (blank = start fresh)
  Using the same RUN_ID loads the CAS baseline from tests 03/04/08 for comparison.

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 10-autonode-scale
```

## Tmux context

Run this test in the **`10-autonode-scale` window** of the `benchmark-hcp-autonode` session
(socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set from
session creation. Use `create-window` → `execute-command` → `get-command-result` per the
harness in `benchmark-run-all`.

## Resolve RUN_ID

```bash
# From the autonode cluster state file:
RUN_ID=$(python3 -c "
import json
d = json.load(open('tmp/cluster.hcp-autonode.json'))
print(d['run_id'])
")
```

If the state file is absent, check `python3 scripts/record-event.py ls` or supply
`--run-id` explicitly.

## Pre-flight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami           # must succeed
oc get ec2nodeclass # must show default READY=True
```

## Run

```bash
python3 scripts/run-test-10-autonode-scale.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type hcp-autonode \
  --run-id "$RUN_ID"
```

Optional flags:

| Flag | Default | Purpose |
|------|---------|---------|
| `--nodepool-name` | `autonode-bench` | Override NodePool name if it already exists |
| `--timeout` | `3600` | Global timeout in seconds |
| `--dry-run` | off | Print actions without executing oc commands |

## What the script measures

### Phase 1 — Initial provision

The first time app pods land on an empty NodePool.  This is the cleanest
Karpenter cold-start measurement.

| Milestone | Description |
|-----------|-------------|
| `initial.pending_to_nodeclaim` | Pod goes Pending → Karpenter creates NodeClaim |
| `initial.nodeclaim_to_node_ready` | NodeClaim created → EC2 node is Ready |
| `initial.node_ready_to_pods_running` | Node Ready → app pods Running |
| `initial.pending_to_pods_running` | **Total: pod Pending → Running** |

### Phase 2 — Progressive load waves

Three waves of load-generator replicas (5 → 15 → 30) drive HPA and potentially
trigger additional node provisioning.

For each wave (`wave_light`, `wave_medium`, `wave_heavy`):

| Milestone | Description |
|-----------|-------------|
| `<wave>.load_to_nodeclaim` | Load applied → new NodeClaim created (if capacity needed) |
| `<wave>.nodeclaim_to_node_ready` | NodeClaim → new node Ready |
| `<wave>.node_ready_to_pods_running` | Node Ready → all app pods Running |
| `<wave>.load_to_pods_running` | **Total: load applied → all pods Running** |

If HPA growth fits on existing nodes, only `load_to_pods_running` is recorded
with `new_nodes_provisioned=no`.

### Phase 3 — Karpenter consolidation

Measures how fast Karpenter removes idle nodes after load is removed.
Karpenter uses `WhenEmptyOrUnderutilized` consolidation with `consolidateAfter: 30s`
(set in `manifests/autonode/nodepool.yaml`) — much faster than CAS's 10-minute
`scale-down-unneeded-time`.

| Milestone | Description |
|-----------|-------------|
| `scaledown.load_stop_to_hpa_min` | Load removed → HPA at minReplicas (2) |
| `scaledown.load_stop_to_first_consolidation` | Load removed → first NodeClaim deleted |
| `scaledown.load_stop_to_stable` | Load removed → NodeClaims back to baseline |

## Recovery

```bash
# Idempotent re-run (applies manifests again, re-polls):
python3 scripts/run-test-10-autonode-scale.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type hcp-autonode \
  --run-id "$RUN_ID"
```

Common failure modes:

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ec2nodeclass/default` not Ready | SubnetsReady=False or SecurityGroupsReady=False | Re-run `benchmark-create-hcp-autonode` Step 6 tagging troubleshooting |
| No NodeClaim appears after pod Pending | App pods scheduled on default workers (nodeSelector not applied) | Verify `oc get pods -n autonode-test -o wide` — column NODE should show a `karpenter.sh/nodepool=autonode-bench` node |
| NodePool not Ready | Wrong shard or CRDs not installed | `rosa describe cluster -c $CLUSTER_NAME -o json \| jq .properties.provision_shard_id` must be `9f11dd2b-98c1-11f0-8fe5-0a580a830a08` |
| HPA never fires | Python app not hitting CPU threshold | Confirm load-generator pods are Running and targeting the correct service |

## Report (Cursor Canvas)

Read the Canvas skill (`skills-cursor/canvas/SKILL.md`) for full canvas instructions.

The canvas must include the following sections:

### 1 — Key Stats row

Show the headline numbers from Phase 1 (initial provision) and Phase 3 (consolidation):

| Metric | Karpenter (AutoNode) | CAS baseline | Δ |
|--------|---------------------|-------------|---|
| Node provisioning (cold start) | `initial.pending_to_pods_running` | `03.workload_applied_to_pods_running` | ±Xm |
| Node provisioning (HPA-triggered) | `wave_heavy.load_to_pods_running` | `08.hpa_trigger_to_all_running` | ±Xm |
| Scale-down to stable | `scaledown.load_stop_to_stable` | `04.workload_removed_to_stable` | ±Xm |

If CAS baseline milestones are absent (different run or tests 03/04/08 not run),
note "CAS baseline not available for this run" and skip the Δ column.

### 2 — NodeClaim timeline (Phase 1)

Table showing each Phase 1 milestone with wall-clock time and elapsed duration.

### 3 — Load wave results (Phase 2)

One section per wave.  For waves where Karpenter provisioned new nodes: show the
NodeClaim → node Ready → pods Running chain.  For waves that fit existing capacity:
note the elapsed time and that no new provisioning was needed.

### 4 — Consolidation timeline (Phase 3)

Table of Phase 3 milestones.  Highlight that Karpenter's `consolidateAfter: 30s`
policy means consolidation starts much faster than CAS's 10-minute minimum.

### 5 — Balloon pod recommendation

Based on the `initial.pending_to_pods_running` elapsed time, include a recommendation:

| Karpenter provision time | Recommendation |
|--------------------------|---------------|
| < 2 min | Balloon pods likely **unnecessary** — Karpenter is fast enough for most burst scenarios |
| 2–4 min | Balloon pods provide **marginal benefit** — consider 1–2 pause pods only for latency-critical bursts |
| 4–7 min | Balloon pods are **still valuable** — consider a smaller headroom than with CAS |
| ≥ 7 min | **Similar to CAS** — balloon pods remain essential |

### 6 — Raw JSON (collapsed)

Include a collapsible section with the full JSON output from the script for audit purposes.

After writing the canvas:

```bash
python3 scripts/checkpoint.py complete --run-id "$RUN_ID" --test 10-autonode-scale
```

## Timing reference (expected ranges)

| Phase | Expected |
|-------|----------|
| Initial provision (pod Pending → Running) | **2–5 min** (Karpenter target) vs 7–10 min CAS |
| Wave light → pods Running | 2–5 min if new node needed, <1 min if existing capacity |
| Wave medium → pods Running | 2–5 min |
| Wave heavy → pods Running | 2–5 min (possibly multiple NodeClaims in parallel) |
| HPA scale-down stabilisation | ~5 min (HPA stabilizationWindowSeconds=300) |
| Karpenter consolidation (first removal) | **<2 min** (consolidateAfter=30s) vs ~23 min CAS |
| Full stable | **5–10 min** vs ~30 min CAS |

## Cleanup (if running standalone)

If not running as part of `benchmark-run-all`, the script deletes the `autonode-test`
namespace and the `autonode-bench` NodePool on completion.  Karpenter drains and
terminates the EC2 instances automatically when the NodePool is deleted.

To clean up manually if the script was interrupted:

```bash
oc delete namespace autonode-test --ignore-not-found
oc delete nodepool autonode-bench --ignore-not-found
# Confirm all NodeClaims are gone before deleting the cluster:
oc get nodeclaim
```
