---
name: benchmark-overprovisioning
description: >-
  Demonstrate and benchmark the cluster overprovisioning pattern using
  low-priority pause pods as headroom reservations. Skill default: saturated
  pool baseline (packed benchmark workers via live-sized capacity-filler, then
  HPA burst). Shows how pre-reserved capacity allows HPA to schedule pods
  immediately without waiting for CAS/Karpenter to provision new nodes, then
  measures latency versus test 08. Use when the user wants to understand or
  demonstrate the pause-pod overprovisioning pattern and its impact on HPA
  response time.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill's close-out plus **suite HTML** under **`reports/`**). **Also append the retrospective** (see **[Retrospective](#retrospective)**): **`docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`** — test **09** for Classic/CAS/HCP CAS, **09b** for **`hcp-autonode`**. Do not end after the script invocation. If blocked or partial, still deliver the report or Canvas with a clear narrative **and** a retro section (status partial/failed, what blocked). See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Overprovisioning with Pause Pods (Test 09)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa` where applicable, tmux MCP tools, local `tmux`, and cluster auth).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Deploy low-priority placeholder (pause) pods that reserve cluster capacity as
headroom. When HPA fires, real pods preempt the pause pods immediately — no
waiting for CAS to provision new nodes. Measure the scheduling latency
improvement compared to test 08.

**Default for this skill:** **saturated pool baseline** (`--saturated-pool-baseline`) — wait for N benchmark workers, **compute `capacity-filler` replicas from live pool CPU/memory** (namespace **`benchmark` excluded** so stale runs do not skew the baseline), deploy pause + filler + cpu-burner + HPA together, then HPA burst. Override sizing with **`--capacity-filler-replicas`**. The legacy **pause-first** ordering is documented below as an explicit opt-out.

## How Overprovisioning Works

1. Deploy pause pods at `PriorityClass: cluster-overprovisioner` (value: -1)
2. Pause pods request real CPU/memory — they occupy node capacity
3. CAS sees the cluster as "full" from the pause pods' perspective; provisions extra nodes to satisfy them
4. When HPA fires and real pods need to schedule, the scheduler preempts pause pods
5. Real pods take the freed capacity immediately (sub-second)
6. CAS sees evicted pause pods as unschedulable → provisions replacement nodes (background)

Net result: HPA scaling is instant; CAS provisioning happens asynchronously.

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 09-overprovisioning
```

For **`run-test-09b-karpenter-overprovisioning.py`**, use `--test 09b-karpenter-overprovisioning`.

## Tmux — required for executing the test (agents)

**Do not** run `run-test-09*.py` to completion in the **Cursor integrated Shell** as a single long foreground command — tool time limits can **SIGTERM** the job mid-test and corrupt cluster/checkpoint state.

**Do** run the script inside **tmux**, same as **`benchmark-run-all`**:

| Mode | What to use |
|------|-------------|
| Part of **`benchmark-run-all`** | Window **`09-overprovisioning`** on session **`benchmark-classic`** or **`benchmark-hcp`**; for AutoNode use **`benchmark-hcp-autonode`** (see **`benchmark-run-all`** session topology). Socket: **`benchmark-<RUN_ID>`** on every tmux MCP call. |
| **Standalone** Test 09 / 09b | Create or attach a tmux session (e.g. **`benchmark-hcp-autonode`** or **`benchmark-standalone-09`**), set **`cd`** to the repo, then **`export KUBECONFIG`** and **`export BENCHMARK_RUN_ID`** / pass **`--run-id`**, and **`execute-command`** with the full **`python3 scripts/run-test-09…`** line from **Run (default)** below. Poll with **`get-command-result`** + **`capture-pane`** until completion or failure. |

**MCP:** use the **user-tmux** server (`create-session`, `create-window`, `execute-command`, `get-command-result`, `capture-pane`). Use a **per-run socket** (e.g. `TMUX_MCP_SOCKET` / socket id = `benchmark-<RUN_ID>`) so this session stays isolated from other work.

**Preflight** (`oc whoami`, checkpoint **status**) may run in short Shell invocations; the **benchmark script itself** runs in tmux.

`nohup` is only a last resort when the user explicitly declines fixing tmux MCP / local `tmux` and approves reduced mode — otherwise pause and request tmux setup first.

When running as part of `benchmark-run-all`, `KUBECONFIG` and `BENCHMARK_RUN_ID` are typically already set from session creation — re-export only for standalone windows. Use the **saturated default** `python3` command from **Run (default — saturated pool baseline)** (not the legacy block) unless intentionally reproducing pause-first behavior.

## Prerequisites

- Test 08 completed (provides the baseline comparison timing; its `bench-standard` pool has been deleted)
- Cluster running with only the default `worker` pool — this test creates its own `bench-standard` pool
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

**Test 09 / 09b:** if you omit `--run-id`, both scripts resolve it automatically from `tmp/cluster.<--cluster-type>.json` (same shape as above). A warning is printed when the file’s `cluster_name` does not match `--cluster-name`.

## Pre-flight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami
```

