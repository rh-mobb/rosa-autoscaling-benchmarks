# ROSA Autoscaling Benchmark

Benchmarking and demonstration harness for cluster autoscaling across **ROSA Classic**, **ROSA HCP** with Cluster Autoscaler (CAS), and **ROSA HCP with AutoNode** (Karpenter-style provisioning). Use **`make create-hcp-autonode`** and **`clusters/hcp-autonode/`** for the AutoNode topology.

## What This Covers

### Core benchmarks (01–09)

| # | Scenario |
|---|----------|
| 01 | Cluster install timing — Classic: `rosa create cluster`; HCP / HCP AutoNode: Terraform apply → operators healthy |
| 02 | Machine pool provisioning — time per machine type until node `Ready` |
| 03 | Cluster autoscale up — unschedulable workload triggers CAS or Karpenter |
| 04 | Cluster autoscale down — workload removed; CAS cooldown vs Karpenter consolidation |
| 05 | Unschedulable oversize workload — exceeds pool instance size (**CAS**: `NotTriggerScaleUp`; **AutoNode**: run **05b** instead) |
| 06 | Horizontal Pod Autoscaler — CPU breach → new pod running |
| 07 | Vertical Pod Autoscaler (advise only) — shows resource recommendations |
| 08 | HPA triggers cluster autoscaler — no room left; CAS or Karpenter scales nodes before pods run |
| 09 | Overprovisioning — pause pods absorb demand so HPA avoids waiting for scale-up (**Classic / HCP CAS**); **`hcp-autonode`** uses **09b** (Karpenter-saturated baseline + same pattern) |

### Variants

| # | Scenario |
|---|----------|
| 05b | Dynamic instance selection — oversize-for-pool workload that **fits** a larger SKU; **AutoNode** provisions appropriate instance (**`benchmark-unschedulable`**) |
| 09b | Karpenter / AutoNode overprovisioning — saturated NodePool baseline + pause-pod headroom (**`benchmark-overprovisioning`**) |

### Advanced autoscaling (10–16)

| # | Scenario |
|---|----------|
| 10 | AutoNode (Karpenter) progressive node provisioning + consolidation — **`hcp-autonode` only** (skipped on Classic / standard HCP) |
| 11 | Planned surge — balloon pods vs proactive node pre-warming |
| 12 | Sudden spike — two-phase comparison (reactive-only vs slack + HPA) |
| 13 | Parallel nodes — multi-node provisioning stagger |
| 14 | CAS progressive scale benchmark — **Classic / standard HCP** (skipped on **`hcp-autonode`**; compare with test **10**) |
| 15 | Spot instance autoscaling — **Classic + `hcp-autonode`** (skipped on standard HCP) |
| 16 | ARM64 (Graviton) node provisioning — all cluster types |

Orchestration: **`benchmark-advanced-autoscaling`** (suite + per-test skills). Tests **10** and **14** share methodology — keep them in sync (see **`AGENTS.md`**).

## Architecture

Tests are driven by **Cursor Agent Skills** that live in `.cursor/skills/`. Each skill orchestrates its scenario by:

- Running **`rosa`/bash** for **ROSA Classic** and machine pools; **ROSA HCP** install/teardown runs through **Terraform** (`clusters/hcp/terraform` via `clusters/hcp/*.sh`).
- Using the **`oc` CLI** for all in-cluster work — events, metrics (`oc adm top`), pod/node state, **`oc apply` / `oc scale` / `oc delete`** against **`manifests/`** — with per-cluster kubeconfig files under **`tmp/kubeconfig.<cluster-name>.yaml`** (see **`clusters/common.sh`** and **`make help`**), not shared **`~/.kube/config`** alone.
- Writing **HTML reports** under **`reports/`** using **`RUN_ID`** in the filename (e.g. **`${RUN_ID}-01-hcp-cluster-install.html`**; **`RUN_ID`** already embeds a UTC timestamp) for test **01** cluster-install results (template: **`reports/template-01-classic-cluster-install.html`** for Classic), **Cursor Canvases** for tests **02–09** (and variants **05b** / **09b**) as each skill’s mandatory close-out, and **Canvases plus suite HTML** for advanced tests **10–16** when you run **`benchmark-advanced-autoscaling`** or **`benchmark-run-all`** (which chains the core suite and may include advanced work per skill docs).

