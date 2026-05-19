---
name: benchmark-run-all
description: >-
  Run all ROSA autoscaling benchmark tests in sequence for Classic and/or HCP.
  HCP stacks live under clusters/hcp/terraform; Classic uses rosa CLI scripts. Collects timings, writes
  HTML comparison reports under reports/. Use for full-suite or Classic-vs-HCP reports.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** (**HTML** in **`reports/`** for test **01**; **Cursor Canvas** for tests **02–09**; **`benchmark-run-all`** requires each child skill’s close-out plus **suite HTML** under **`reports/`**). Do not end after intermediate **`make`**, **`rosa`**, or **`oc`** steps unless the user explicitly accepts no report. If blocked or partial, still deliver the report or Canvas with a clear narrative. See **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

# Benchmark: Run All Tests (Orchestrator)

Run the complete benchmark suite (tests 01–09) in sequence for one or both
cluster types. Collect timing results from each skill and render a final
comparison HTML report with all metrics side by side.

## Invocation & confirmation (for agents)

The **`benchmark-*`** skills in this workspace **may be invoked automatically** when the conversation is clearly about benchmarking, provisioning timing, tests **01–09**, or **`make create-*`** / **`make destroy-*`** for the harness.

**When to skip a confirmation ping**

The user issued a **direct run request**: they named the suite or script to execute (examples: "run **`benchmark-run-all`**", "execute **`benchmark-cluster-install`** for HCP", "start test 03", **`make create-hcp`** for this benchmark"). Proceed with prerequisites checks, then run.

**When to confirm once first**

The request is **indirect or exploratory**: planning, hypothetical, “we should benchmark”, vague “measure autoscaling”, or you must **infer** that they wanted a destructive/long **Terraform** / **`rosa`** / **`make`** run. Reply with a one-line summary of **what will run**, **Classic vs HCP**, and **risk** (time, quota, teardown), then **wait for approval** before starting cluster lifecycle, **`terraform apply`**, or the full **`benchmark-run-all`** chain.

Safe without prior confirmation: read-only gates (**`rosa whoami`**, **`make cluster-create-lock-status`**, **`python3 scripts/checkpoint.py status`**, **`record-event.py ls`**).

**Hands-off:** After the user has approved cluster lifecycle (create/destroy/suite), execute every scripted retry and env-driven flag the skills describe yourself (**HCP destroy** → **Agents — HCP destroy** below; **`make reconcile-hcp`** when **`benchmark-cluster-install`** calls for it; **`hcp.env`** defaults for apply/403). **Do not** offload flag knowledge to the user unless both destroy attempts fail and the skill points to **last-resort** manual **`terraform`**.

**`make` exit status (agents):** If you pipe **`make create-hcp`** / **`make create-classic`** to **`tee`**, use **`set -o pipefail`** and wait on **`make`** (or **`PIPESTATUS`**) so failure is not masked by **`tee`**’s exit 0.

**Integrated Shell vs long installs:** a **foreground** **`make create-*`** in the **Cursor Shell** tool is **not** safe for 45–90+ minute installs — tool time limits can **SIGTERM** the job (**Error 143**) and strand the cluster mid-STS (see **`benchmark-cluster-install`**). Use the **tmux** harness below (**`execute-command`** + **`get-command-result`**). If tmux MCP or local `tmux` is unavailable, **pause and ask the user to install/fix it first**; only use non-tmux fallback when the user explicitly declines and approves reduced mode.

**Completion:** A direct "run this benchmark" request includes **finishing** the relevant skill's **reporting step** (HTML for **01**, **Canvas** for **02–09**, suite HTML when **`benchmark-run-all`** is the scope). See the same rule file.

Related local rule: **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

## Tooling gate (agents)

Before running this suite, verify the required tools and integrations are available:

- tmux MCP tools (`find-session`, `create-session`, `create-window`, `execute-command`, `get-command-result`, `capture-pane`) and local `tmux` binary
- `oc` CLI
- `rosa` CLI
- skill-specific CLIs used by the selected topology (for example `terraform` for HCP lifecycle)
- Python 3.11+ for harness scripts (`datetime.UTC` is used by `record-event.py`; system Python 3.9 will fail)

If any required tool or integration is missing/unhealthy, **stop and ask the user to install or repair it first**. The user may explicitly decline and request reduced-mode execution; only then proceed without the missing dependency.

Do not silently work around missing prerequisites.

Prefer the repo virtual environment before any benchmark command:

```bash
source .venv/bin/activate
python3 -V   # expect 3.11+
```

## Inputs

Ask the user before starting:
- `CLUSTER_TYPE`: `classic`, `hcp`, or `both`
- `RUN_ID`: an existing run to resume (blank = start fresh)
- Whether to skip bare-metal (test 02) — it takes 20–40 min and may not be needed
- Whether to run tests in sequence on a single cluster or alternate between clusters

## Cluster provisioning (this repository)

For **test 01** (`benchmark-cluster-install`) or whenever the user asks to **create** or **destroy** the **HCP** benchmark cluster, follow this harness — **do not** script **`rosa create cluster --hosted-cp`**, **`rosa delete cluster`**, or **`rosa create network`** for HCP **lifecycle** (those paths are not in this repo).

| Topology | Install | Teardown |
|----------|---------|----------|
| **Classic** | `make create-classic` → `clusters/classic/create.sh` | `make destroy-classic` (**`destroy.sh`**: cluster uninstall + **`rosa delete operator-roles`** + **`rosa delete oidc-provider`**) |
| **HCP** | `make create-hcp` → **`clusters/hcp/create.sh`** (**Terraform only** under **`clusters/hcp/terraform/`**) · **`make reconcile-hcp`** → full apply only (recovery) | `make destroy-hcp` → **`terraform destroy`** (needs **`clusters/hcp/terraform/terraform.<cluster>.tfstate`**) |

**HCP auth for Terraform:** **`RHCS_TOKEN`** or **`rosa login`** (create.sh uses **`rosa token`** when unset). After the cluster exists, day-2 **`rosa`** / **`oc`** usage is normal — see **`rosa-cli`** skill.

**Agents — HCP destroy (hands-off — do not ask the user for Terraform flags):** From the **repository root**, ensure **`RHCS_TOKEN`** is available or **`rosa token`** works in the same shell (detached **`nohup`** jobs must **export `RHCS_TOKEN`** — **`rosa token`** often fails there).

1. Resolve the cluster name the same way **`make`** does (Makefile **`include hcp.env`** when present): **`ROSA_CLUSTER_NAME_HCP`** (e.g. **`source hcp.env`** in **`bash`** or read **`hcp.env`**).
2. Run destroy with the Makefile confirmation satisfied **without human typing**:
   ```bash
   printf '%s\n' "${ROSA_CLUSTER_NAME_HCP}" | make destroy-hcp
   ```
3. If that exits **non-zero** and the log mentions **refresh**, **`data.aws_security_groups.cluster_default`**, **empty** **`ids`**, or **Invalid index** (common after a **partial or interrupted** destroy), **retry once immediately** — **do not** stop to ask whether to use **`-refresh=false`**:
   ```bash
   printf '%s\n' "${ROSA_CLUSTER_NAME_HCP}" | make destroy-hcp ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH=1
   ```
   The **`Makefile`** forwards **`ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH`** to **`destroy.sh`** → **`terraform destroy -refresh=false`** (see **`clusters/hcp/lib-terraform.sh`**).
4. Size **`block_until_ms`** generously (**often 15–45+ minutes**); **avoid SIGTERM** mid-destroy.

If **both** steps fail, fall back to **`rosa-cli`** → manual **`terraform`** from **`clusters/hcp/terraform`** (same backend + **`-var-file`**) as **last resort**.

**Agents — HCP create:** **`create.sh`** retries **`terraform apply`** on OCM **403** and records **`hcp.ocm403_retry_sleep`** when backoffs run. If apply still fails, use **`make reconcile-hcp`** (same state + var-file path as create). See **`clusters/hcp/lib-terraform.sh`** and **`benchmark-cluster-install`**.

## Tmux session harness

All benchmark commands — create, every test (01–09), and destroy — run inside a **persistent tmux session** so they survive IDE restarts and Cursor session recycling. The tmux MCP tools (`create-session`, `create-window`, `execute-command`, `get-command-result`, `capture-pane`, `find-session`, `kill-session`) are used for every long-running operation; the Cursor Shell tool is reserved for short reads and pre-flight checks.

### Session topology

| Resource | Convention |
|----------|-----------|
| Socket | `benchmark-<RUN_ID>` — pass as `socket` to **every** tmux MCP call so all tools target the same isolated server |
| Session per cluster type | `benchmark-classic` · `benchmark-hcp` · `benchmark-hcp-autonode` |
| Window per test / phase | `01-create` · `02-machine-pool` · `03-autoscale-up` · `04-autoscale-down` · `05-unschedulable` · `06-hpa` · `07-vpa-advise` · `08-hpa-cas` · `09-overprovisioning` · `destroy` |

### Session creation (once per cluster type, at run start)

1. Call `find-session` (name=`benchmark-<classic|hcp>`, socket=`benchmark-<RUN_ID>`) — if a session exists this is a resume; skip to **Resuming** below.
2. Call `create-session` (name=`benchmark-classic` or `benchmark-hcp`).
3. In the **default pane** of the new session, set persistent env with `execute-command`. Use `sh -lc '...'` to load the login shell profile:

```bash
cd /path/to/repo
source .venv/bin/activate
export RHCS_TOKEN="$(rosa token)"
export KUBECONFIG="$PWD/tmp/kubeconfig.<CLUSTER_NAME>.yaml"
export BENCHMARK_RUN_ID="<RUN_ID>"
```

Every window opened in this session inherits these variables — `oc` commands work without re-exporting KUBECONFIG, and Terraform picks up `RHCS_TOKEN` automatically.

### Running commands in a window

For each test or lifecycle phase:

1. Call `create-window` (sessionId=…, name=`<window-name>`) → save the returned `paneId`.
2. Call `execute-command` (paneId=…, command=`make create-classic …`) → save `commandId` (initial status: `pending`).
3. **Poll for progress:** for operations expected to take > 5 min (test 01, machine pool bare-metal, destroy), poll every **60–90 s** in a **continuous loop until terminal state** — see **`benchmark-cluster-install`** → **Blocking babysit loop** when the user wants **blocking babysit** / **poll until complete**. Each iteration:
   - Call `get-command-result(commandId)` — if `status` is still `pending`, call `capture-pane` (last 50 lines, `start=-50`) to read live output and log progress to the user.
   - If **`get-command-result`** loses tracking, use **`capture-pane`** + **`rosa describe cluster`** / **`make cluster-create-lock-status`** until **`TMUX_MCP_DONE_*`** appears or failure is clear (**`benchmark-cluster-install`**).
   - Continue until `status` is `completed` or `failed`, or pane shows **`TMUX_MCP_DONE_*`**.
4. Read `exitCode` from the final `get-command-result`. Non-zero = failure; apply the skill-specific error-handling path (reconcile, NO_REFRESH retry, etc.).

For operations that finish in < 5 min (most `oc apply` / `oc wait` steps in tests 02–09), call `execute-command` and a single `get-command-result` after an `Await` of the expected duration.

### Running Classic + HCP in parallel

When `CLUSTER_TYPE=both`, create **two sessions** on the same socket. Run their `01-create` windows concurrently — the agent can issue both `execute-command` calls, then poll both `commandId` values interleaved. All subsequent test windows in each session also run independently; synchronise only for the final HTML report step.

### Resuming an interrupted run

```bash
# 1. Check for an existing session
find-session: name="benchmark-<type>", socket="benchmark-<RUN_ID>"

# 2. List its windows to see which tests already ran
list-windows: sessionId=<found-session-id>

# 3. Check checkpoint state
python3 scripts/checkpoint.py status --run-id "$RUN_ID"
```

Re-use the existing session and its env. If a window for the current test exists and its `execute-command` already completed (verify with `capture-pane` for an exit marker), advance to the next test.

### Destroy phase

Run `make destroy-classic` / `make destroy-hcp` in a window named `destroy` inside the **same session**. Apply the hands-off retry rules from **Agents — HCP destroy** above. After confirmed teardown, call `kill-session` to clean up. Do **not** kill the session before the final HTML report is written.

## Resume from Interrupted Run

If the user provides a `RUN_ID` (or one is found via `python3 scripts/record-event.py ls`):

```bash
# Show what has already been completed:
python3 scripts/checkpoint.py status --run-id "$RUN_ID"

# Find the next test to run:
NEXT=$(python3 scripts/checkpoint.py next --run-id "$RUN_ID")
echo "Resuming from: $NEXT"
```

Skip any test whose checkpoint status is `completed` or `skipped`.
Load timing results for already-completed tests from `events.jsonl`:

```bash
python3 scripts/record-event.py summary --run-id "$RUN_ID"
```

Include completed-test results in the final HTML report even when resuming — they are
already persisted and fully readable from the JSONL file.

## Execution Order

Run skills in this order. For `both` cluster types, run each test on Classic
first, then HCP, before moving to the next test.

| # | Skill | Prerequisite | Approx duration |
|---|-------|-------------|-----------------|
| 01 | `benchmark-cluster-install` | No cluster yet for the chosen type(s); **HCP** → Terraform apply | 15–65 min |
| 02 | `benchmark-machine-pool` | Clusters ready | 10–60 min (bare-metal adds ~35 min) |
| 03 | `benchmark-autoscale-up` | Machine pools ready | 10–20 min |
| 04 | `benchmark-autoscale-down` | Test 03 complete | 15–25 min |
| 05 | `benchmark-unschedulable` | Cluster running | 5 min |
| 06 | `benchmark-hpa` | Cluster running | 15–25 min |
| 07 | `benchmark-vpa-advise` | Test 06 running | 5–10 min |
| 08 | `benchmark-hpa-triggers-cas` | Tests 06, 03 complete | 15–25 min |
| 09 | `benchmark-overprovisioning` | Test 08 complete | 15–25 min |

For test **09**, use the **`benchmark-overprovisioning`** skill’s **default saturated** command (see that skill’s **Run (default — saturated pool baseline)** section — includes `--saturated-pool-baseline` and ROSA pool bounds for Classic/HCP). Do not fall back to the legacy one-liner unless you are intentionally reproducing older pause-first behavior.

For test **01**, agents must follow **`benchmark-cluster-install`** **Mandatory close-out**: deliver the **HTML report** under **`reports/`** (**`RUN_ID`**-based naming in that skill), before ending the turn — including **HCP** partial-apply recovery paths.

For tests **02–09**, follow each skill’s **mandatory close-out** (typically **Canvas** with timings and narrative, plus **`checkpoint.py` / `record-event.py`** when **`RUN_ID`** is set). Do **not** advance to the next test or end the session on a “benchmark …” ask until that test’s deliverable is satisfied or explicitly failed with a documented partial report.

Estimated total: **90–180 minutes** for one cluster type (without bare-metal).

## Per-Test Result Collection

Results are persisted to disk as they happen — the in-session dictionary is just
a cache for the final HTML comparison report. After each skill completes:

1. The skill marks the checkpoint: `python3 scripts/checkpoint.py complete --run-id "$RUN_ID" --test <id>`
2. Key timing events are appended to `results/<run-id>/events.jsonl`
3. Load the full run summary at any point: `python3 scripts/record-event.py summary --run-id "$RUN_ID"`

In-session cache (for HTML report authoring):

```
results[test_id][cluster_type] = {
  "test": "01-cluster-install",
  "cluster_type": "classic",
  "milestones": { ... },   # loaded from events.jsonl if resuming
  "total_elapsed_ms": 2700000,
  "events_summary": [ ... ],
  "anomalies": [ ... ]
}
```

Carry this dictionary through the run; populate it from `events.jsonl` when resuming.

## Progress Reporting

After each test completes, print a brief status line:
```
✓ Test 01 (cluster-install) — classic: 52m14s | hcp: 18m42s
✓ Test 02 (machine-pool)    — classic: standard 6m | memory 7m | compute 5m | bare-metal 28m
...
```

If a test fails or is skipped, note it and continue with the next.

## Final HTML comparison report

After all tests complete, write a comparative HTML document under **`reports/`** using the same **`RUN_ID`**-based naming as **`benchmark-cluster-install`**. For a suite-wide file use e.g. **`<RUN_ID>-suite-01-through-09.html`** (suite **`RUN_ID`** from that benchmark run).

Immediately afterward, regenerate the browsable index (latest-run summary, historical links, and install-time trend chart):

```bash
python3 scripts/update-reports-index.py
# or: make reports-index
```

### Report structure

**Section 1 — Summary Stats**

Classic vs HCP columns for:

- Cluster install time
- Machine pool provisioning (average, excluding bare-metal)
- Cluster autoscale-up time
- Cluster autoscale-down time
- HPA response time (CPU breach → pods running)
- HPA + CAS e2e time (test 08)
- Overprovisioning savings (test 08 time − test 09 time)

**Section 2 — Detailed Timing Table**

Full table with one row per test per cluster type:

| Test | Scenario | Classic | HCP | Delta |
|------|----------|---------|-----|-------|
| 01 | Cluster install (total) | Xm Ys | Xm Ys | ±Xm |
| 02 | m5.xlarge provision | ... | ... | ... |
| 02 | m5.metal provision | ... | ... | ... |
| 03 | CAS scale-up | ... | ... | ... |
| 04 | CAS scale-down | ... | ... | ... |
| 06 | HPA response | ... | ... | ... |
| 08 | HPA+CAS e2e | ... | ... | ... |
| 09 | Overprov. HPA | ... | ... | ... |

**Section 3 — Key Findings**

Narrative bullets:
- Which cluster type provisioned faster and by how much
- Which autoscaling scenario showed the biggest difference between Classic and HCP
- Whether HPC control plane speed affected CAS decisions
- Overprovisioning ROI: how many minutes saved per HPA event × expected event frequency

**Section 4 — Events Highlights**

Any anomalies, warnings, or interesting events from across all tests.

**Section 5 — Recommendations**

Based on the results, recommend:
- Cluster type preference for workloads with frequent autoscaling
- Whether overprovisioning is cost-justified for the observed workload pattern
- VPA target values from test 07 that could improve resource efficiency

## Error Handling

If any test fails:
- Record the failure with error details
- Continue to the next test
- In the final HTML report, mark the failed test row with emphasis or a warning-style note
- Include the error message in the events highlights section

## Retrospective — Finalize

Once all tests are done and the suite HTML is written, finalize the retrospective file at
`docs/retrospectives/<RUN_ID>-<CLUSTER_TYPE>.md`.

Replace the `<!-- SUMMARY_PLACEHOLDER -->` line with:

```markdown
## Run Summary

**Run ID:** <RUN_ID>  
**Cluster type:** <classic|hcp>  
**Date:** <YYYY-MM-DD>  
**Tests completed:** <N>/9 (or N/total)

### Headline Numbers
- <3–5 key timing results that best characterise this run>

### Top Issues
- <Cross-test problems worth remembering for future runs — include whether they were resolved and whether a fix was made to the harness>

### Top Insights
- <The 3–5 most important findings from the full run — things that would change how someone designs or operates this cluster type>

---
```

The summary goes at the top (replacing the placeholder) so the file reads: summary first, then test-by-test detail below.

## Cleanup

After the run completes (and the user confirms), offer to:
1. Remove all benchmark workloads from clusters (`benchmark` namespace)
2. Optionally run **`make destroy-classic`** and/or **`make destroy-hcp`** (HCP teardown is **Terraform only** — requires state under **`clusters/hcp/terraform/`**)

Do NOT destroy clusters automatically — always confirm with the user first.
