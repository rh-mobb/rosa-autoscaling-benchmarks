---
name: benchmark-cluster-install
description: >-
  Benchmark ROSA cluster installation time across Classic (rosa CLI via
  make create-classic) and HCP (Terraform via make create-hcp). Records
  cumulative milestones: OCM ready, oc login, default machine pools (workers),
  ClusterOperators Available; writes HTML under reports/ (Terraform timings optional).
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill’s close-out plus **suite HTML** under **`reports/`**). Do not end after intermediate **`make`**, **`rosa`**, or **`oc`** steps unless the user explicitly accepts no report. If blocked or partial, still deliver the report or Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Cluster Install (Test 01)

Measure time through **OCM ready → `oc login` → all default worker nodes Ready (pools) → all ClusterOperators Available** (test 01).

- **Classic:** `make create-classic` — **`rosa create cluster`** then phased **`oc`** checks in that order.
- **HCP:** `make create-hcp` — **Terraform apply** then the same **`oc`** milestone order (install clock starts at Terraform apply start in `create.sh`).

**Agents:** Confirm with the user before **`make create-classic`** / **`make create-hcp`** unless they gave a **direct command** to run this test — see **Invocation & confirmation** in **`benchmark-run-all`** and **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**. After teardown or recovery is **in scope** and approved, run skill-documented retries (**`make reconcile-hcp`**, HCP destroy **`NO_REFRESH`**) yourself — **do not** ask the user for Makefile or Terraform flags.

## Tooling gate (agents)

Before executing this test, verify required tools and integrations are available and healthy (`oc`, `rosa`, `terraform` for HCP, tmux MCP tools, and local `tmux`).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. The user may explicitly decline and allow reduced-mode execution; only then proceed without that dependency.

Do not silently work around missing prerequisites.

## Report file naming

Save each report under **`reports/`** using **`RUN_ID`** from the run (no extra filename timestamp — **`RUN_ID`** already begins with **`YYYYMMDDTHHMMSS`** from `record-event.py init`, so listings stay ordered by run start):

```text
<RUN_ID>-01-<classic|hcp>-cluster-install.html
```

Example: `20260506T153045-hcp-01-hcp-cluster-install.html`

```bash
REPORT="reports/${RUN_ID}-01-classic-cluster-install.html"   # or -01-hcp-
```

Set **Report generated** in the HTML body to when you wrote the file (extended ISO-8601 UTC is fine); it does **not** have to match the **`RUN_ID`** prefix.

## Mandatory close-out (do not skip)

If you invoked this skill for a create attempt (success **or** failure **or** recover-after-error), you **must** finish **Step 7** — **HTML report plus wrap-up** — **in the same session before ending your response.** Do not stop after only Terraform recovery, `rosa describe`, or “cluster looks healthy” unless Step 7 is already done.

- **Success path:** full timings from **`events.jsonl`** where present; HTML report saved under **`reports/`** (naming above); **`python3 scripts/update-reports-index.py`** (or **`make reports-index`**) run so **`reports/index.html`** stays current; checkpoint complete.
- **Partial path:** `emit_timing` rows are still written for **`hcp.terraform_apply`** / **`hcp.create_submitted`** when Terraform fails (wall time to failure). For **optional** analysis, **`hcp.ocm403_retry_sleep`** records **only** time spent in OCM **403** backoff sleeps (subtract from **`hcp.terraform_apply`** wall time if you need “apply minus flake waits”). **Classic:** copy **`reports/template-01-classic-cluster-install.html`** to **`reports/${RUN_ID}-01-classic-cluster-install.html`** and fill it. **HCP:** same section layout (summary stats, timeline from **`hcp.*`** labels, findings, narrative, timing reference); copy the Classic template and adapt labels/tables, or hand-author HTML following that structure until an HCP template exists. Still run **`scripts/update-reports-index.py`** after saving the HTML.

Only skip Step 7 when Step 0 determined test **01** is already **`completed`** for the requested **`RUN_ID`** and you are **only** surfacing prior results (still OK to open or regenerate the HTML report from **`events.jsonl`** if the user asks).

## Checkpoint & Resume

Every skill in this suite uses `scripts/checkpoint.py` to persist progress. If
a session is interrupted, re-invoke the skill and it will detect the existing
checkpoint and resume from the last completed milestone.