**ROSA Classic (`--cluster-type classic`):** `run-test-09-overprovisioning.py`
creates the **`bench-standard`** machine pool automatically when it is missing,
using the same labels as `make add-pool TYPE=standard` (`benchmark=true`,
`pool-type=standard`) so workload `nodeSelector` / preflight slack stay consistent.
You can still run `make add-pool` first if you prefer; use
`--skip-classic-bench-machinepool-create` to disable auto-create.

If **`rosa create machinepool`** or **`rosa edit machinepool`** returns **OCM HTTP 503**,
the script **stops** with an auth/API message (no retry). Fix `rosa login` /
`rosa whoami` and cluster API access, then re-run.

**ROSA HCP (CAS, not AutoNode):** continue to add the machine pool out-of-band if
your topology requires it (`make add-pool` or console); this script does not
auto-create pools for `--cluster-type hcp`.

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami
```

Pause pods and `cpu-burner` (Classic manifests) target **`pool-type: standard`**
so scheduling is isolated to the bench pool.

Optional manual pool creation (Classic, if you disabled auto-create or need a dry run check first):

```bash
make add-pool TYPE=standard CLUSTER="$CLUSTER_NAME" \
  AUTOSCALE_MIN_REPLICAS=3 AUTOSCALE_MAX_REPLICAS=12
```

## Run (default — saturated pool baseline)

Use this when executing the skill from **`benchmark-run-all`** (tmux `09-overprovisioning` window) or standalone. **`rosa`** must be on `PATH` for Classic/HCP when using `--rosa-machinepool-*`.

### Classic or HCP (CAS) — `run-test-09-overprovisioning.py`

```bash
python3 scripts/run-test-09-overprovisioning.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --saturated-pool-baseline \
  --baseline-pool-ready-count 3 \
  --rosa-machinepool-min 3 \
  --rosa-machinepool-max 12 \
  --require-saturated-before-balloons \
  --timeout 2400
```

(`$CLUSTER_TYPE` is `classic` or `hcp`.)

### HCP AutoNode (Karpenter) — `run-test-09b-karpenter-overprovisioning.py`

**NodePool:** `manifests/autonode/nodepool.yaml` (or Terraform) must define **`karpenter.sh/nodepool=<name>`** (skill default **`autonode-bench`**). If the pool is **empty**, the script applies a **transient** workload (`manifests/workloads/karpenter-bench-bootstrap.yaml` — **pod anti-affinity** so **`--baseline-pool-ready-count`** pods spread across **distinct nodes**, then scales it to **0** before sizing). You can still pre-warm the pool out-of-band if you prefer.

```bash
python3 scripts/run-test-09b-karpenter-overprovisioning.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type hcp-autonode \
  --run-id "$RUN_ID" \
  --nodepool-name autonode-bench \
  --saturated-pool-baseline \
  --baseline-pool-ready-count 3 \
  --require-saturated-before-balloons \
  --timeout 2400
