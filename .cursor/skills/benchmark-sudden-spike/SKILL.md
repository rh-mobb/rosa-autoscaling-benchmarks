---
name: benchmark-sudden-spike
description: >-
  Benchmark an unplanned sudden traffic spike on ROSA using a two-phase
  same-cluster comparison. Phase 1 shows raw CAS/Karpenter response with no
  preparation (the degradation window). Phase 2 shows how HPA + balloon pods +
  CAS/Karpenter collapses that window. Emits cross-phase improvement deltas.
  Use when the user wants to demonstrate that autoscaling design — not just
  autoscaler choice — determines how quickly a cluster recovers from a sudden
  spike, and that even CAS becomes adequate when balloon pods absorb the
  initial burst.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**Cursor Canvas** — see Canvas section below). Do not end after the script invocation. If blocked or partial, still deliver the Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Sudden Spike — Two-Phase Comparison (Test 12)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, tmux MCP tools, local `tmux`, and cluster auth; include `rosa` where pool checks are needed).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Simulates the retail "influencer spike": an unexpected 10× traffic surge with
no prior warning. Runs two phases back-to-back on the same cluster so the
comparison is apples-to-apples.

## Phase 1 — No preparation (straight CAS/Karpenter)

```
capacity-filler saturates cluster
  ↓
cpu-burner deploys at 1 replica
  ↓
t_surge: HPA applied → metrics-server detects CPU spike
  ↓ ~15–30 s  HPA fires
  ↓ pods Pending → FailedScheduling
  ↓ CAS TriggeredScaleUp OR Karpenter NodeClaim created
  ↓ ~8–12 min (CAS) / ~2–3 min (Karpenter) — new nodes Ready
  ↓ pods schedule → Running → Ready
```
**Degradation window: typically 8–12 min CAS, 3–5 min Karpenter.**

## Phase 2 — Balloon pods + HPA + CAS/Karpenter

```
balloon pods (surge-overprovisioner) hold warm capacity
  ↓
cpu-burner deploys at 1 replica
  ↓
t_surge: HPA applied
  ↓ ~15–30 s  HPA fires
  ↓ <1 s      balloon pods evicted (preemption) — first wave instant
  ↓ <10 s     first cpu-burner pods Ready (served from freed balloon slots)
  ↓ async     CAS/Karpenter restores balloon pod headroom
```
**Degradation window: ~10–30 s to first pod Ready regardless of autoscaler.**

The improvement deltas (`first_pod_improvement_ms`, `full_recovery_improvement_pct`)
are emitted directly into `result.extra` for report generation.

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 12-sudden-spike
```

## Tmux context

When running as part of `benchmark-run-all`, execute in the **`12-sudden-spike` window** of the `benchmark-<classic|hcp>` session.

## Prerequisites

- Cluster running (only the default `worker` pool is required — this test creates its own `bench-standard` pool; Karpenter NodePool for hcp-autonode is managed by the autonode skill)
- `oc` logged in; `KUBECONFIG` set
- `manifests/overprovisioning/priority-class.yaml` present (applied automatically)
- Recommended: run after test 09 (overprovisioning) so the audience already understands the pattern

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
```

Create the `bench-standard` pool for this test. `capacity-filler`, `cpu-burner`,
and balloon pods all target `nodeSelector: pool-type: standard` so both phases
of the spike run in an isolated, measurable node group:

```bash
make add-pool TYPE=standard CLUSTER="$CLUSTER_NAME"
```

## Run

```bash
python3 scripts/run-test-12-sudden-spike.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --target-replicas 10 \
  --balloon-replicas 5 \
  --timeout 3600
```

- `--target-replicas`: how many cpu-burner replicas HPA should drive to (default 10).
- `--balloon-replicas`: balloon pods for Phase 2. Set to `target_replicas - 1` for maximum effect (default 5).
- For `hcp-autonode`: add `--nodepool-name autonode-bench`.

Increase `--timeout` for Classic CAS clusters where Phase 1 node provisioning takes 10–15 min.

## What the script does

**Phase 1 (no prep):**
1. Applies `capacity-filler`; waits Running (saturates cluster)
2. Deploys `cpu-burner` at 1 replica (no HPA)
3. `t_surge` = applies HPA
4. Polls HPA for scale decision; records `phase1.surge_trigger_to_hpa_decision`
5. Watches `FailedScheduling` → CAS/Karpenter chain → first new node Ready
6. Tracks readiness curve under `phase1.*` milestones
7. Between-phase cleanup: cpu-burner → 1, HPA deleted, filler → 0; waits 60 s