Before starting:
```bash
# Check whether a run is already in progress
python3 scripts/record-event.py ls

# If a run exists, find its run-id and check where it left off:
python3 scripts/checkpoint.py status --run-id <RUN_ID>

# Find the next incomplete test:
python3 scripts/checkpoint.py next --run-id <RUN_ID>
```

## Prerequisites

- `rosa whoami` succeeds (authenticated with OCM)
- `aws sts get-caller-identity` succeeds
- **`terraform` CLI** installed (required for **HCP**; `make setup` checks it)
- **Python 3.11+ required for harness scripts** (the project uses `datetime.UTC`, unavailable in older system Python like macOS 3.9)
- Prefer the repo virtual environment so `python3` resolves to a supported version:
  ```bash
  source .venv/bin/activate
  python3 -V   # expect 3.11+
  ```
- **`classic.env`** and **`hcp.env`** exist (`make init-env` copies from `*.env.example`). Set `ROSA_CLUSTER_NAME_*` there if you change cluster names.
- **HCP:** **`clusters/hcp/create.sh`** runs **`clusters/hcp/terraform`**. Recovery without a second full create: **`make reconcile-hcp`**. Teardown when requested: **`benchmark-run-all`** → **Agents — HCP destroy** (hands-off **`make destroy-hcp`**, then **`ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH=1`** on refresh failures). **`RHCS_TOKEN`** or **`rosa login`**. Optional **`ROSA_HCP_TERRAFORM_VAR_FILE`**. **`make destroy-hcp`** needs Terraform state at **`clusters/hcp/terraform/terraform.<name>.tfstate`**.
- Do not run two **`make create-classic`** (or two **`make create-hcp`**) concurrently; creation scripts mutex per topology. Classic + HCP in parallel is allowed (`make cluster-create-lock-status`).
- For a **greenfield** create, the target cluster name should **not** already exist in OCM; see **Step 2** if you are **recovering** a partial **HCP** apply on an existing cluster from the same **`RUN_ID`**.

## Inputs

Ask the user (or infer from context):
- `CLUSTER_TYPE`: `classic`, `hcp`, or `both`
- `RUN_ID`: existing run ID to resume (leave blank to start fresh)

## Procedure

### Step 0 — Resolve run ID

If `RUN_ID` is provided, verify it exists:
```bash
python3 scripts/record-event.py ls
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 01-cluster-install
```
If status is `completed`, report results from the existing run and skip execution.
If blank, the create script will generate a new run ID via `init_run`.

### Step 1 — Mark test in-progress

**`init_run`** in **`clusters/common.sh`** (called from both create scripts) runs **`checkpoint init`** and, unless test **01** is already **`completed`**, **`checkpoint start`** for **`01-cluster-install`**. You only need the manual command below if you are **not** going through **`init_run`**:

```bash
python3 scripts/checkpoint.py start --run-id "$RUN_ID" --test 01-cluster-install
```

### Step 2 — Verify cluster existence

```bash
rosa describe cluster -c "$CLUSTER_NAME" -o json 2>&1
```

- **Fresh install (default):** If the cluster **already exists**, report state and **stop** with instructions to run **`make destroy-<type>`** first (unless the user explicitly chose to reuse an existing cluster for a different workflow).
- **HCP recover same run:** If **`make create-hcp`** failed after **`init_run`** but OCM now shows the cluster (partial Terraform apply), **do not** treat Step 2 as a hard stop for teardown. Use **`results/<run-id>/`** from the logs, run **`make reconcile-hcp`** (or the equivalent **`clusters/hcp/reconcile.sh`** with the same **`hcp.env`** as **`create-hcp`**), verify nodes and ClusterOperators, then go **straight to Step 7** with persisted + inferred timings documented.

### Step 3 — Invoke the create script (inside tmux)

#### Long jobs — Cursor Shell vs tmux / `nohup`

**Do not** rely on the **Cursor integrated Shell** tool to hold **`make create-classic`**, **`make create-hcp`**, or **`clusters/classic/resume-install-wait.sh`** open for **tens of minutes** as a single blocking invocation. When the agent tool hits its wait limit it may **background** the terminal; that often ends the shell **process group** with **SIGTERM** (**`make: *** [target] Error 143`**). The create can stop after **`rosa create cluster`** returns but **before** **`emit_timing`** / **`events.jsonl`** updates — or mid **post-submit** work — and **without operator IAM roles**, leaving OCM in **`waiting`** (*Operator Role(s) not found*).