```

**Capacity-filler:** omit **`--capacity-filler-replicas`** so the script sums allocatable CPU/memory on **Ready** bench nodes (`pool-type=standard` for Classic/CAS, `karpenter.sh/nodepool=<name>` for AutoNode), compares to **pod requests excluding namespace `benchmark`**, and picks a replica count that targets **`--max-slack-cpu-cores`** (default **2** cores) after pause + steady cpu-burner + filler. **09b only:** after the bundle is **Running**, the script may run **extra pack rounds** (`--karpenter-pack-max-rounds`, `--karpenter-pack-settle-s`) if Karpenter grew the pool and CPU slack is still ≥ threshold. Pass **`--capacity-filler-replicas`** only to override initial math.

### Legacy (pause-first — opt out of saturated default)

For parity with older suite runs, **omit** `--saturated-pool-baseline` and all `--rosa-machinepool-*` / `--baseline-pool-*` flags. Expect **`extra.topology_mode` = `pause_first_then_filler`**. Pool sizing warnings in the retrospective still apply (hidden slack).

```bash
python3 scripts/run-test-09-overprovisioning.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --timeout 2400
```

### Reference — optional flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--cpu-burner-replicas` | `3` | Target `cpu-burner` replicas after HPA trigger |
| `--saturated-pool-baseline` | **on in skill default command** | Wait for N benchmark workers, apply pause + filler + cpu-burner + HPA together, scale filler, then burst |
| `--baseline-pool-ready-count` | `3` | Min Ready nodes on `pool-type=standard` or `karpenter.sh/nodepool=<name>` before deploy |
| `--baseline-pool-wait-timeout-s` | `2400` | Wait timeout for those nodes |
| `--capacity-filler-replicas` | **Omit** on saturated default → **computed** from pool alloc vs pod requests (`benchmark` excluded); **legacy** / explicit override: set integer; else manifest default until scaled | Pins or overrides live sizing for `capacity-filler` (400m CPU / 400Mi per pod) |
| `--rosa-machinepool-min` / `--rosa-machinepool-max` | **set in skill default (Classic/HCP)** | **classic/hcp:** `rosa edit machinepool` on `--machinepool-name` (`bench-standard`). Omit only for **legacy** pause-first or if you already sized the pool out-of-band |
| `--machinepool-name` | `bench-standard` | Pool for ROSA edit |
| `--nodepool-name` | `autonode-bench` | **hcp-autonode:** label + NodeClaim scope in `run-test-09` / `09b` |
| `--require-saturated-before-balloons` | **on in skill default command** | **Saturated:** fail post-bundle if CPU slack ≥ `--max-slack-cpu-cores`. **Legacy:** fail before pause pods |
| `--max-slack-cpu-cores` | `2` | Slack threshold (cores) |
| `--karpenter-pack-max-rounds` | `15` | **09b:** max iterations to add filler after settle if pool slack still high |
| `--karpenter-pack-settle-s` | `20` | **09b:** sleep before each post-bundle slack sample during pack |
| `--expect-worker-count` | _(unset)_ | Fail when cluster-wide Ready **node** count ≠ this value |
| `--skip-scale-down-observe` | **off** | Skip post-restore phase: idling `cpu-burner` for HPA scale-down + fleet stabilization wait |
| `--scale-down-timeout-s` | `2400` | Max time for HPA-at-min + fleet stability (split ~50/50 between phases) |
| `--scale-down-stable-polls` | `3` | Consecutive identical fleet-size samples (NodeClaims or pool Ready nodes) required |
| `--sustained-peak-duration-s` | `1200` | After burst pods are **Ready**: keep cpu-burner at HPA load this many seconds while **polling** nodes, HPA replicas, pause/cpu-burner pod phases, and fleet metrics (**20 min** default). `0` skips. |
| `--sustained-peak-poll-interval-s` | `60` | Seconds between polls during sustained peak |

**Saturated path** (`extra.topology_mode` = `saturated_pool_baseline`):

