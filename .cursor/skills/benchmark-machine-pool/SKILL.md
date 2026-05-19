---
name: benchmark-machine-pool
description: >-
  Benchmark machine pool provisioning time across multiple instance types on a
  running ROSA cluster. Adds standard, memory-optimized, and compute-optimized
  machine pools in sequence (bare-metal excluded by default), measuring time
  from pool creation to first node Ready for each type. Use when the user wants
  to measure or compare how long different machine types take to provision and
  become schedulable. Add bare-metal only when the user explicitly requests it.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill’s close-out plus **suite HTML** under **`reports/`**). Do not end after intermediate **`make`**, **`rosa`**, or **`oc`** steps unless the user explicitly accepts no report. If blocked or partial, still deliver the report or Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Machine Pool Provisioning (Test 02)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa`, tmux MCP tools, local `tmux`, and cluster auth).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Measure the time from `rosa create machinepool` to the first node becoming `Ready`
for each machine type. The default set is three types: standard (m5.xlarge),
memory-optimized (r5.xlarge), and compute-optimized (c5.xlarge). Bare-metal
(m5.metal) is **excluded by default** — include it only when the user explicitly
asks for it (e.g. "include bare metal", "test bare metal", "run all four types").

## Mandatory close-out (agents)

Do **not** treat **`make add-pool`** (or a lone `rosa create machinepool`) as completing the benchmark. The user’s intent is a **measured, reported** run.

1. **Preflight:** Before pool creation, ensure **`export KUBECONFIG="$PWD/tmp/kubeconfig.<CLUSTER_NAME>.yaml"`** and **`oc whoami`** succeed. If not, **`oc login`** using the same pattern as **`clusters/classic/create.sh`** (user **`cluster-admin`**) or **`clusters/hcp/create.sh`** (htpasswd user **`admin`**) with **`CLUSTER_ADMIN_PASSWORD`** — otherwise the wait loop never sees **Ready** nodes and **`first_node_ready`** timings are not emitted.
2. **Execution:** Run the pool script(s) to **completion** (success or timeout/fail from the script). Use a long enough runtime budget for the shell step (bare-metal pools, if included, need up to ~90 minutes). Do not stop after “submitted” timing only.
3. **Report:** In the **same session** (unless you are only surfacing a **prior** completed checkpoint), deliver **Step 4 — Render Canvas** with tables/stats/events and narrative. If the run is partial (auth, quota, SIGTERM, user abort), the Canvas must still ship with a **clear partial/failed** section and what was captured vs missing.
4. **Checkpoint/events:** When using **`RUN_ID`**, update **`checkpoint.py`** and **`record-event.py`** per **Checkpoint & Resume** below on success or failure.

## Checkpoint & Resume

Check for an existing run before starting:
```bash
python3 scripts/record-event.py ls
STATUS=$(python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 02-machine-pool)
# If "completed", load results from events.jsonl and skip to Canvas rendering
```
Mark progress:
```bash
python3 scripts/checkpoint.py start    --run-id "$RUN_ID" --test 02-machine-pool
# ... run the test ...
python3 scripts/checkpoint.py complete --run-id "$RUN_ID" --test 02-machine-pool
# On failure:
python3 scripts/checkpoint.py fail     --run-id "$RUN_ID" --test 02-machine-pool --reason "timeout waiting for node"
```
Record each machine pool's timing as an event:
```bash
python3 scripts/record-event.py record \
  --run-id "$RUN_ID" --label "02.pool.bench-standard.node_ready" \
  --start-ms "$T_POOL_START" --end-ms "$T_NODE_READY" \
  --cluster-type "$CLUSTER_TYPE" --cluster-name "$CLUSTER_NAME" \
  --meta "instance_type=m5.xlarge"
```

## Tmux context

When running as part of `benchmark-run-all`, execute this test in the **`02-machine-pool` window** of the `benchmark-<classic|hcp>` session (socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set from session creation — do not re-export unless running this skill standalone. Use `create-window` → `execute-command` → `get-command-result` (with `capture-pane` for live progress on bare-metal pools, which take up to 90 min) per the harness in `benchmark-run-all`.

## Prerequisites

- **`oc` CLI** logged in to the target cluster (`oc whoami` succeeds). **`make add-pool`** sets **`KUBECONFIG`** but does **not** run **`oc login`** — agents must verify **`whoami`** succeeds **before** relying on timings from **`add_machine_pool`**. Use repo-isolated kubeconfig: **`export KUBECONFIG="$PWD/tmp/kubeconfig.<CLUSTER_NAME>.yaml"`** and **`oc login`** to the cluster API when the file is missing or stale.
- **Multi-AZ Classic + quota:** default `add_machine_pool` spreads pools across three zones (3+ nodes per pool). For **one node per pool in a single AZ** (less quota/capacity), set in `classic.env` / env:
  - `ROSA_MACHINE_POOL_SINGLE_AZ=yes`
  - Optional `ROSA_MACHINE_POOL_AZ=us-east-1a` (default: first AZ from `rosa describe cluster`)
  - Optional `ROSA_MACHINE_POOL_MIN_REPLICAS=1` / `ROSA_MACHINE_POOL_MAX_REPLICAS=1` (defaults when unset)
- **HCP (`CLUSTER_TYPE=hcp`):** Cluster was created with **`make create-hcp`** (Terraform) in this workspace
- `make setup` passes

## Inputs

Ask the user (or infer from context):
- `CLUSTER_TYPE`: `classic` or `hcp`
- `CLUSTER_NAME`: the cluster name (defaults `classic-bench` / `hcp-bench` from Makefile / **`classic.env`** / **`hcp.env`**; ask if unclear)
- Which machine types to test (default: standard, memory-optimized, compute-optimized; **bare-metal is excluded unless the user explicitly requests it** — it takes 20–40 min and requires dedicated instance quota)

## Procedure

### Step 1 — Baseline node count

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.<CLUSTER_NAME>.yaml"   # if not already set by scripts
oc get nodes --no-headers | grep -c " Ready " || true
```