**Phase 2 (balloon pods):**
1. Applies `priority-class` + `surge-overprovisioner`; scales to `--balloon-replicas`; waits Running
2. Deploys `cpu-burner` at 1 replica (no HPA)
3. `t_surge` = applies HPA
4. Polls HPA for scale decision; records `phase2.surge_trigger_to_hpa_decision`
5. Watches for `Preempted`/`Evicted` events; records `phase2.surge_trigger_to_preemption`
6. Tracks readiness curve under `phase2.*` milestones
7. Cleanup

**Cross-phase deltas** computed and stored in `result.extra`:
- `first_pod_improvement_ms` / `first_pod_improvement_pct`
- `full_recovery_improvement_ms` / `full_recovery_improvement_pct`

Expected runtime: **50–90 min** total (Phase 1 dominates on CAS clusters).

## Key milestones

| Milestone | Phase | Description |
|-----------|-------|-------------|
| `phase1.surge_trigger_to_hpa_decision` | 1 | Metrics-server window |
| `phase1.surge_trigger_to_pods_pending` | 1 | FailedScheduling observed |
| `phase1.surge_trigger_to_first_node_ready` | 1 | First new node provisioned |
| `phase1.surge_trigger_to_first_pod_ready` | 1 | **Degradation window start** |
| `phase1.surge_trigger_to_all_ready` | 1 | **Degradation window closed** |
| `phase2.surge_trigger_to_preemption` | 2 | Balloon pods evicted |
| `phase2.surge_trigger_to_first_pod_ready` | 2 | **First user served with prep** |
| `phase2.surge_trigger_to_all_ready` | 2 | **Full recovery with prep** |

## Recovery

Re-run the same command. If Phase 1 completed but Phase 2 did not:

```bash
# Manually clean Phase 1 remnants then re-run
oc scale deployment cpu-burner --replicas=1 -n benchmark
oc delete hpa cpu-burner-hpa -n benchmark --ignore-not-found
oc scale deployment capacity-filler --replicas=0 -n benchmark
sleep 60

python3 scripts/run-test-12-sudden-spike.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --target-replicas 10 \
  --balloon-replicas 5
```

Common failure modes:
- **Phase 1 node provisioning timeout**: increase `--timeout` or check CAS `max-nodes` in the machine pool config.
- **Phase 2 no preemption events**: balloon pods may not have scheduled (cluster had spare capacity). Check `oc get pods -n benchmark -l app=surge-overprovisioner`.

## Cleanup

After the Canvas is delivered, delete the `bench-standard` pool:

```bash
make remove-pool NAME=bench-standard CLUSTER="$CLUSTER_NAME"
```

## Report (Cursor Canvas)

Present a Canvas with:

**The headline number first** — e.g. "First user served 9 min 40 s faster with balloon pods."

**Two-phase comparison table:**

| Metric | Phase 1 (no prep) | Phase 2 (balloon pods) | Improvement |
|--------|-------------------|------------------------|-------------|
| HPA decision | `phase1.surge_trigger_to_hpa_decision` | `phase2.surge_trigger_to_hpa_decision` | — |
| First pod Ready | `phase1.surge_trigger_to_first_pod_ready` | `phase2.surge_trigger_to_first_pod_ready` | `first_pod_improvement_ms` |
| 50% Ready | `phase1.surge_trigger_to_50pct_ready` | `phase2.surge_trigger_to_50pct_ready` | delta |
| All pods Ready | `phase1.surge_trigger_to_all_ready` | `phase2.surge_trigger_to_all_ready` | `full_recovery_improvement_ms` |

**T+60s / T+120s / T+180s snapshots** — show the readiness ramp for both phases side by side.

**Narrative sections:**
- The degradation window: what users experienced in Phase 1 (HTTP 503s, timeouts)
- How balloon pods collapsed the window: preemption in <1 s, first pod Ready in seconds
- Why CAS vs Karpenter matters less than the design: with balloon pods, both become fast enough
- Sizing: `balloon_replicas = target_replicas - 1` maximises coverage; fewer balloons = partial protection
- Cost trade-off: N balloon pods hold N × 500m CPU / 512Mi permanently (ongoing AWS cost vs SLA value)
- Key message: **autoscaling design > autoscaler choice for sudden spikes**
