---
name: benchmark-advanced-autoscaling
description: >-
  Run advanced autoscaling benchmarks (tests 10–16) on a ROSA cluster,
  provisioning the cluster first if it does not exist. Covers: Karpenter node
  provisioning speed (10, AutoNode only), planned surge with balloon pods and
  proactive pre-warming (11), sudden spike two-phase comparison (12), parallel
  multi-node provisioning stagger (13), CAS progressive scale benchmark
  (14, Classic/HCP only — CAS counterpart of test 10), spot instance
  autoscaling (15, Classic + AutoNode only — HCP standard skipped), and ARM64
  (Graviton) node provisioning (16, all cluster types). Test 10 is skipped
  automatically on Classic and standard HCP clusters (no Karpenter). Test 14
  is skipped automatically on hcp-autonode clusters (use test 10 instead).
  Test 15 is skipped on standard HCP. Tests 10 and 14 are linked — see
  AGENTS.md. Delivers a Cursor Canvas per test plus a suite HTML report. Use
  when the user asks to run advanced autoscaling benchmarks, Karpenter
  benchmarks, surge/spike scenarios, parallel node tests, spot instance tests,
  ARM64/Graviton tests, or CAS vs Karpenter comparison benchmarks on ROSA.
---

> **Agents — mandatory close-out:** Deliver a **Cursor Canvas** after each test and a **suite HTML** under `reports/` when all tests complete. If blocked or partial, still ship the Canvas/HTML with a failed/partial narrative.

# Benchmark: Advanced Autoscaling (Tests 10–16)

Runs advanced autoscaling benchmark tests on a ROSA cluster (Classic,
HCP, or HCP+AutoNode), creating the cluster if it does not already exist.

## Tooling gate (agents)

Before running this suite, verify required tools and integrations are available (`oc`, `rosa`, tmux MCP tools, local `tmux`, plus `terraform` when HCP lifecycle is in scope).
Also require Python 3.11+ for harness scripts (`datetime.UTC` is used by `record-event.py` and fails on older system Python like macOS 3.9).

Prefer the repo virtual environment before any suite command:

```bash
source .venv/bin/activate
python3 -V   # expect 3.11+
```

If any required tool or integration is missing/unhealthy, **stop and ask the user to install/fix it first**. The user may explicitly decline and request reduced-mode execution; only then proceed without the missing dependency.

Do not silently work around missing prerequisites.

## Test availability by cluster type

| Cluster type | Test 10 | Tests 11–13 | Test 14 | Test 15 | Test 16 |
|---|---|---|---|---|---|
| `hcp-autonode` (Karpenter) | **run** | run | **skip** — use test 10 | **run** | **run** |
| `hcp` (standard HCP, CAS) | **skip** — no NodeClaims | run | **run** | **skip** — no spot support | **run** |
| `classic` (CAS) | **skip** — no NodeClaims | run | **run** | **run** | **run** |

Tests 10 and 14 are the Karpenter/CAS counterparts of the same benchmark.
They share wave sizing, milestone naming conventions, and JSON output schema.
**Any change to one must be reflected in the other.** See AGENTS.md.

Check at the start of the run:

```bash
[[ "${CLUSTER_TYPE}" == "hcp-autonode" ]] && RUN_T10=true  || RUN_T10=false
[[ "${CLUSTER_TYPE}" != "hcp-autonode" ]] && RUN_T14=true  || RUN_T14=false
[[ "${CLUSTER_TYPE}" != "hcp" ]]           && RUN_T15=true  || RUN_T15=false
RUN_T16=true   # test 16 runs on all cluster types
echo "Test 10: $RUN_T10   Test 14: $RUN_T14   Test 15: $RUN_T15   Test 16: $RUN_T16"
```

If `RUN_T10=false`, mark it skipped and proceed to test 11:

```bash
python3 scripts/checkpoint.py skip \
  --run-id "${BENCHMARK_RUN_ID}" --test 10-autonode-scale \
  --reason "cluster type ${CLUSTER_TYPE} does not support Karpenter NodeClaims"
```

If `RUN_T14=false`, mark it skipped and proceed to the suite close-out:

```bash
python3 scripts/checkpoint.py skip \
  --run-id "${BENCHMARK_RUN_ID}" --test 14-cas-scale \
  --reason "cluster type ${CLUSTER_TYPE} is hcp-autonode — use test 10 (Karpenter) instead"
```

Test 15 runs on `classic` and `hcp-autonode`; skip it on `hcp`:

```bash
[[ "${CLUSTER_TYPE}" != "hcp" ]] && RUN_T15=true || RUN_T15=false
echo "Test 15 will run: $RUN_T15"
```

If `RUN_T15=false`:

```bash
python3 scripts/checkpoint.py skip \
  --run-id "${BENCHMARK_RUN_ID}" --test 15-spot-instances \
  --reason "standard HCP does not support spot instances without AutoNode"
```

## Cluster lifecycle

### Detect existing cluster

```bash
# Read env for the target cluster type
CLUSTER_TYPE="${CLUSTER_TYPE:-hcp-autonode}"   # classic | hcp | hcp-autonode

STATE_FILE="tmp/cluster.${CLUSTER_TYPE}.json"
CLUSTER_STATE=$(python3 -c "import json; print(json.load(open('${STATE_FILE}'))['cluster_name'])" 2>/dev/null || echo "missing")
echo "Cluster state: $CLUSTER_STATE"
```

If the state file exists and the cluster is reachable (`oc whoami` succeeds with the corresponding kubeconfig), skip to **Pre-flight**. If absent or not reachable, provision it first.

### Provision cluster (if needed)

| Cluster type | Provision skill | Make target |
|---|---|---|
| `hcp-autonode` | `benchmark-create-hcp-autonode` | `make create-hcp-autonode` |
| `hcp` | `benchmark-cluster-install` | `make create-hcp` |
| `classic` | `benchmark-cluster-install` | `make create-classic` |

Run in the tmux session (socket `benchmark-<RUN_ID>`, window `01-create`) so the long install survives IDE restarts.

For `hcp-autonode`: Do **not** use `benchmark-cluster-install` — AutoNode provisioning is handled exclusively by `clusters/hcp-autonode/create.sh` via `make create-hcp-autonode`.

## Session & environment setup

```bash
# Set cluster type (classic | hcp | hcp-autonode)
CLUSTER_TYPE="${CLUSTER_TYPE:-hcp-autonode}"

# Source the matching env file to get CLUSTER_NAME
case "$CLUSTER_TYPE" in
  hcp-autonode) source autonode.env; CLUSTER_NAME="${ROSA_CLUSTER_NAME_AUTONODE}" ;;
  hcp)          source hcp.env;      CLUSTER_NAME="${ROSA_CLUSTER_NAME_HCP}" ;;
  classic)      source classic.env;  CLUSTER_NAME="${ROSA_CLUSTER_NAME_CLASSIC}" ;;
esac

# Reuse existing run_id or mint a new one
RUN_ID=$(python3 -c "import json; print(json.load(open('tmp/cluster.${CLUSTER_TYPE}.json'))['run_id'])" 2>/dev/null \
  || python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-${CLUSTER_TYPE}')")

export KUBECONFIG="$PWD/tmp/kubeconfig.${CLUSTER_NAME}.yaml"
export BENCHMARK_RUN_ID="$RUN_ID"
export CLUSTER_NAME CLUSTER_TYPE

# Determine whether test 10 runs
[[ "${CLUSTER_TYPE}" == "hcp-autonode" ]] && RUN_T10=true || RUN_T10=false
```

Use the **tmux** MCP (socket `benchmark-<RUN_ID>`, session `benchmark-<CLUSTER_TYPE>`); create a window per test.