| Approach | When to use |
|----------|-------------|
| **Tmux MCP** (preferred) | Always for test **01** installs when tmux tools are available — see **Session + window setup** below and **`benchmark-run-all`** → *Tmux session harness*. |
| **`nohup` + log + poll** | Use only when the user explicitly declines fixing tmux MCP / local tmux and approves reduced mode; otherwise pause and request tool setup first. |

#### Blocking babysit loop (user-requested or standing preference)

When the user asks for **blocking babysit**, **poll until complete**, **stay on the install**, or states that this is how they want cluster creates monitored:

- Keep **`make create-classic`** / **`make create-hcp`** / **`resume-install-wait.sh`** in **tmux** (do **not** hand back after “create submitted”).
- After **`execute-command`**, run a **tight poll loop in the same agent turn**: every **60–90 s**, call **`get-command-result(commandId)`** (when markers still work) **and** **`capture-pane`** (`start=-50`) **and**, when useful, **`rosa describe cluster`** / **`make cluster-create-lock-status`** until:
  - **`get-command-result`** returns **`completed`** or **`failed`**, **or**
  - **`capture-pane`** shows a **`TMUX_MCP_DONE_<uuid>_<exit>`** line for the wrapped command (`_0` = success).
- After **each** poll, post the one-line **`⏳ [<elapsed>] <cluster> — <state> (<last log line>)`** update (same format as Step 5 below).
- **Do not** end the assistant turn early with only “install is running” unless the platform truncates the session — then tell the user how to resume (**tmux pane**, **`results/<RUN_ID>/raw/install.log`**, **`rosa describe cluster`**).
- **Trade-off:** Cursor may show the agent as **busy** until the loop exits; that is intentional for this mode.

If **`get-command-result`** returns **`tracking expired`** / **`markers not found`** mid-run, fall back to **`capture-pane`** + **`rosa describe`** only — still poll every **60–90 s** until **`TMUX_MCP_DONE_*`** appears or failure is obvious.

**Classic resume** ( **`resume-install-wait.sh`** ): same rules — **tmux** `execute-command` **or** **`nohup`**. The script requires **`BENCHMARK_RUN_ID`**, **`ROSA_CLUSTER_NAME`**, **`CLUSTER_ADMIN_PASSWORD`**, and an **`events.jsonl`** line for **`classic.create_submitted`** (seed with **`record-event.py record`** if **`make create-classic`** died before **`emit_timing`**).

**`tee`:** If **`make`** is piped to **`tee`**, use **`set -o pipefail`** and wait on **`make`**’s exit (or **`PIPESTATUS`**) inside the **same** detached process (tmux pane or **`nohup bash -c '…'`**), not in Cursor Shell for multi-hour runs.

#### Session + window setup (tmux — preferred)

Run the create script in the **`01-create` window** of the cluster's benchmark session (see **Tmux session harness** in `benchmark-run-all`). If this is the first test in the run, create the session first.

**Session + window setup:**

1. `find-session` (name=`benchmark-<classic|hcp>`, socket=`benchmark-<RUN_ID>`) — create the session if absent.
2. In the session's default pane, set env (once, skip if resuming):

```bash
cd /path/to/repo
source .venv/bin/activate
export RHCS_TOKEN="$(rosa token)"
export KUBECONFIG="$PWD/tmp/kubeconfig.<CLUSTER_NAME>.yaml"
export BENCHMARK_RUN_ID="<RUN_ID>"
```

3. `create-window` (sessionId=…, name=`01-create`) → save `paneId`.
4. `execute-command` (paneId=…, command=`make create-classic` or `make create-hcp`) → save `commandId`.
5. **Poll loop:** every **60–90 s**, same cadence whether or not the user asked for **blocking babysit** — if they did, treat this as **mandatory continuous polling until terminal state** (see **Blocking babysit loop** above). Call `get-command-result(commandId)`; while `status=pending`, call `capture-pane` (last 50 lines) to read live output. After each poll, **post a one-line status update to the user** in this format:
   ```
   ⏳ [<elapsed>] classic-bench — <current state> (<last log line>)
   ```
   For example: `⏳ [32m] classic-bench — installing (waiting...)`
   This keeps the user informed without requiring them to ask. Continue polling until **`get-command-result`** is **`completed`** or **`failed`**, or until **`capture-pane`** shows **`TMUX_MCP_DONE_*`** (see **Blocking babysit loop** if tracking expires).
