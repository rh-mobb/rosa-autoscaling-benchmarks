# Skill: Analyze Raw Telemetry

## Tooling gate (agents)

Before running this skill, verify required tools are available (`python3` and repository scripts used by this workflow).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

## Purpose

Extract fine-grained provisioning timelines from raw telemetry files that the
scripted collectors (`collect-install-log-milestones.py`,
`collect-ec2-pool-telemetry.py`) could not parse deterministically. Emit the
results as `record-event.py record` shell commands so the user can merge them
into `events.jsonl` with a single paste.

This skill is the iteration environment for LLM prompts. Once the prompts are
stable across several real runs, they become the spec for
`scripts/analyze-raw-telemetry.py`.

## When to invoke

- After a cluster install or machine pool run has completed and
  `results/<run-id>/raw/` contains `install.log` and/or `console-*.txt`.
- When you want deeper sub-milestones than the scripted collectors captured
  (e.g. exact ignition fetch latency, unexpected boot delays, install failures).
- When diagnosing a slow or failed install and need a narrative summary.

---

## Step 1 — Locate the run

Ask for `RUN_ID`, or if omitted, read `results/` and pick the most recent run:

```bash
ls -t results/ | head -5
```

Confirm with the user which run to analyze, then set:
```
RUN_ID=<confirmed run id>
RAW_DIR=results/${RUN_ID}/raw
```

---

## Step 2 — Inventory the raw files

Read the directory listing and report what is available:

```bash
ls -lh results/${RUN_ID}/raw/
```

Typical files:
- `install.log` — OpenShift installer log from `rosa logs install`
- `console-i-<instance-id>.txt` — EC2 serial console output per node

Also read `results/${RUN_ID}/events.jsonl` to see which milestones the scripted
collectors already recorded (avoid duplicating them in the LLM output).

---

## Step 3 — Analyze install.log

If `install.log` exists, read it with the Read tool and analyze using this
prompt template:

---
**PROMPT — install.log analysis**

You are analyzing an OpenShift installer log to build a precise provisioning
timeline. The log may use logrus key=value format
(`time="..." level=info msg="..."`) or JSON format.

For each significant event, produce a JSON object on its own line:
```json
{"milestone": "snake_case_name", "iso_timestamp": "2026-05-09T01:23:45Z", "confidence": "high|medium|low", "source_line": "<first 120 chars of matching line>"}
```

**Milestones to extract (if present):**
- Infrastructure creation start / VPC / subnets created
- Bootstrap EC2 instance requested / launched
- Bootstrap API server reachable (first `API v...` message)
- Bootstrap complete
- Bootstrap resources destroyed
- Worker node CSR approval
- Cluster operators progressing / available
- Install complete

**Also report:**
- Any ERROR or WARN lines with timestamps
- Any gap longer than 5 minutes between consecutive log entries
- If the install failed, the last meaningful log line before failure

**Do not** invent timestamps. If a line lacks a timestamp, mark confidence "low"
and note it in source_line.

LOG CONTENT:
```
{insert install.log content here — trim to first 8000 lines if very long}
```
---

After receiving the LLM output, format it as `record-event.py record` commands
(see Step 5).

---

## Step 4 — Analyze console-*.txt

For each `console-<instance-id>.txt` file, read it with the Read tool and
analyze using this prompt template:

---
**PROMPT — EC2 serial console analysis**

You are analyzing the EC2 serial console output (kernel boot log + systemd
journal) from a CoreOS/RHCOS node provisioned by OpenShift MachineAPI.

The file contains:
- Kernel boot messages with relative timestamps: `[   X.XXXXXX] message`
- systemd unit activation lines: `May 08 02:10:30 hostname systemd[1]: ...`
- Ignition log lines from `ignition-fetch`, `ignition-disks`, `ignition-files`,
  `ignition-complete`
- kubelet and CRI-O startup lines

For each significant boot event, produce a JSON object on its own line:
```json
{"milestone": "snake_case_name", "kernel_offset_s": 12.3, "systemd_timestamp": "May 08 02:10:30", "confidence": "high|medium|low", "source_line": "<first 120 chars>"}
```