## NodePool pre-flight (hcp-autonode only)

On `hcp-autonode`, the `autonode-bench` Karpenter NodePool must exist before tests 10–13 run (workloads target it via nodeAffinity). Skip this step on Classic/HCP.

```bash
if [[ "${CLUSTER_TYPE}" == "hcp-autonode" ]]; then
  oc get nodepool autonode-bench 2>/dev/null || oc apply -f manifests/autonode/nodepool.yaml
fi
```

## Execution order

| # | Test | Script | Cluster types | Approx duration |
|---|------|--------|---------------|-----------------|
| 10 | Karpenter scale (3 waves + consolidation) | `run-test-10-autonode-scale.py` | hcp-autonode only | 60–90 min |
| 11 | Planned surge (balloon-pods + proactive-nodes) | `run-test-11-planned-surge.py` | all | 30–50 min |
| 12 | Sudden spike (two-phase comparison) | `run-test-12-sudden-spike.py` | all | 60–90 min |
| 13 | Parallel node provisioning | `run-test-13-parallel-nodes.py` | all | 10–20 min |
| 14 | CAS progressive scale (3 waves + scale-down) | `run-test-14-cas-scale.py` | classic, hcp only | 120–180 min |
| 15 | Spot instance autoscaling | `run-test-15-spot-instances.py` | classic, hcp-autonode | 8–20 min |
| 16 | ARM64 (Graviton) node provisioning | `run-test-16-arm-nodes.py` | all | 8–20 min |

Run sequentially unless resuming from a checkpoint. After each test completes, deliver its Canvas before starting the next.

Test 14 runs last among the CAS/Karpenter scale tests because its Phase 3 (CAS scale-down) is the longest phase in the suite (~45–90 min for 3 rollback steps). On `hcp-autonode` clusters test 14 is skipped — test 10 already covers the Karpenter equivalent. Test 15 (spot) and test 16 (ARM64) run after test 14 because they are independent and short (8–20 min each).

## Test commands

Pass `--cluster-type "${CLUSTER_TYPE}"` to every script. On `hcp-autonode`, the scripts automatically use Karpenter manifests (`cpu-burner-karpenter.yaml`, `surge-overprovisioner-karpenter.yaml`, etc.) and the `--nodepool-name` flag. On Classic/HCP, they use standard manifests targeting `pool-type=standard` machine pools.

```bash
# Shared flags — append to every command below
COMMON="--cluster-name ${CLUSTER_NAME} --cluster-type ${CLUSTER_TYPE} --run-id ${BENCHMARK_RUN_ID}"
NODEPOOL="--nodepool-name autonode-bench"   # hcp-autonode only; omit for classic/hcp
```

### Test 10 — Karpenter scale *(hcp-autonode only — skip on classic/hcp)*

```bash
if [[ "$RUN_T10" == "true" ]]; then
  python3 scripts/run-test-10-autonode-scale.py $COMMON 2>&1 | tee /tmp/test-10.log
else
  python3 scripts/checkpoint.py skip --run-id "${BENCHMARK_RUN_ID}" --test 10-autonode-scale \
    --reason "cluster type ${CLUSTER_TYPE} does not support Karpenter NodeClaims"
  echo "[skip] Test 10 — not applicable for ${CLUSTER_TYPE}"
fi
```

Follow **`benchmark-autonode-scale`** skill for milestone definitions and Canvas format.

### Test 11 — Planned surge *(all cluster types)*

On Classic/HCP, omit `$NODEPOOL`; the script uses `pool-type=standard` machine pool nodes instead.