6. Read `exitCode`: `0` = success; non-zero = failure; apply the recovery paths below.

**`nohup` fallback** (same repo root, when tmux is not used):

```bash
# Classic — after sourcing env, detach and capture PID + log path for polling
set -a && source classic.env && set +a && \
nohup env ROSA_CLUSTER_NAME="$ROSA_CLUSTER_NAME_CLASSIC" \
  CLUSTER_ADMIN_PASSWORD="$CLUSTER_ADMIN_PASSWORD" \
  AWS_REGION="$AWS_REGION" ROSA_VERSION="$ROSA_VERSION" \
  CLUSTER_TYPE=classic PATH="$PWD/.venv/bin:$PATH" HOME="$HOME" \
  make create-classic >> /tmp/benchmark-01-classic-create.log 2>&1 &
echo "PID=$!  log=/tmp/benchmark-01-classic-create.log"

# HCP — export RHCS_TOKEN if rosa token will not work inside nohup
set -a && source hcp.env && set +a && export RHCS_TOKEN="${RHCS_TOKEN:-$(rosa token)}" && \
nohup env ROSA_CLUSTER_NAME="$ROSA_CLUSTER_NAME_HCP" AWS_REGION="$AWS_REGION" \
  ROSA_VERSION="$ROSA_VERSION" RHCS_TOKEN="$RHCS_TOKEN" CLUSTER_TYPE=hcp \
  PATH="$PWD/.venv/bin:$PATH" HOME="$HOME" \
  make create-hcp >> /tmp/benchmark-01-hcp-create.log 2>&1 &
echo "PID=$!  log=/tmp/benchmark-01-hcp-create.log"

# Classic resume (cluster already in OCM; events.jsonl has classic.create_submitted)
set -a && source classic.env && set +a && \
nohup env ROSA_CLUSTER_NAME="$ROSA_CLUSTER_NAME_CLASSIC" \
  CLUSTER_ADMIN_PASSWORD="$CLUSTER_ADMIN_PASSWORD" \
  BENCHMARK_RUN_ID="<RUN_ID>" AWS_REGION="$AWS_REGION" CLUSTER_TYPE=classic \
  PATH="$PWD/.venv/bin:$PATH" HOME="$HOME" \
  bash clusters/classic/resume-install-wait.sh >> /tmp/benchmark-01-classic-resume.log 2>&1 &
echo "PID=$!  log=/tmp/benchmark-01-classic-resume.log"
```

**For Classic**, `make create-classic` uses **`rosa create cluster`** (`clusters/classic/create.sh`) and emits **`classic.create_submitted`**, **`classic.cluster_ready`**, **`classic.operators_ready`**, **`classic.total`**.

**For HCP**, `make create-hcp` runs Terraform via `clusters/hcp/create.sh` using a **single-shot** apply; recorded labels include **`hcp.terraform_init`**, **`hcp.ocm403_retry_sleep`** when OCM **403** retries slept (backoff-only; omit if zero), **`hcp.terraform_apply`**, **`hcp.create_submitted`**, **`hcp.cluster_ready`**, **`hcp.operators_ready`**, **`hcp.total`**. **`make reconcile-hcp`** is a **full** Terraform apply for recovery (does not start a new benchmark run or **`init_run`**). **`make destroy-hcp`** is **`terraform destroy`** only (needs local Terraform state).

Run reconcile / retry commands in the **same `01-create` window** pane so logs are co-located with the original create output.

**HCP OCM `CLUSTERS-MGMT-403` (Forbidden)** — the harness uses a single-shot `terraform apply` matching the upstream reference implementation. Transient 403s are caught by the retry loop in **`clusters/hcp/lib-terraform.sh`** (tune with **`ROSA_HCP_TERRAFORM_403_MAX_RETRIES`**, default **12**, and **`ROSA_HCP_TERRAFORM_403_RETRY_SLEEP_SEC`**, default **120**). **`hcp.ocm403_retry_sleep`** in **`events.jsonl`** isolates time spent in backoffs so **`hcp.terraform_apply`** can be read with or without flake waits. The root cause (upstream module not passing `autoscaling_enabled` to `rhcs_cluster_rosa_hcp` at create time) is tracked in a separate upstream bug.

**Agents:** If **`make create-hcp`** still fails after scripted retries, run **`make reconcile-hcp`** before hand-Terraform — same modules, state file, and var-file generation.