0. Optional **`rosa edit machinepool`** (classic/hcp only) — then wait for **`baseline-pool-ready-count`** Ready nodes on the pool label
1. **Size `capacity-filler`** (unless `--capacity-filler-replicas` is set): live **`extra.capacity_filler_sizing`** from pool allocatable CPU/memory vs requests on those nodes, excluding namespace **`benchmark`**
2. Snapshot `t0_baseline`
3. Apply PriorityClass + pause + capacity-filler + cpu-burner + HPA; scale filler; wait deployments; wait pause pods Running
4. Snapshot `after_headroom`; record **`start_to_headroom_ready`**; post-bundle slack + optional fail (`--require-saturated-before-balloons`)
5. Scale `cpu-burner` to HPA target; snapshot `at_hpa_trigger`
6. Preemption poll; **cpu-burner** Running/Ready; **`burst_absorption_mechanism`** / evidence; snapshot `after_workload_running`
7. **Sustained peak (default 20m):** with burst pods **Ready**, keep cpu-burner under load (`yes` burn) and record **`extra.sustained_peak.samples`** on each poll (`timestamp_ms`, full node name list plus **`nodes_added_vs_prev`** / **`nodes_removed_vs_prev`**, bench-pool Ready count, cluster Ready node count, HPA current+desired replicas, pause and cpu-burner **phase counts**, **NodeClaims** or **MachineSet** replicas). Milestone **`…sustained_peak_wall_clock`** spans the dwell. Runs **before** the headroom-restore wait so CAS/Karpenter behavior **during peak load** is visible. Skip with **`--sustained-peak-duration-s 0`**. Raise **`--timeout`** for long peaks (script warns if `timeout` looks too low vs peak + restore + observe).
8. Headroom restore poll; snapshot `after_restore`; **`restore_fleet_delta`**
9. **Scale-down observation (default):** snapshot `before_hpa_scale_down_burn` → JSON-patch `cpu-burner` to **`sleep infinity`** (HPA scale-down includes 300s stabilization) → poll HPA at **minReplicas** → poll stable fleet size → snapshot `after_fleet_scale_down` → restore stress command; **`extra.scale_down`**. Omit with **`--skip-scale-down-observe`** or **`--dry-run`**.
10. Cleanup; JSON summary (`fleet_snapshots`, `preflight`, `capacity_filler_sizing`, `sustained_peak`, etc.)

**Legacy path** (`pause_first_then_filler`): preflight slack → pause only → wait → filler + HPA → same burst/restore phases as above.

**Fleet snapshot shapes (for agents / HTML):**

- **Classic / HCP (CAS):** each snapshot may include `machineset_replicas`: `{ <machineset>: { desired, ready, available } }`.
- **hcp-autonode:** each snapshot includes `nodeclaim_count` (09: all NodeClaims; 09b: filtered by `--nodepool-name`) and, on 09b, `nodepool_name`.

Expected runtime: **35–75+ minutes** when using the default **20m** sustained peak, plus pause provisioning, headroom restore, and optional scale-down observation — raise **`--timeout`** accordingly.

**Suite ordering:** residual capacity from earlier tests can make **`burst_absorption_mechanism=slack`** honest but unintended. Prefer a dedicated cluster, a reset before Test 09, or **`--require-saturated-before-balloons`** once slack policy is validated (watch cloud quota / max nodes so normalization does not wedge the suite).

## Recovery

Re-run the **same** invocation you used initially — for the skill default, that is the **saturated** command from **Run (default)**:

```bash
python3 scripts/run-test-09-overprovisioning.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --saturated-pool-baseline \
  --baseline-pool-ready-count 3 \
  --rosa-machinepool-min 3 \
  --rosa-machinepool-max 12 \
  --require-saturated-before-balloons \
  --timeout 2400
```

(For `hcp-autonode`, use the **09b** saturated block from the Run section — same live filler sizing as Classic when `--capacity-filler-replicas` is omitted.)

Common failure modes:
- **Pause pods not Running within the wait window** (20m for test **09**, 15m for **09b**): machine pool max-replicas may be too low to host pause pods + existing workload. Check `oc get machines -n openshift-machine-api` (Classic) or NodePool / NodeClaims (HCP AutoNode).
- **cpu-burner pods not Running within 5m via preemption**: pause pods may not have been large enough to free sufficient capacity. Check pause pod resource requests vs cpu-burner pod requests.
- **Post-bundle CPU slack ≥ threshold:** raise **`--capacity-filler-replicas`** manually, increase **`--max-slack-cpu-cores`**, or fix **`extra.capacity_filler_sizing`** errors (CPU vs memory bound on the pool).

## Cleanup

After the Canvas is delivered, delete the `bench-standard` pool:

```bash
make remove-pool NAME=bench-standard CLUSTER="$CLUSTER_NAME"
```

## Report (Cursor Canvas)

**Comparison table** vs test 08:

| Metric | Test 08 (no overprovisioning) | Test 09 (with overprovisioning) | Improvement |
|--------|------------------------------|--------------------------------|-------------|
| HPA trigger → pods Running | T_08_TOTAL | T_09_TOTAL | delta |
| CAS provisioning wait | T_08_CAS | ~0 (preemption) | delta |
| User-facing latency | high | low | delta |
| Headroom restore (background) | N/A | T_09_RESTORE | — |
| **Burst absorption** | — | **`extra.burst_absorption_mechanism`** + **`extra.burst_absorption_evidence`** | Labels honest path: reserved headroom vs spare capacity |
| **Restore fleet proof** | — | **`extra.restore_fleet_delta`** (`type` + `count`) | Shows whether placeholders refilled via new machines / NodeClaims / nodes only |