Record count of Ready nodes before adding any pools.

### Step 2 — Add machine pools in sequence

Run the default three types sequentially. Add the bare-metal step only when the
user explicitly requested it:

```bash
make add-pool TYPE=standard CLUSTER=<name>
make add-pool TYPE=memory-optimized CLUSTER=<name>
make add-pool TYPE=compute-optimized CLUSTER=<name>
# bare-metal — run ONLY if the user explicitly asked for it:
# make add-pool TYPE=bare-metal CLUSTER=<name>
```

(`make add-pool` sets **`KUBECONFIG`** per **`CLUSTER`** via **`machine-pools/common.sh`**.)

**Observability:** `add_machine_pool` in **`machine-pools/common.sh`** emits a **snapshot** right after the pool is submitted (`emit_timing` for `submitted`), then roughly **every 2 minutes** while polling for Ready nodes, and again **on timeout** before failing. Each snapshot tries **`rosa list` / `describe machinepool`** (ROSA Classic; on **HCP** these may be missing or lag — rely on **`oc`** / console for node pools) and **`oc get machines`** (namespace `openshift-machine-api`) / **`oc get nodes -l pool-type=...`** so you can confirm OCM or the control plane saw the request and spot quota or provisioning stalls.

For each pool addition:
1. Note the start time immediately before the `make` call
2. Poll nodes using **`pool-type`** labels (what ROSA applies from **`machine-pools/add-*.sh`**), e.g.:
   - `oc get nodes -l pool-type=standard`
   - `oc get nodes -l pool-type=memory-optimized`
   - `oc get nodes -l pool-type=compute-optimized`
   - `oc get nodes -l pool-type=bare-metal`
3. Confirm **`STATUS`** column **Ready** / **`oc get node <name> -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}{end}'`**
4. Record the timestamp when the first node from the pool reaches Ready
5. Optional utilization snapshot: **`oc adm top nodes`** (requires metrics)

### Step 3 — Capture machine events

After each pool is ready:

```bash
oc get events -n openshift-machine-api --sort-by=.lastTimestamp
```

Filter mentally or with **`grep`** for the pool / machine name. Note provisioning delays or warnings.

### Step 4 — Render Canvas

Create a Canvas with:
- A table: Machine Type | Instance | vCPU | RAM | Provisioning Time
- A bar-chart style comparison (use `Stat` components with the elapsed time as value)
- Events highlights for any pools that had warnings
- A narrative comparing provision times and explaining which phases dominated

Expected provisioning times for reference:

| Pool | Instance | Expected Time | Included by default |
|------|----------|---------------|---------------------|
| standard | m5.xlarge | 4–8 min | yes |
| memory-optimized | r5.xlarge | 4–8 min | yes |
| compute-optimized | c5.xlarge | 4–8 min | yes |
| bare-metal | m5.metal | 20–40 min | **no — explicit request only** |

## Cleanup

After all timing milestones have been recorded, delete every bench pool created
in this test. Each subsequent test that needs a `bench-standard` pool creates it
at the start of that test and deletes it when done — the default `worker` pool
provides base cluster capacity between tests.

Delete in reverse provisioning order (fastest to slowest). Only include
`bench-metal` in the loop when bare-metal was actually provisioned:

```bash
# Default cleanup (no bare-metal):
for pool in bench-standard bench-memory bench-compute; do
  make remove-pool NAME="${pool}" CLUSTER="${CLUSTER_NAME}"
done

# If bare-metal was explicitly requested and provisioned, also run:
# make remove-pool NAME="bench-metal" CLUSTER="${CLUSTER_NAME}"
```

AWS terminates the EC2 instances asynchronously after each `rosa delete machinepool`
call returns; you do not need to wait for node drain before proceeding.

Inform the user that the cluster is back to the baseline `worker` pool and is
ready for individual benchmark tests (03–09, 11–13), each of which manages its
own `bench-standard` pool lifecycle.

## Retrospective

After this test completes, append to `docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`
(create the file with the standard header if it does not yet exist — see `benchmark-cluster-install` for the header format).

```markdown
## Test 02 — Machine Pool Provisioning

**Status:** completed / partial / failed

### Issues Encountered
- <List any problems and resolution status. If none, write: _None._>

### Key Insights
- <Provisioning times per instance type vs expected ranges, any outliers (e.g. bare-metal), whether parallel pool creation affected results.>
```