**Agents:** When wrapping **`make create-hcp`** with **`tee`**, use **`set -o pipefail`** and wait on **`make`**, or use **`PIPESTATUS`**, so failures are visible (see **`benchmark-run-all`**).

**Agents:** HCP teardown edge cases (**refresh** failures after partial destroy; **`RHCS_TOKEN`** / detached shells) → **`rosa-cli`** → **Agents: HCP Terraform destroy — auth, interruptions, refresh failures**.

**Agents:** HCP **`terraform apply`** failures — classify error; for **403**, rely on **in-script retries** first, then **`make reconcile-hcp`**.

**After any HCP apply failure:** Capture **`Benchmark run ID:`** from the script log (or newest **`results/*/metadata.json`** for **`cluster_name`**). After reconcile, run **`python3 scripts/record-event.py summary --run-id "$RUN_ID"`** so you know what landed in **`events.jsonl`**. Optionally append manual milestones with **`record-event.py record`** (labels such as **`hcp.manual_terraform_apply_reconcile`**) so the JSONL reflects recovery — still deliver Step 7 HTML report even if you skip optional **`record`** calls.

The script calls `init_run`, which:
- Creates `results/<run-id>/` directory
- Writes `results/<run-id>/metadata.json`
- Initialises `results/<run-id>/checkpoint.json`
- Starts **`01-cluster-install`** in **`checkpoint.json`** when not already **`completed`**
- Exports `$BENCHMARK_RUN_ID`

Every `emit_timing` call then appends to `results/<run-id>/events.jsonl`.
You can watch events accumulate in real time:
```bash
tail -f results/<run-id>/events.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    print(f\"{e['label']:<45} {e['elapsed_human']:>10}  {e['iso']}\")
"
```

### Step 4 — Poll cluster state via `oc`

While the script is running (or after it completes), optionally cross-check state with **`oc`** (use the same **`KUBECONFIG`** as the create script: **`tmp/kubeconfig.<cluster-name>.yaml`** under the repo after login).

**ClusterOperators:**

```bash
oc get clusteroperators.config.openshift.io -o wide
# or wait (already done in create.sh):
oc wait clusteroperators --all --for=condition=Available=True --timeout=5m
```

For deeper inspection, **`oc get clusteroperator <name> -o yaml`** and check **`status.conditions`** for **`Available=True`** and **`Degraded=False`**.

Record the timestamp when **all** operators first report Available=True (if you are adding an agent-only milestone).
Append this as an agent-recorded event (portable end timestamp; avoid **`date +%s%3N`** on macOS):
```bash
END_MS="$(python3 -c 'import time; print(int(time.time() * 1000))')"
python3 scripts/record-event.py record \
  --run-id "$RUN_ID" --label "01.all_operators_available" \
  --start-ms "$T_CREATE_START" --end-ms "$END_MS" \
  --cluster-type "$CLUSTER_TYPE" --cluster-name "$CLUSTER_NAME"
```

### Step 5 — Collect machine events

Use **`oc get events`** in **`openshift-machine-api`** (newest last):

```bash
oc get events -n openshift-machine-api --sort-by=.lastTimestamp
```

Note provisioning warnings/errors for the report.

### Step 6 — Record timing milestones

Create scripts persist cumulative timings from **`T_START`** (benchmark start) in **`events.jsonl`**:

| Order | Milestone | Label (Classic) | Label (HCP) |
|-------|-----------|-----------------|---------------|
| 1 | OCM reports cluster **ready** | **`classic.cluster_ready`** | **`hcp.cluster_ready`** |
| 2 | **`oc login`** succeeds | **`classic.oc_login_ok`** · user **`cluster-admin`** | **`hcp.oc_login_ok`** · htpasswd user **`admin`** |
| 3 | All **worker** nodes **Ready** (default machine pools) | **`classic.machine_pools_ready`** (+ alias **`classic.workers_ready`**) | **`hcp.machine_pools_ready`** |
| 4 | All **ClusterOperators** **Available** | **`classic.operators_ready`** | **`hcp.operators_ready`** |
| 5 | Install script complete | **`classic.total`** | **`hcp.total`** |