Use `kernel_offset_s` (seconds from kernel start, from `[X.XXXXXX]` prefix) when
available. Use `systemd_timestamp` when the line is from the journal section.
Include both if both are present on the same line.

**Key milestones to extract:**
- Kernel start (offset 0.0)
- Ignition config fetch start (`ignition-fetch.service` starting)
- Ignition config fetch complete
- Ignition disk configuration complete
- Ignition files written complete
- Ignition complete (`ignition-complete.service` finished)
- Network interface up (first `NETDEV_UP` or `link becomes ready`)
- CRI-O started
- kubelet started (first kubelet log line)
- Any errors or unexpected long pauses

**Also note:**
- Total time from kernel start to kubelet start (if both are visible)
- Any ignition errors or retries

INSTANCE ID: {instance_id}

CONSOLE OUTPUT:
```
{insert console content here — trim to first 3000 lines if very long}
```
---

After receiving the LLM output, format it as `record-event.py record` commands
(see Step 5).

---

## Step 5 — Emit record-event.py commands

Convert the LLM-extracted milestones into shell commands the user can paste.
Use `llm.` as the label prefix so scripted and LLM-derived events are visually
distinct in the milestone table.

**For install log milestones:**
Use `T_START` (the `start_ms` of the first scripted event in events.jsonl, or
ask the user) as the baseline `--start-ms`.

```bash
# Install log milestones (LLM-extracted) — paste to merge into events.jsonl
python3 scripts/record-event.py record \
  --run-id       "${RUN_ID}" \
  --label        llm.install_log.bootstrap_ec2_requested \
  --start-ms     <T_START_MS> \
  --end-ms       <epoch_ms_from_iso_timestamp> \
  --cluster-type classic \
  --cluster-name <cluster_name>

python3 scripts/record-event.py record \
  --run-id       "${RUN_ID}" \
  --label        llm.install_log.worker_csr_approved \
  --start-ms     <T_START_MS> \
  --end-ms       <epoch_ms> \
  --cluster-type classic \
  --cluster-name <cluster_name>
```

**For console milestones**, use `T_POOL_START` as the baseline, and include the
instance ID in the label:

```bash
python3 scripts/record-event.py record \
  --run-id       "${RUN_ID}" \
  --label        "llm.console.i-0abc1234.ignition_fetch_start" \
  --start-ms     <T_POOL_START_MS> \
  --end-ms       <epoch_ms> \
  --cluster-type classic \
  --cluster-name <cluster_name> \
  --meta         instance_id=i-0abc1234 kernel_offset_s=12.3
```

**Helper: convert ISO timestamp to epoch milliseconds:**
```python
python3 -c "from datetime import datetime,timezone; print(int(datetime.fromisoformat('2026-05-09T01:23:45+00:00').timestamp()*1000))"
```

After the user pastes the commands, remind them to regenerate the report index:
```bash
python3 scripts/update-reports-index.py
```

---

## Step 6 — Optional narrative section

If the user wants a failure root-cause or anomaly summary to include in the
HTML report, synthesize a short narrative (3–8 sentences) covering:

- Total install time and how it compares to the typical range (35–50 min for Classic)
- Any phases that took significantly longer than expected
- Errors or warnings found in the logs
- Ignition fetch/complete latency vs. typical (< 2 min)
- Recommendation if anything looks actionable

Present this as a quoted block the user can paste into the HTML report's
`<section>` or into the Canvas artifact.

---

## Notes

- LLM-extracted events use the `llm.` prefix and are **additive** — they never
  overwrite scripted events.
- Confidence levels: `high` = explicit timestamp in source line; `medium` =
  inferred from context; `low` = estimated from kernel offset only.
- `kernel_offset_s` timestamps cannot be directly correlated to wall-clock time
  unless you know the instance launch time (from `pool.<name>.ec2_launch_requested`
  in events.jsonl). Use CloudTrail RunInstances time as the boot epoch anchor.
- The prompts in this skill are the canonical source for `scripts/analyze-raw-telemetry.py`
  once prompt quality is confirmed over several runs.