```bash
# balloon-pods strategy
python3 scripts/run-test-11-planned-surge.py $COMMON \
  --strategy balloon-pods --balloon-replicas 5 \
  $([[ "$CLUSTER_TYPE" == "hcp-autonode" ]] && echo "$NODEPOOL") \
  --timeout 2400 2>&1 | tee /tmp/test-11-balloon.log

# proactive-nodes strategy
python3 scripts/run-test-11-planned-surge.py $COMMON \
  --strategy proactive-nodes --prewarm-nodes 2 \
  $([[ "$CLUSTER_TYPE" == "hcp-autonode" ]] && echo "$NODEPOOL") \
  --timeout 2400 2>&1 | tee /tmp/test-11-proactive.log
```

Follow **`benchmark-planned-surge`** skill for Canvas format.

### Test 12 — Sudden spike *(all cluster types)*

```bash
python3 scripts/run-test-12-sudden-spike.py $COMMON \
  --target-replicas 10 --balloon-replicas 5 \
  $([[ "$CLUSTER_TYPE" == "hcp-autonode" ]] && echo "$NODEPOOL") \
  --timeout 3600 2>&1 | tee /tmp/test-12.log
```

Follow **`benchmark-sudden-spike`** skill for Canvas format.

### Test 13 — Parallel nodes *(all cluster types)*

```bash
python3 scripts/run-test-13-parallel-nodes.py $COMMON \
  --expected-nodes 3 \
  $([[ "$CLUSTER_TYPE" == "hcp-autonode" ]] && echo "$NODEPOOL") \
  --timeout 2400 2>&1 | tee /tmp/test-13.log
```

Follow **`benchmark-parallel-nodes`** skill for Canvas format and node arrival timeline.

### Test 14 — CAS progressive scale *(classic and hcp only — skip on hcp-autonode)*

```bash
if [[ "$RUN_T14" == "true" ]]; then
  python3 scripts/run-test-14-cas-scale.py $COMMON \
    --timeout 5400 2>&1 | tee /tmp/test-14.log
else
  python3 scripts/checkpoint.py skip --run-id "${BENCHMARK_RUN_ID}" --test 14-cas-scale \
    --reason "cluster type ${CLUSTER_TYPE} is hcp-autonode — use test 10 (Karpenter) instead"
  echo "[skip] Test 14 — not applicable for ${CLUSTER_TYPE}"
fi
```

Follow **`benchmark-cas-scale`** skill for milestone definitions and Canvas format.
The Canvas should include a CAS vs Karpenter side-by-side table when test 10
data is available in `results/$RUN_ID/events.jsonl` from the same run.

### Test 15 — Spot instance autoscaling *(classic + hcp-autonode only — skip on hcp)*

```bash
if [[ "$RUN_T15" == "true" ]]; then
  python3 scripts/run-test-15-spot-instances.py $COMMON \
    $([[ "$CLUSTER_TYPE" == "hcp-autonode" ]] && echo "--nodepool-name autonode-spot") \
    --timeout 1800 2>&1 | tee /tmp/test-15.log
else
  python3 scripts/checkpoint.py skip --run-id "${BENCHMARK_RUN_ID}" --test 15-spot-instances \
    --reason "standard HCP does not support spot instances without AutoNode"
  echo "[skip] Test 15 — not applicable for ${CLUSTER_TYPE}"
fi
```

Follow **`benchmark-spot-instances`** skill for milestone definitions and Canvas format.

### Test 16 — ARM64 (Graviton) node provisioning *(all cluster types)*

```bash
python3 scripts/run-test-16-arm-nodes.py $COMMON \
  $([[ "$CLUSTER_TYPE" == "hcp-autonode" ]] && echo "--nodepool-name autonode-arm64") \
  --timeout 1800 2>&1 | tee /tmp/test-16.log
```

Follow **`benchmark-arm-nodes`** skill for milestone definitions and Canvas format.
On `hcp-autonode`, the script verifies that `ec2nodeclass/default` has an arm64
AMI in `status.amis` before proceeding — both the RHCOS aarch64 and x86_64 AMIs
are pre-populated by HyperShift, so no custom NodeClass is needed.

## Checkpoint management

