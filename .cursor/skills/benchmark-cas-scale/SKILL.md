---
name: benchmark-cas-scale
description: >-
  Benchmark CAS progressive node provisioning speed and scale-down on a ROSA
  Classic or HCP cluster. Measures the full chain — workload applied →
  FailedScheduling → CAS TriggeredScaleUp → node Ready → pod Running — across
  three progressive load waves, then measures CAS scale-down after load is
  removed. Designed as the CAS counterpart of test 10 (Karpenter/AutoNode):
  same wave sizing, same milestone naming conventions, same JSON output schema,
  enabling direct side-by-side comparison. Use when the user wants to measure
  CAS provisioning speed with the same methodology as test 10, or to produce a
  Karpenter vs CAS comparison canvas.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** — a **Cursor Canvas** with the CAS vs Karpenter comparison table, phase timeline, and scale-down analysis. Do not end after the script invocation. If blocked or partial, still deliver the Canvas with a failure narrative. See `.cursor/rules/local/rosa-benchmark-invocation.mdc`.

> **Linked test:** Test 14 and test 10 (`benchmark-autonode-scale`) are coupled. Wave counts, replica sizing, timeout values, and milestone naming conventions MUST stay in sync between `run-test-14-cas-scale.py` and `run-test-10-autonode-scale.py`. See AGENTS.md for the coupling note.

# Benchmark: CAS Progressive Scale-Up and Scale-Down (Test 14)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa`, tmux MCP tools, local `tmux`, and cluster auth).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

CAS counterpart of test 10 (`benchmark-autonode-scale`). Uses the same
three-phase structure and identical wave sizing so timing results are
directly comparable.

## Prerequisites

- ROSA Classic or HCP cluster with machine pool autoscaling enabled
- `pool-type=standard` label on the standard worker nodes (set at machine pool
  creation time via `make add-pool` or `rosa create machinepool --labels`)
- Machine pool `max-replicas` ≥ current workers + 3 (one per wave)
- `oc` logged in; `KUBECONFIG` set to the cluster's kubeconfig
- No existing `cas-scale-test` or `benchmark` namespace on the cluster
- **Standard workers at or near min-replicas before running** — if extra nodes
  from previous tests are still present, Phase 1 may provision fewer nodes than
  needed for Phase 2, and Phase 2 waves will fit on existing capacity without
  triggering new provisioning. If in doubt, clean up other benchmark namespaces
  and wait for CAS to scale down before starting this test.

## Inputs

Ask the user (or infer from context):

- `CLUSTER_NAME`: cluster name (e.g. from `classic.env` or `oc whoami --show-server`)
- `RUN_ID`: existing run ID from `benchmark-cluster-install` (blank = start fresh)
  Using the same RUN_ID loads the Karpenter baseline from test 10 when available.