**Include:**

- **`extra.pool_bootstrap`** (09b saturated): whether transient **`autonode-bootstrap` / `pool-warm`** ran to spread **`--baseline-pool-ready-count`** across distinct NodePool nodes before sizing
- **`extra.capacity_filler_pack_rounds`** (09b): post-bundle filler add iterations when Karpenter left excess CPU slack — empty if first settle was already under threshold
- Before/after pause pod status (Running → Evicted → Running again)
- Preemption events with timestamps (and note whether they fall **after** `at_hpa_trigger` — stale events are filtered in-script)
- **`extra.fleet_snapshots`** timeline (`t0_baseline` → `after_headroom` → `at_hpa_trigger` → `after_workload_running` → optionally `before_hpa_scale_down_burn` → `after_fleet_scale_down`; headroom restore **`after_restore`** comes **after** the sustained-peak window)
- **`extra.sustained_peak`** (unless duration `0`): `duration_s_requested`, `poll_interval_s`, `sample_count`, **`samples[]`** with `timestamp_ms`, node lists, `nodes_added_vs_prev` / `nodes_removed_vs_prev`, HPA replicas, pause/cpu-burner phases, NodeClaims or MachineSets
- **`extra.scale_down`** (unless skipped): HPA-at-min + fleet-stability flags, fleet metric, before/after sizes
- CAS / Karpenter headroom restoration / node provisioning (tie to `restore_fleet_delta`)
- **Trade-offs section**:
  - Cost: extra nodes to host pause pods (ongoing AWS cost)
  - Benefit: HPA latency reduced from minutes to seconds
  - Sizing guidance: headroom = expected HPA burst size × pod resource requests
  - CAS still provisions eventually — the difference is whether the user waits

## Retrospective

**Agents — required:** After the HTML report exists (and Canvas when applicable), **append** a **Test 09** or **Test 09b** subsection to **`docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`**. Create the file from the template below if it does not exist. Use **`hcp-autonode`** for **09b** runs; **`classic`** / **`hcp`** for **`run-test-09-overprovisioning.py`**. If the file already has an older Test 09 entry for the same run, **add a dated subheading** (e.g. saturated-baseline rerun) instead of deleting history.

```markdown
## Test 09 — Overprovisioning

**Status:** completed / partial / failed  
**Time (HPA trigger → pods Ready):** <X>m <Y>s  
**Time to headroom restored:** <X>s

### Topology verification (from JSON `extra`)

Copy from the test stdout or `results/<RUN_ID>/` artifacts:

- **`extra.topology_mode`:** `saturated_pool_baseline` (skill default) vs `pause_first_then_filler` (legacy).
- **`extra.capacity_filler_sizing`** (saturated, when `--capacity-filler-replicas` omitted): chosen replica count, pool alloc vs baseline requests (`benchmark` excluded), projected CPU slack — sanity-check packing before interpreting preemption.
- **`preflight.new_nodes_for_balloons`:** how many **new Ready node names** appeared between `t0_baseline` and `after_headroom` (0 ⇒ pause pods landed on existing capacity).
- **`burst_absorption_mechanism`:** `preemption` \| `slack` \| `mixed` — paired with **`burst_absorption_evidence`** (event count + node delta after HPA trigger).
- **`restore_fleet_delta`:** `none` \| `machineset+N` \| `nodeclaim+N` \| `node+N` — whether headroom restore increased MachineSet desired replicas, NodeClaims (Karpenter), or only node count without the above.

### Issues Encountered
- <List any problems and resolution status. If none, write: _None._>

### Key Insights
- <Whether **`burst_absorption_mechanism`** matches the intended story (headroom vs suite slack), headroom timing vs test 08, and how **`restore_fleet_delta`** confirms the autoscaler refilled cushions.>
```

For **09b** (`hcp-autonode`), use heading **`## Test 09b — Karpenter overprovisioning`** and extend **Topology verification** with **`extra.sustained_peak`**, **`extra.pool_bootstrap`** / **`extra.capacity_filler_pack_rounds`**, and **`extra.scale_down`** (incl. partial observe).