Agents should **complete** those deliverables (not stop at **`make add-pool`**-style steps alone) — see **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

This means test runs are interactive and agent-interpreted, not silent log files.

## Autoscaling Advisor

Discovery-first agent that analyzes a running cluster and produces ranked,
evidence-backed autoscaling recommendations. Runs three phases: topology
discovery, workload observation (Prometheus 7d history + VPA), and reasoning
(R0–R10 catalog). Outputs HTML and JSON reports.

```bash
cd advisor && pip install -r requirements.txt

# Scope to the OTel demo namespace on the classic-bench cluster
python3 agent.py --cluster-type classic --namespace otel-demo

# Full cluster audit
python3 agent.py --cluster-type hcp-autonode

# Open the report
open reports/advisor/advisor_report.html
```

See [`advisor/README.md`](advisor/README.md) for the full CLI reference and
[`.cursor/skills/autoscaling-advisor/SKILL.md`](.cursor/skills/autoscaling-advisor/SKILL.md)
for the interactive Cursor skill.

---

## Load-Test Harness

A realistic HTTP load-testing environment for validating autoscaling behavior
with real user-facing metrics (latency, error rate) rather than pod-readiness
timings alone. Used by the autoscaling advisor to compare before/after states
when recommendations are applied.

Built on the **OpenTelemetry Demo App** (19 microservices across Go, .NET,
Python, Node.js, Ruby, Java) with intentionally misconfigured HPAs and
**k6** for controlled load scenarios.

```bash
# Deploy to an existing cluster
CLUSTER_TYPE=classic ./load-test/deploy.sh install

# Run a load scenario (creates a k6 Job, tails output)
./load-test/deploy.sh run-k6 sudden-spike BASELINE_RPS=30 SPIKE_RPS=300
./load-test/deploy.sh run-k6 ramp         BASELINE_RPS=30 PEAK_RPS=150
./load-test/deploy.sh run-k6 burst-and-drop

# Status check
./load-test/deploy.sh status

# Tear down (with confirmation)
CLUSTER_TYPE=classic ./load-test/deploy.sh uninstall
```

**Scenarios:** `sudden-spike` (10× burst), `ramp` (linear to 5×), `daily-pattern`
(compressed 24h), `sustained-high` (3× hold + scale-down observation),
`burst-and-drop` (HPA stabilization tuning).

Full documentation: **[load-test/README.md](load-test/README.md)**. Skill:
**`benchmark-load-test`**.

## Browser autoscaling simulator

For a **local, no-cluster demo**, open **`simulator/index.html`** in a browser. The page loads React and Recharts from public CDNs, so you need **network access** the first time you run it.

The simulator is an **illustrative toy model**: synthetic traffic curves (manual, daily rhythm, on-sale burst, viral surge), HPA-style replica targets, optional balloon / overprovisioning pods, and three modes with timings aligned to this repo’s **Classic CAS**, **HCP CAS**, and **HCP + AutoNode** stories (spread vs bin-pack, scale-up delay, provision duration, scale-in cooldown). It charts demand vs capacity, dropped throughput, and two **separate** USD framings (worker runtime vs a cents-per-dropped-request assumption). Use it for intuition and deck walkthroughs — **not** as a substitute for live benchmarks under **`scripts/`** and the **`benchmark-*`** skills.

```bash
# macOS example
open simulator/index.html
```

Architecture, constants, tick order, and limitations: **`simulator/README.md`**.

## GitHub Pages

On every push to **`main`**, **Deploy GitHub Pages** (`.github/workflows/deploy-github-pages.yml`) builds the Slidev deck under **`presentation/`** with the correct subpath base, copies **`simulator/index.html`** to **`/simulator/`**, renders **`pages/index.html`** as the site home page, and deploys the bundle to GitHub Pages. You can also run the workflow manually (**Actions → Deploy GitHub Pages → Run workflow**).

**One-time setup:** in the GitHub repo, open **Settings → Pages → Build and deployment**, set **Source** to **GitHub Actions** (not “Deploy from a branch”). Until this is saved, **Deploy GitHub Pages** will fail at the deploy step with **404 Not Found** (“Creating Pages deployment failed”). After the first successful run, the site URL is:

`https://<owner>.github.io/<repository>/`

Paths:

| Path | Content |
|------|---------|
| `/` | Landing page (project summary + links) |
| `/simulator/` | Browser autoscaling simulator |
| `/deck/` | Static Slidev build (Classic vs HCP + AutoNode benchmarks deck) |

The landing template lives in **`pages/index.html`** (placeholder `__GITHUB_REPO_URL__` replaced in CI). **`pages/`** is only for publishing — it is not used by local benchmark runs.

## Prerequisites

| Tool | Purpose |
|------|---------|
| [`rosa`](https://github.com/openshift/rosa) | Cluster and machine pool lifecycle |
| [`oc`](https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html) | Cluster login and context switching |
| [`aws`](https://aws.amazon.com/cli/) | EC2 instance type validation |
| [`terraform`](https://www.terraform.io/) | **`make create-hcp`** default provisions **`clusters/hcp/terraform`** (RHCS + AWS providers) |
| [`helm`](https://helm.sh/) ≥ 3 | Deploy the OTel demo load-test harness (`load-test/deploy.sh install`) |
| `jq` | JSON parsing in bash scripts |
| `python3` | Complex parsing and version detection |
| `shellcheck` | Bash script linting |
| `ruff` | Python script linting |

You must be **already logged in** before running anything:

```bash
rosa login          # authenticate with Red Hat OCM (also sources RHCS_TOKEN for Terraform via `rosa token` when unset)
aws configure       # or set AWS_PROFILE / instance role
```

For **`make create-hcp`**, set **`RHCS_TOKEN`** explicitly if Terraform cannot reuse `rosa token` (offline tokens and CI/CD); see **`clusters/hcp/terraform/README.md`**.

## Quick Start

```bash
# 1. Create config (fixed paths: classic.env, hcp.env)
make init-env

# 2. Validate prerequisites
make setup

# 3. Edit classic.env / hcp.env (`hcp.env` tunes Terraform-backed HCP; see template)
$EDITOR classic.env hcp.env

# 4. Create clusters
make create-classic
make create-hcp
# Optional: ROSA HCP with AutoNode (tests 10, 09b, etc.)
# make create-hcp-autonode

# 5. Open Cursor and invoke a benchmark skill
# e.g. "run benchmark-run-all for CLUSTER_TYPE=classic"

# 6. Tear down when done
make destroy-classic
make destroy-hcp
```

## Configuration

Filenames are fixed: **`classic.env`** (ROSA Classic settings) and **`hcp.env`** (ROSA HCP). This matches “at most one Classic and one HCP” in the benchmark harness. **`ROSA_CLUSTER_NAME_CLASSIC`** and **`ROSA_CLUSTER_NAME_HCP`** still default to **`classic-bench`** and **`hcp-bench`** inside those files; rename the cluster by editing the variable, not the filename.

Both files are loaded each `make` invocation (`classic.env` first, then `hcp.env`); duplicate keys are won by **`hcp.env`**.

The root `Makefile` does not read a monolithic `.env`; move any legacy values into **`classic.env`** / **`hcp.env`** (rename old `classic-bench.env` → **`classic.env`**, etc., if upgrading).

**Non-interactive destroy:** All three `make destroy-*` targets prompt you to type the cluster name. To skip the prompt in automation or agent workflows, set `ROSA_DESTROY_YES=<cluster-name>`:

```bash
ROSA_DESTROY_YES=an-bench make destroy-hcp-autonode
ROSA_DESTROY_YES=hcp-bench make destroy-hcp
ROSA_DESTROY_YES=classic-bench make destroy-classic
```

The safety check still validates that the value matches the actual cluster name — it just skips the interactive `read`.

**Cluster create locks:** Each topology has its own mutex: `tmp/cluster-create-classic.lock/` and `tmp/cluster-create-hcp.lock/`. You can run **`make create-classic` and `make create-hcp` at the same time**; overlapping two Classic (or two HCP) creates is blocked. Locks clear on exit/interrupt or stale reclaim (dead holder PID, or age over `CLUSTER_CREATE_LOCK_MAX_AGE_SEC`, default 6 hours). Emergency bypass: `ROSA_CLUSTER_CREATE_LOCK_DISABLE=1`. Inspect: `make cluster-create-lock-status`. If an older repo left `tmp/cluster-create.lock/`, delete it manually; it is no longer used.

Key variables (typically set in cluster env files; defaults below apply if omitted):

| Variable | Default | Description |
|----------|---------|-------------|
| `ROSA_CLUSTER_NAME_CLASSIC` | `classic-bench` | Classic cluster name (max 15 chars; set in **`classic.env`**) |
| `ROSA_CLUSTER_NAME_HCP` | `hcp-bench` | HCP cluster name (max 15 chars; set in **`hcp.env`**) |
| `AWS_REGION` | `us-east-1` | AWS region |
| `ROSA_VERSION` | `4.21.12` (in `*.env.example`) | Set **the same value in `classic.env` and `hcp.env`** (Makefile loads `hcp.env` last; a blank line there overrides Classic). Blank in both ⇒ auto-detect latest common Classic/HCP version. |
| `AUTOSCALE_MIN_REPLICAS` | `1` | Minimum nodes for benchmark machine pools |
| `AUTOSCALE_MAX_REPLICAS` | `10` | Maximum nodes for benchmark machine pools |
| `CLUSTER_ADMIN_PASSWORD` | _(Make default only)_ | Required for cluster creation — set in at least one cluster env file |

**ROSA HCP (Terraform only):** **`make create-hcp`** runs **`clusters/hcp/create.sh`**, which **only** applies **`clusters/hcp/terraform`** (no `rosa create cluster` flow in this repo). State file: **`clusters/hcp/terraform/terraform.<cluster-name>.tfstate`**. Benchmark timing includes **`hcp.terraform_init`**, optional **`hcp.ocm403_retry_sleep`** (time in OCM **403** backoff only), **`hcp.terraform_apply`**, **`hcp.create_submitted`** (full apply window), then **`wait_for_cluster_state`** plus **`oc wait`**. **`make reconcile-hcp`** runs **`clusters/hcp/reconcile.sh`** for a **full** Terraform apply on an existing stack (e.g. after a partial **`create-hcp`**). Optional **`ROSA_HCP_TERRAFORM_VAR_FILE`** points at a complete `.tfvars` (advanced / BYO patterns). **`ROSA_HCP_REPLICAS`**, **`ROSA_HCP_MAX_POOL_REPLICAS`** (default pool max per AZ; falls back to **`AUTOSCALE_MAX_REPLICAS`**), **`ROSA_HCP_MULTI_AZ`**, **`ROSA_HCP_NETWORK_VPC_CIDR`**, and **`ROSA_HCP_INSTANCE_TYPE`** feed the auto-generated snippet when that file is not set. **`ROSA_HCP_TERRAFORM_403_*`** tune the transient **`CLUSTERS-MGMT-403`** retry loop; see **`hcp.env.example`**.

**ROSA Classic:** **`make create-classic`** uses **`clusters/classic/create.sh`**. Set **`ROSA_CLASSIC_MULTI_AZ=yes`** with **`ROSA_CLASSIC_COMPUTE_*`** for multi-AZ worker autoscaling (see **`classic.env.example`**).

**`make destroy-hcp`** runs **`terraform destroy`** via **`clusters/hcp/destroy.sh`** and **requires that state file**. Without state you must delete the cluster and IAM/VPC remnants through OCM and AWS yourself — there is no ROSA-cli destroy path scripted here for HCP.

## Benchmark Skills

Skills live in **`.cursor/skills/benchmark-*/`**. The model **may invoke them automatically** when the chat is clearly about benchmarking. **Confirmation:** vague or exploratory asks deserve a quick scope check before **`make create-*`** / **`terraform apply`** / long runs; explicit commands (e.g. “run **`benchmark-run-all`**”) proceed without extra ping — see **`benchmark-run-all`** skill and **`.cursor/rules/local/rosa-benchmark-invocation.mdc`**.

Invoke them by name in chat. Most skills take **`CLUSTER_TYPE=classic`**, **`hcp`**, or **`hcp-autonode`** where the scenario applies (AutoNode-only tests skip automatically on the wrong topology).

| Skill | Description |
|-------|-------------|
| `benchmark-cluster-install` | Time cluster creation and operator readiness |
| `benchmark-create-hcp-autonode` | Provision **ROSA HCP with AutoNode** (Terraform + IAM + `rosa edit cluster --autonode`) |
| `benchmark-machine-pool` | Time machine pool provisioning per instance type |
| `benchmark-autoscale-up` | Trigger and measure cluster scale-up |
| `benchmark-autoscale-down` | Trigger and measure cluster scale-down |
| `benchmark-unschedulable` | Tests **05** / **05b** — static pool vs dynamic instance fit |
| `benchmark-hpa` | Measure HPA response time under CPU load |
| `benchmark-vpa-advise` | Show VPA resource recommendations |
| `benchmark-hpa-triggers-cas` | Measure end-to-end HPA → autoscaler → pod scheduled |
| `benchmark-overprovisioning` | Tests **09** / **09b** — pause-pod headroom vs HPA+CAS/Karpenter |
| `benchmark-autonode-scale` | Test **10** — progressive AutoNode provisioning ( **`hcp-autonode`** ) |
| `benchmark-planned-surge` | Test **11** |
| `benchmark-sudden-spike` | Test **12** |
| `benchmark-parallel-nodes` | Test **13** |
| `benchmark-cas-scale` | Test **14** — CAS counterpart of test **10** |
| `benchmark-spot-instances` | Test **15** |
| `benchmark-arm-nodes` | Test **16** |
| `benchmark-advanced-autoscaling` | Run **10–16** with cluster-type skips + suite HTML |
| `benchmark-run-all` | Core suite **01–09** in sequence; comparison HTML under **`reports/`** |
| `benchmark-load-test` | Deploy OTel demo + k6 load scenarios on a running cluster; validate and tear down |

## Machine Types Tested

| Script | Instance | vCPU | RAM | Notes |
|--------|----------|------|-----|-------|
| `add-standard.sh` | `m5.xlarge` | 4 | 16 GiB | General purpose baseline |
| `add-memory-optimized.sh` | `r5.xlarge` | 4 | 32 GiB | Memory-intensive workloads |
| `add-compute-optimized.sh` | `c5.xlarge` | 4 | 8 GiB | Compute-intensive workloads |
| `add-bare-metal.sh` | `m5.metal` | 96 | 384 GiB | Bare metal — longest provision time |

## Repository Structure

```
.
├── Makefile
├── README.md
├── simulator/                  # Browser demo — README.md + index.html (CDN scripts)
├── pages/                      # GitHub Pages landing template (see workflow)
├── .github/workflows/          # CI — lint + GitHub Pages deploy on main
├── classic.env.example         # Template for classic.env
├── hcp.env.example             # Template for hcp.env
├── clusters/
│   ├── classic/          # ROSA Classic create/destroy scripts
│   ├── hcp/              # HCP wrappers + terraform/ (validated-pattern ROSA modules)
│   ├── hcp-autonode/     # HCP + AutoNode (Karpenter) create/destroy
│   └── hcp-karpenter/    # Legacy / preview notes (prefer hcp-autonode/)
├── terraform/
│   └── hcp-simple/       # Pointer only; stack lives under clusters/hcp/terraform/
├── machine-pools/        # Machine pool provisioning scripts
├── manifests/
│   ├── workloads/        # cpu-burner, memory-hog deployments
│   ├── autoscaling/      # HPA and VPA definitions
│   └── overprovisioning/ # pause pod priority class + deployment
├── scripts/              # Python utility scripts
├── load-test/            # OTel demo + k6 load-test harness (see load-test/README.md)
│   ├── deploy.sh         # install / status / run-k6 / uninstall
│   ├── helm/             # values-rosa.yaml — ROSA-compatible OTel demo Helm values
│   ├── manifests/        # namespace, SCC bindings, HPA/VPA/KEDA configs
│   └── k6/               # scenarios/, lib/, jobs/ — k6 load scripts and Job template
└── .cursor/
    └── skills/           # Cursor Agent Skills (one per benchmark)
```

## ROSA HCP with AutoNode

AutoNode benchmarks use **`CLUSTER_TYPE=hcp-autonode`**, **`make create-hcp-autonode`** / **`make destroy-hcp-autonode`**, and **`clusters/hcp-autonode/`**. The older **`clusters/hcp-karpenter/`** tree may still hold preview-era notes; prefer **`benchmark-create-hcp-autonode`** and the **`hcp-autonode`** scripts for current flows.

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Please read the [Code of Conduct](CODE_OF_CONDUCT.md). To report security-sensitive issues, see [SECURITY.md](SECURITY.md).
