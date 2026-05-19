---
name: benchmark-parallel-nodes
description: >-
  Benchmark parallel node provisioning speed and stagger on ROSA. Forces
  multiple new nodes to provision simultaneously by applying a trigger workload
  that overflows current cluster capacity, then tracks each node's individual
  arrival time to measure whether CAS/Karpenter provisions them in parallel or
  serially, and quantifies the stagger between the first and last node Ready.
  Use when the user wants to understand multi-node provisioning behaviour,
  compare CAS vs Karpenter parallelism, or demonstrate that Karpenter provisions
  N nodes faster than CAS because it bypasses AWS Auto Scaling Group delays.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**Cursor Canvas** — see Canvas section below). Do not end after the script invocation. If blocked or partial, still deliver the Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Parallel Node Provisioning (Test 13)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, tmux MCP tools, local `tmux`, and cluster auth; include `rosa` where pool checks are needed).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Measures how quickly CAS and Karpenter provision multiple nodes simultaneously
when a large workload arrives. Tracks each node's individual Ready timestamp
to compute provisioning stagger (time between first and last node Ready) and
total provisioning time.

## What this shows

- **CAS** provisions nodes via AWS Auto Scaling Groups, which can batch multiple
  launch requests but applies them in waves — stagger is typically 30–90 s between nodes.
- **Karpenter** creates EC2 instances directly via Fleet API, often launching
  multiple nodes in a single API call — stagger is typically < 30 s.

The shorter the stagger, the more evenly load is distributed across new nodes
as they become schedulable.

## Procedure

```
Baseline: record current Ready node names
  ↓
Apply trigger workload (configurable replicas → forces N new nodes)
  ↓
t_trigger = workload applied
  ↓
watch_node_arrivals() polls every 15 s for new Ready nodes
  Each arrival → milestone trigger_to_node_N_ready
  ↓
After all N expected nodes arrive:
  stagger = last_node_arrival - first_node_arrival
  total   = last_node_arrival - t_trigger
  ↓
Cleanup: scale trigger to 0
```

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 13-parallel-nodes
```

## Tmux context

When running as part of `benchmark-run-all`, execute in the **`13-parallel-nodes` window** of the `benchmark-<classic|hcp>` session.

## Prerequisites

- Cluster running (only the default `worker` pool is required — this test creates its own `bench-standard` pool)
- `oc` logged in; `KUBECONFIG` set

## Resolve RUN_ID

```bash
RUN_ID=$(python3 -c "
import json
d = json.load(open('tmp/cluster.${CLUSTER_TYPE}.json'))
print(d['run_id'])
")
```

## Pre-flight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami
oc get nodes --no-headers | wc -l   # note baseline node count
```

Create the `bench-standard` pool for this test. `cas-trigger.yaml` targets
`nodeSelector: pool-type: standard` so trigger pods land exclusively on this
pool, guaranteeing CAS must provision the expected nodes here:

```bash
make add-pool TYPE=standard CLUSTER="$CLUSTER_NAME"
```

Ensure `max-replicas` in `classic.env` (`AUTOSCALE_MAX_REPLICAS`) is ≥ initial
pool size + `--expected-nodes` before running.

## Run

```bash
python3 scripts/run-test-13-parallel-nodes.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --expected-nodes 3 \
  --timeout 2400
```

- `--expected-nodes`: number of new nodes to wait for (default: 3). Must be ≤ machine pool `max-replicas − current`.
- For `hcp-autonode`: add `--nodepool-name autonode-bench`.

## What the script does

1. Records baseline Ready node names
2. Applies `cas-trigger.yaml` / `karpenter-trigger.yaml` (trigger workload)
3. Scales trigger to enough replicas to require `--expected-nodes` new nodes
4. `t_trigger` = timestamp at trigger application
5. Calls `watch_node_arrivals()` — polls every 15 s for new Ready nodes, fires `on_arrival` callback per node
6. Each arrival records `trigger_to_node_N_ready` milestone with node name and index
7. After all nodes arrive, computes:
   - `provisioning_stagger_ms` = last arrival − first arrival
   - `trigger_to_all_nodes_ready` = last arrival − t_trigger
8. Cleanup: scale trigger to 0

Expected runtime: **15–30 min** (CAS); **5–10 min** (Karpenter).

## Key milestones

| Milestone | Description |
|-----------|-------------|
| `trigger_to_node_1_ready` | First new node Ready |
| `trigger_to_node_2_ready` | Second new node Ready |
| `trigger_to_node_N_ready` | Nth new node Ready |
| `trigger_to_all_nodes_ready` | All expected nodes Ready |
| `provisioning_stagger_ms` (in `result.extra`) | Time between first and last node |

## Recovery

Re-run the same command. `watch_node_arrivals` resets the baseline on each run.

Common failure modes:
- **Fewer nodes than expected**: machine pool `max-replicas` may be too low. Check `rosa list machinepools --cluster "$CLUSTER_NAME"`.
- **Trigger pods not Pending**: existing cluster has spare capacity — increase trigger replicas or check capacity-filler status.

## Cleanup

After the Canvas is delivered, delete the `bench-standard` pool:

```bash
make remove-pool NAME=bench-standard CLUSTER="$CLUSTER_NAME"
```

## Report (Cursor Canvas)

Present a Canvas with:

**Node arrival timeline** — a timeline chart showing each node's arrival relative to `t_trigger`:

```
t+0:00  trigger applied
t+X:XX  node-1 Ready  ──────────┐ first arrival
t+X:XX  node-2 Ready            │ stagger
t+X:XX  node-3 Ready  ──────────┘ last arrival
         ↑─────────────────────┘
         total provisioning time
```

**Summary table:**

| Metric | Classic (CAS) | HCP AutoNode (Karpenter) |
|--------|---------------|--------------------------|
| First node Ready | `trigger_to_node_1_ready` | `trigger_to_node_1_ready` |
| All nodes Ready | `trigger_to_all_nodes_ready` | `trigger_to_all_nodes_ready` |
| Provisioning stagger | `provisioning_stagger_ms` | `provisioning_stagger_ms` |

**Narrative sections:**
- Why stagger matters: pods land on nodes as they arrive, so shorter stagger = more balanced load sooner
- CAS behaviour: ASG launches in batches, nodes arrive in waves
- Karpenter behaviour: Fleet API batch launch, nodes arrive nearly simultaneously
- Implications for surge sizing: if CAS stagger is 60 s, pods may pile up on node-1 before node-2 arrives
- Recommendation: pair CAS with balloon pods (T09/T11) to avoid the stagger window being user-visible
