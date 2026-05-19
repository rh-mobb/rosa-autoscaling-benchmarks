---
name: benchmark-planned-surge
description: >-
  Benchmark a planned traffic surge using proactive autoscaling strategies on
  ROSA. Demonstrates two approaches — balloon pods (low-priority pause pods
  that are preempted instantly) and proactive node pre-warming — and measures
  how quickly the cluster absorbs a 3–6× traffic spike from the moment HPA
  detects it. Use when the user wants to show that good autoscaling design
  (pre-reserved capacity) makes even CAS acceptable for planned events, or
  to demonstrate time-based proactive scaling ahead of a known peak.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**Cursor Canvas** — see Canvas section below). Do not end after the script invocation. If blocked or partial, still deliver the Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Planned Surge — Proactive Strategies (Test 11)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, tmux MCP tools, local `tmux`, and cluster auth; include `rosa` where pool checks are needed).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Simulates the retail "planned sale" scenario: traffic is coming and you prepare
the cluster ahead of time. Two preparation strategies are measured back-to-back
to show that good design makes CAS and Karpenter both adequate for known surges.

## Strategies

### `balloon-pods` (default)
Pre-deploy low-priority pause pods (`surge-overprovisioner`) that hold warm
capacity. When HPA fires at the surge moment, cpu-burner pods immediately
preempt the balloon pods — no CAS/Karpenter wait for the first wave.

```
t_surge (HPA applied)
  ↓ ~15–30 s  metrics-server detection window
  ↓ <1 s      balloon pods evicted (preemption)
  ↓ <5 s      cpu-burner pods scheduled and Ready
  ↓ async     CAS/Karpenter restores balloon pod headroom
```

### `proactive-nodes`
Force N extra nodes to provision before the surge using a placeholder
trigger workload. Nodes are kept warm by the trigger. When HPA fires, the
surge pods land on the pre-provisioned nodes with no provisioning delay.

```
t_prep: apply trigger → CAS/Karpenter provisions N nodes (~8–12 min CAS, ~2–3 min Karpenter)
  ↓
t_surge (HPA applied)
  ↓ ~15–30 s  metrics-server window
  ↓ ~5–10 s   pods scheduled on pre-warmed nodes (near-instant)
```

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 11-planned-surge
```

## Tmux context

When running as part of `benchmark-run-all`, execute in the **`11-planned-surge` window** of the `benchmark-<classic|hcp>` session. `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set from session creation.

## Prerequisites

- Cluster running (only the default `worker` pool is required — this test creates its own `bench-standard` pool; Karpenter NodePool for hcp-autonode is managed by the autonode skill)
- `oc` logged in; `KUBECONFIG` set
- `manifests/overprovisioning/priority-class.yaml` present (applied automatically)

## Resolve RUN_ID

```bash
RUN_ID=$(python3 -c "
import json
d = json.load(open('tmp/cluster.${CLUSTER_TYPE}.json'))
print(d['run_id'])
")
```

If the state file is absent, check `python3 scripts/record-event.py ls`.

## Pre-flight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami
```

Create the `bench-standard` pool for this test. Balloon pods, `cpu-burner`, and
the trigger workload all target `nodeSelector: pool-type: standard`:

```bash
make add-pool TYPE=standard CLUSTER="$CLUSTER_NAME"
```

## Run — balloon-pods strategy (default)

```bash
python3 scripts/run-test-11-planned-surge.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --strategy balloon-pods \
  --balloon-replicas 5 \
  --timeout 2400
```

`--balloon-replicas` should equal `expected_surge_replicas - 1`. Default 5 is
sized for a surge from 1 → 6 cpu-burner replicas on a 2-node m5.xlarge cluster.

## Run — proactive-nodes strategy

```bash
python3 scripts/run-test-11-planned-surge.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --strategy proactive-nodes \
  --prewarm-nodes 2 \
  --timeout 2400
```

For `hcp-autonode`, add `--nodepool-name autonode-bench`.

## What the script does

**balloon-pods:**
1. Applies `priority-class.yaml` + `surge-overprovisioner{,-karpenter}.yaml`
2. Scales balloon pods to `--balloon-replicas`; waits for Running
3. Deploys `cpu-burner` at 1 replica (no HPA yet)
4. `t_surge` = applies `hpa.yaml` → HPA begins monitoring
5. Polls HPA until `desiredReplicas > 1` (metrics-server window)
6. Watches for `Preempted`/`Evicted` events on balloon pods
7. Tracks readiness curve: first pod Ready, 50% Ready, all Ready
8. Cleanup: cpu-burner → 1, HPA deleted, balloon pods → 0

**proactive-nodes:**
1. Applies trigger (30 replicas) to force N new nodes; waits for nodes Ready
2. Deploys `cpu-burner` at 1 replica alongside trigger
3. `t_surge` = applies HPA
4. Polls HPA until desiredReplicas > 1
5. Scales trigger to 0 once cpu-burner pods are Running (nodes stay for scale-down delay)
6. Tracks readiness curve
7. Cleanup

Expected runtime: **balloon-pods** ~15–25 min total; **proactive-nodes** ~25–40 min.

## Key milestones

| Milestone | Description |
|-----------|-------------|
| `preparation_to_ready` | Cost of pre-deploying balloon pods or pre-warming nodes |
| `surge_trigger_to_hpa_decision` | Metrics-server detection window (~15–30 s) |
| `surge_trigger_to_preemption` | Balloon pods evicted (balloon-pods only) |
| `surge_trigger_to_first_pod_ready` | **First user served — key KPI** |
| `surge_trigger_to_50pct_ready` | Half capacity restored |
| `surge_trigger_to_all_ready` | Full surge absorbed |

## Recovery

Re-run the same command. The script is idempotent (`oc apply`, scale operations).

Common failure modes:
- **Balloon pods not Running**: machine pool max may be too low. Check `oc get machines -n openshift-machine-api`.
- **HPA never fires**: metrics-server may be unavailable. Check `oc get pods -n openshift-monitoring`.
- **Proactive-nodes: nodes not provisioning**: verify trigger manifest nodeAffinity matches the pool label.

## Cleanup

After the Canvas is delivered, delete the `bench-standard` pool:

```bash
make remove-pool NAME=bench-standard CLUSTER="$CLUSTER_NAME"
```

## Report (Cursor Canvas)

Present a Canvas with:

**Strategy comparison table:**

| Metric | balloon-pods | proactive-nodes |
|--------|-------------|-----------------|
| Preparation cost | `preparation_to_ready` | `preparation_to_ready` |
| HPA decision (metrics window) | `surge_trigger_to_hpa_decision` | `surge_trigger_to_hpa_decision` |
| First pod Ready | `surge_trigger_to_first_pod_ready` | `surge_trigger_to_first_pod_ready` |
| All pods Ready | `surge_trigger_to_all_ready` | `surge_trigger_to_all_ready` |

**Narrative sections:**
- How the preparation paid off (first pod Ready in seconds, not minutes)
- T+60s / T+120s / T+180s snapshots showing the readiness ramp
- Comparison to test 09 (overprovisioning) if data available: T11 is the "surge scale" equivalent
- When to choose balloon-pods vs proactive-nodes:
  - balloon-pods: lower ongoing cost, works for both CAS and Karpenter, headroom ≤ 1–2 node equivalents
  - proactive-nodes: better for surges larger than what balloon pods can absorb, requires tight timing
- Sizing guidance: balloon replicas = expected HPA target − current replicas
- Key message: **with good design, even CAS responds to planned surges in seconds**