- `CLUSTER_TYPE`: `classic` or `hcp`

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 14-cas-scale
```

## Tmux context

Run this test in the **`14-cas-scale` window** of the benchmark session
(socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are
already set from session creation. Use `create-window` → `execute-command`
→ `get-command-result` per the harness in `benchmark-run-all`.

## Resolve RUN_ID

```bash
RUN_ID=$(python3 -c "
import json
d = json.load(open('tmp/cluster.${CLUSTER_TYPE}.json'))
print(d['run_id'])
")
```

If the state file is absent, check `python3 scripts/record-event.py ls` or
supply `--run-id` explicitly.

## Pre-flight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami           # must succeed
rosa list machinepools -c "$CLUSTER_NAME"  # confirm autoscaling=true and max-replicas headroom
```

## Run

```bash
python3 scripts/run-test-14-cas-scale.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "${CLUSTER_TYPE:-classic}" \
  --run-id "$RUN_ID"
```

Optional flags:

| Flag | Default | Purpose |
|------|---------|---------|
| `--timeout` | `5400` | Global per-phase timeout in seconds |
| `--dry-run` | off | Print actions without executing oc commands |

Note: `--cluster-type hcp-autonode` is rejected — use `run-test-10-autonode-scale.py` for Karpenter.

## What the script measures

### Phase 1 — Initial provision (mirrors test 03 and test 10 Phase 1)

The first time pods force a CAS scale-up using `cas-trigger.yaml`.

| Milestone | Description |
|-----------|-------------|
| `initial.workload_applied_to_failed_scheduling` | Trigger applied → FailedScheduling event |
| `initial.failed_scheduling_to_cas_triggered` | FailedScheduling → CAS TriggeredScaleUp event |
| `initial.cas_triggered_to_node_ready` | CAS decision → EC2 node Ready |
| `initial.node_ready_to_pods_running` | Node Ready → trigger pods Running |
| `initial.pending_to_pods_running` | **Total: workload applied → pods Running** |

### Phase 2 — Progressive load waves

Three waves of direct replica scaling (+2 per wave) each force exactly 1
new CAS node (1000m CPU/pod, 2 pods per m5.xlarge).

For each wave (`wave_1`, `wave_2`, `wave_3`):

| Milestone | Description |
|-----------|-------------|
| `<wave>.scale_to_cas_triggered` | Deployment scaled → CAS TriggeredScaleUp event |
| `<wave>.cas_triggered_to_node_ready` | CAS decision → new node Ready |
| `<wave>.node_ready_to_pods_running` | Node Ready → all app pods Running |
| `<wave>.scale_to_pods_running` | **Total: deployment scaled → all pods Running** |

### Phase 3 — CAS scale-down

Measures how long CAS takes to remove idle nodes after load is removed.
CAS is gated by `scale-down-unneeded-time` (~10 min) and
`scale-down-delay-after-add` (~10 min) — expect **15–30 min per node** vs
Karpenter's `consolidateAfter: 30s`.

| Milestone | Description |
|-----------|-------------|
| `<step>.scale_to_cordon` | App scaled down → CAS cordons a node (earliest signal) |
| `<step>.scale_to_node_removed` | App scaled down → node no longer in `oc get nodes` |
| `<step>.scale_to_pods_stable` | App scaled down → all remaining pods Running |

## Recovery

Common failure modes:

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| FailedScheduling never fires | Trigger pods scheduled on non-standard nodes | Verify `pool-type=standard` label on worker nodes; check `oc get nodes -L pool-type` |
| No CAS TriggeredScaleUp event | Machine pool autoscaling disabled or max-replicas too low | `rosa edit machinepool -c $CLUSTER_NAME --enable-autoscaling --max-replicas <N>` |
| Node never Ready | EC2 quota or IAM issue | Check `oc get machines -n openshift-machine-api` and events |
| Phase 3 never removes node | CAS cooldown still running from earlier scale-up | Wait; CAS scale-down-delay-after-add is 10 min from last scale-up |
| Phase 3 timeout | Scale-down-unneeded-time extends beyond SCALEDOWN_TIMEOUT_S | Increase `--timeout 7200`; or check CAS logs in openshift-machine-api |

## Report (Cursor Canvas)

Read the Canvas skill (`skills-cursor/canvas/SKILL.md`) for full canvas instructions.

The canvas must include the following sections:

### 1 — Key Stats row (CAS vs Karpenter comparison)

Show the headline numbers from Phase 1 and Phase 3 side-by-side with test 10:

| Metric | CAS (Test 14) | Karpenter (Test 10) | Δ |
|--------|--------------|---------------------|---|
| Node provisioning (cold start) | `initial.pending_to_pods_running` | `10-autonode-scale.initial.pending_to_pods_running` | ±Xm |
| Node provisioning (wave 3) | `wave_3.scale_to_pods_running` | `10-autonode-scale.wave_3.scale_to_pods_running` | ±Xm |
| Scale-down per node | `rollback_3.scale_to_node_removed` | `10-autonode-scale.rollback_3.scale_to_node_removed` | ±Xm |

If Karpenter baseline milestones are absent (different run or test 10 not run),
note "Karpenter baseline not available for this run" and skip the Δ column.

### 2 — Phase 1 timeline

Table showing each Phase 1 milestone with wall-clock time and elapsed duration.
Include note on CAS provisioning chain:
`FailedScheduling → TriggeredScaleUp → MachineSet replica increment → Machine object → EC2 RunInstances → three-boot (Ignition → MCD → final boot) → Node Ready`

### 3 — Load wave results (Phase 2)

One section per wave. For each wave: show the CAS trigger → node Ready → pods
Running chain with elapsed times. Note `scale_to_cas_triggered` — this is the
CAS equivalent of Karpenter's `scale_to_nodeclaim` in test 10.

### 4 — Scale-down timeline (Phase 3)

Table of Phase 3 milestones. Highlight the effect of CAS cooldown timers:
- `scale-down-unneeded-time`: 10 min (CAS waits this long before acting on an idle node)
- `scale-down-delay-after-add`: 10 min (CAS waits after any scale-up before scaling down)
- Compare against Karpenter `consolidateAfter: 30s` if test 10 data available

### 5 — Balloon pod recommendation (CAS context)

| CAS provision time | Recommendation |
|-------------------|---------------|
| < 5 min | Balloon pods provide marginal benefit — consider only for p99 burst scenarios |
| 5–8 min | Balloon pods **strongly recommended** — pre-reserve 1–2 nodes worth of headroom |
| ≥ 8 min | Balloon pods **essential** — CAS latency makes cold-start unacceptable for bursty workloads |

### 6 — Raw JSON (collapsed)

Include a collapsible section with the full JSON output from the script for
audit purposes.

After writing the canvas:

```bash
python3 scripts/checkpoint.py complete --run-id "$RUN_ID" --test 14-cas-scale
```

## Timing reference (expected ranges)

| Phase | Expected |
|-------|----------|
| Initial provision (workload applied → pods Running) | **7–12 min** (CAS) vs 2–5 min Karpenter |
| Wave CAS decision (`scale_to_cas_triggered`) | 30–120s after FailedScheduling |
| Wave node Ready | 5–8 min from CAS decision (EC2 RunInstances + three-boot) |
| Wave pods Running | <1 min after node Ready |
| Scale-down cordon (per node) | **10–20 min** after scale-down (cooldown timers) |
| Scale-down node removed (per node) | **15–30 min** from scale command |
| Full stable | **45–90 min** total for all 3 rollback steps |

## Cleanup (if running standalone)

If not running as part of `benchmark-run-all`, the script deletes the
`cas-scale-test` and `benchmark` namespaces on completion.

To clean up manually if the script was interrupted:

```bash
oc delete namespace cas-scale-test benchmark --ignore-not-found
# Confirm all extra nodes are gone before destroying the cluster:
oc get nodes
rosa list machinepools -c $CLUSTER_NAME
```