Optional provisioning / HCP Terraform detail: **`classic.create_submitted`**; **`hcp.terraform_apply_phase1`**, **`hcp.terraform_post_cluster_pause`**, **`hcp.terraform_apply_phase2`** (phased path only); **`hcp.ocm403_retry_sleep`** (403 backoff only, if non-zero); **`hcp.terraform_*`**, **`hcp.create_submitted`**; after failed create, manual **`record-event`** labels such as **`hcp.manual_terraform_apply_reconcile`** if you reconcile outside **`make reconcile-hcp`**.

### Step 7 — HTML report first, then checkpoint

**Order:** Write **`reports/<RUN_ID>-01-<classic|hcp>-cluster-install.html`** (see **Report file naming**), then **refresh the reports dashboard** (summary table + trend chart + links to every HTML file):

```bash
python3 scripts/update-reports-index.py
# or: make reports-index
```

Then update checkpoint.

**Report layout:** The reader should see the **four outcome phases** in order: **OCM ready → oc login → machine pools (workers) → operators**, plus **phase durations** (differences between consecutive milestones) and **`*.total`**. Copy **`reports/template-01-classic-cluster-install.html`** and swap **`classic.*`** for **`hcp.*`** where needed.

**De-emphasize** Terraform / early submit rows: optional **“Provisioning internals”** subsection or bottom of timeline.

**Classic:** fill from **`events.jsonl`** + **`metadata.json`**; compute segment durations from **`elapsed_ms`** or **`end_ms − previous end_ms`**.

**HCP:** same structure (**`hcp.cluster_ready`** … **`hcp.operators_ready`**).

Do **not** use a Cursor **`.canvas.tsx`** for this test — **`reports/`** HTML is authoritative.

**Checkpoint:**

```bash
python3 scripts/checkpoint.py complete --run-id "$RUN_ID" --test 01-cluster-install
```

Use **`complete`** only when the cluster is **operationally usable** for test 02 (API up, workers **Ready**, ClusterOperators healthy). If the create failed and was **not** reconciled, leave **`01-cluster-install`** **`in_progress`** or **`pending`** per **`checkpoint.py`** semantics — **but still ship the HTML report** explaining failure and next steps.

## Timing Reference (Expected Ranges)

| Segment | ROSA Classic | ROSA HCP |
|---------|-------------|----------|
| Start → OCM **ready** | (bulk of create) | (bulk of create) |
| OCM ready → **`oc login`** | ~2–10 min | ~2–10 min |
| Login → all **workers** Ready (default pools) | ~5–15 min | ~5–15 min |
| Pools → all **operators** Available | ~5–15 min | ~2–10 min |
| **Total (typical)** | **45–65 min** | **15–25 min** |

Flag anomalies if any phase exceeds 1.5× the expected range.

**When the user orders HCP cluster deletion** (or teardown is explicitly in scope): follow **hands-off** **`benchmark-run-all`** → **Agents — HCP destroy**: pipe **`ROSA_CLUSTER_NAME_HCP`** into **`make destroy-hcp`** first; **if** that fails with **refresh** / **`cluster_default`** / **Invalid index** symptoms, **immediately** retry with **`ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH=1`** — **do not** ask the user to supply flags. Run destroy in the **`destroy` window** of the cluster's benchmark session (see **Tmux session harness** in `benchmark-run-all`); call `kill-session` after confirmed teardown and final report are both complete.

## Retrospective

After this test completes, write the retrospective entry for this run.

**File:** `docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`
(e.g. `docs/retrospectives/20260511T041449-classic.md`)

If the file does **not** exist yet, create it with this header first:

```markdown
# Benchmark Retrospective — <RUN_ID>

**Cluster type:** <classic|hcp>  
**Date:** <YYYY-MM-DD>  
**Tests run:** (fill in as tests complete)

<!-- SUMMARY_PLACEHOLDER -->

---
```

Then append this section:

```markdown
## Test 01 — Cluster Install

**Status:** completed / partial / failed  
**Total time:** <X>m <Y>s

### Issues Encountered
- <List any problems that came up and whether they were resolved. If none, write: _None._>

### Key Insights
- <Factual observations from this specific run — install duration vs expected range, any phase that was unusually fast/slow, anything noteworthy about the environment or cluster config.>
```

Keep content grounded in what actually happened in this run — not generic statements about the scenario.

## Cleanup (default — benchmark continuation)

Do not clean up the cluster — it is needed for subsequent benchmark skills.
Inform the user the cluster is ready for the next test (`benchmark-machine-pool`).
