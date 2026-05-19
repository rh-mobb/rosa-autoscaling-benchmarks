---
name: benchmark-vpa-advise
description: >-
  Show Vertical Pod Autoscaler recommendations for the cpu-burner workload in
  advise-only mode. Reads the VPA object's recommendation status after the
  workload has been running under load, presents the suggested CPU and memory
  bounds, and explains when and why you would act on VPA recommendations versus
  relying on HPA. Use when the user wants to understand VPA recommendations,
  see what resources VPA would suggest, or demonstrate VPA in advise mode.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill's close-out plus **suite HTML** under **`reports/`**). Do not end after the script invocation. If blocked or partial, still deliver the report or Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: VPA Advise Mode (Test 07)

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, tmux MCP tools, local `tmux`, and cluster auth).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Read and present VPA recommendations for the cpu-burner deployment after it has
been running under load. Explain what each recommendation value means and when
to act on it.

## Checkpoint & Resume

```bash
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 07-vpa-advise
```

## Tmux context

When running as part of `benchmark-run-all`, execute this test in the **`07-vpa-advise` window** of the `benchmark-<classic|hcp>` session (socket `benchmark-<RUN_ID>`). `KUBECONFIG` and `BENCHMARK_RUN_ID` are already set from session creation — do not re-export unless running this skill standalone. Use `create-window` → `execute-command` → `get-command-result` per the harness in `benchmark-run-all`.

## Prerequisites

- `cpu-burner` deployment is running in namespace `benchmark`
- VPA operator is installed (the script installs it if missing)
- Workload has been running for at least 5–10 minutes (VPA needs history)

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

## Pre-flight

```bash
export KUBECONFIG="$PWD/tmp/kubeconfig.$CLUSTER_NAME.yaml"
oc whoami
```

## Run

```bash
python3 scripts/run-test-07-vpa-advise.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --timeout 900
```

The script:
1. Verifies / installs VPA operator
2. Applies `manifests/workloads/cpu-burner.yaml` and `manifests/autoscaling/vpa.yaml` (idempotent)
3. Waits for VPA `status.recommendation.containerRecommendations` to be populated
4. Reads current resource requests from the deployment
5. Compares requests to VPA lower/target/upper bounds
6. Reads VPA events (OOMKill, eviction history)
7. Prints structured JSON summary with full comparison

Expected runtime: **5–15 minutes** (depends on how long the workload has been running).

## Recovery

```bash
python3 scripts/run-test-07-vpa-advise.py \
  --cluster-name "$CLUSTER_NAME" \
  --cluster-type "$CLUSTER_TYPE" \
  --run-id "$RUN_ID" \
  --timeout 900
```

If recommendations do not appear: ensure cpu-burner has been Running under load for at least 10 minutes. Check `oc get vpa cpu-burner-vpa -n benchmark -o yaml` for `status.conditions`.

## Report (Cursor Canvas)

**Resource Comparison Table**:

| Container | Current CPU | VPA Lower | VPA Target | VPA Upper | Current Memory | VPA Lower | VPA Target | VPA Upper |
|-----------|-------------|-----------|------------|-----------|----------------|-----------|------------|-----------|

**Key insights**:
- Over-provisioned: current > VPA upper (wasting resources / inflating CAS headroom calculations)
- Under-provisioned: current < VPA lower (risk of throttle or OOMKill)
- VPA target: what the deployment could be right-sized to

**Narrative — When to use VPA vs HPA**:
- Use HPA to scale out replicas for stateless services under variable load
- Use VPA (Off mode) to right-size pod requests for predictable workloads
- Running HPA and VPA together on CPU: safe only in VPA `Off` mode — both `Auto` and `Recreate` modes conflict with HPA

## Notes on VPA + HPA Compatibility

VPA in `Off` mode is safe alongside HPA — it collects data and provides advice
but never modifies running pods. If VPA were in `Auto` or `Recreate` mode, it
would conflict with HPA on CPU metrics.

## Retrospective

After this test completes, append to `docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`.

```markdown
## Test 07 — VPA Advise

**Status:** completed / partial / failed

### Issues Encountered
- <List any problems and resolution status. If none, write: _None._>

### Key Insights
- <VPA target vs current resource requests (CPU and memory), whether the workload was over- or under-provisioned, any implications for HPA accuracy or bin-packing efficiency.>
```