```bash
# Check progress
python3 scripts/checkpoint.py status --run-id "${BENCHMARK_RUN_ID}"

# Resume from next pending test
NEXT=$(python3 scripts/checkpoint.py next --run-id "${BENCHMARK_RUN_ID}")
echo "Next: $NEXT"
```

## Suite close-out

After all tests complete (10–16, skipping inapplicable ones):

1. **Per-test Canvases** — deliver one Canvas per test following the individual skill's Canvas spec:
   - Test 10 → `benchmark-autonode-scale`
   - Test 11 → `benchmark-planned-surge`
   - Test 12 → `benchmark-sudden-spike`
   - Test 13 → `benchmark-parallel-nodes`
   - Test 14 → `benchmark-cas-scale`
   - Test 15 → `benchmark-spot-instances`
   - Test 16 → `benchmark-arm-nodes`

2. **Suite HTML** — write `reports/<RUN_ID>-<CLUSTER_TYPE>-advanced-suite-10-through-16.html` with:
   - KPI grid: provisioner NodeClaim/TriggeredScaleUp latency, balloon-pods surge response, sudden-spike degradation window with/without prep, parallel-node stagger, scale-down speed, spot vs. on-demand provisioning delta, ARM vs x86 boot time delta
   - Detailed timing table (one row per test/strategy)
   - **CAS vs Karpenter comparison section** when both test 10 and test 14 were run (requires running on both cluster types in the same suite)
   - **Spot vs. on-demand section** when test 15 ran alongside test 03 or test 10
   - **ARM vs x86 section** — `nodeclaim_to_node_ready` comparison from test 16 vs test 10/03 baseline
   - Key findings: provisioner scheduling decision speed, balloon pods ROI, stagger impact on load distribution, CAS cooldown cost, spot cost/speed trade-off, ARM64 boot time and cost parity
   - Recommendations

3. **Regenerate index:**
   ```bash
   python3 scripts/update-reports-index.py
   ```

## Error handling

| Error | Cluster type | Recovery |
|-------|---|---|
| Cluster missing | any | Provision via the matching skill/make target (see Cluster lifecycle) |
| `autonode-bench` NodePool missing | hcp-autonode | `oc apply -f manifests/autonode/nodepool.yaml` |
| Test 10 attempted on wrong cluster type | classic/hcp | Should have been auto-skipped; run the `checkpoint skip` command manually |
| Test 14 attempted on hcp-autonode | hcp-autonode | Should have been auto-skipped; run the `checkpoint skip` command manually |
| Test 14 Phase 3 times out | classic/hcp | CAS cooldown still active; increase `--timeout 7200`; check `oc get clusterautoscaler -o yaml` for scale-down settings |
| Test 11/12 balloon pods not Running | hcp-autonode | Check Karpenter NodePool capacity; verify `maxNodes` in the NodePool spec |
| Test 11/12 balloon pods not Running | classic/hcp | Check machine pool `max-replicas`; run `oc get machines -n openshift-machine-api` |
| Test 12 Phase 1 timeout | any | Increase `--timeout 5400`; on hcp-autonode check `oc get nodeclaims`; on classic/hcp check CAS events |
| Test 13 fewer nodes than expected | classic/hcp | Verify machine pool `max-replicas ≥ current + expected-nodes`; check `rosa list machinepools` |
| Test 13 fewer nodes than expected | hcp-autonode | Verify NodePool `maxNodes`; check `oc get nodeclaims -l karpenter.sh/nodepool=autonode-bench` |
| OCM 403 during hcp-autonode create | hcp-autonode | Follow recovery path in `clusters/hcp-autonode/create.sh` (manual IDP + IAM trust policy update) |

## Cleanup (optional — confirm with user)

```bash
# Remove benchmark namespace workloads only
oc delete namespace benchmark autonode-test --ignore-not-found

# Destroy cluster (requires explicit user confirmation before running)
make destroy-hcp-autonode
```

Never destroy the cluster automatically — always confirm with the user first.
