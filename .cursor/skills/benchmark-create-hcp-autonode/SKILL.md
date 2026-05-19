---
name: benchmark-create-hcp-autonode
description: >-
  Provision a ROSA HCP cluster with AutoNode (Karpenter) enabled using the
  AutoNode Private Preview. Runs make create-hcp-autonode, which provisions the
  cluster via Terraform (injecting the provision_shard_id property) then
  performs AutoNode IAM setup, subnet/SG tagging, and rosa edit cluster
  --autonode=enabled. Delivers a Cursor Canvas with cluster details, IAM ARNs,
  timing breakdown, and AutoNode verification status. Use when the user wants to
  set up or benchmark a Karpenter-managed ROSA HCP cluster.
---

> **Agents — mandatory close-out:** Finish this skill through its documented **close-out** — a **Cursor Canvas** under `reports/` naming conventions (see Step 7). Do not end after `make create-hcp-autonode` alone. If blocked or partial, still deliver the Canvas with a failure narrative and next steps. See `.cursor/rules/local/rosa-benchmark-invocation.mdc`.

# Provision ROSA HCP with AutoNode / Karpenter

## Tooling gate (agents)

Before running this skill, verify required tools/integrations are available (`oc`, `rosa`, `terraform`, `aws`, `jq`, tmux MCP tools, local `tmux`, and cluster/cloud auth).
Require Python 3.11+ for harness scripts (`record-event.py` uses `datetime.UTC`; older system Python like macOS 3.9 will fail).

Prefer the repo virtual environment before lifecycle commands:

```bash
source .venv/bin/activate
python3 -V   # expect 3.11+
```

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

AutoNode is a Private Preview feature that replaces Cluster Autoscaler with Karpenter on ROSA HCP. This skill provisions a cluster into the dedicated AutoNode shard, creates the Karpenter IAM role, tags subnets/security groups for Karpenter discovery, and enables AutoNode via `rosa edit cluster`.

**Agents:** Confirm with the user before `make create-hcp-autonode` unless they gave a **direct command** to run it — see **Invocation & confirmation** in `benchmark-run-all` and `.cursor/rules/local/rosa-benchmark-invocation.mdc`.

## Prerequisites

- Enrolled in the AutoNode Private Preview (contact Red Hat support for access)
- ROSA CLI v1.2.57 or above (`rosa version`)
- `aws`, `oc`, `terraform`, `jq`, `python3` available (`make setup`)
- Python 3.11+ active (prefer `.venv` so `python3` is not the system 3.9)
- `rosa whoami` and `aws sts get-caller-identity` succeed
- `autonode.env` exists (`make init-env`), with:
  - `AUTONODE_PREFIX` set to a unique IAM prefix
  - `AUTONODE_SHARD_ID` set (default pre-filled: `9f11dd2b-98c1-11f0-8fe5-0a580a830a08`)
  - `AWS_REGION=us-east-1` (fixed for private preview)
  - `ROSA_VERSION` ≥ 4.19 (e.g. `4.19.15`)
  - `ROSA_CLUSTER_NAME_AUTONODE` set (max 15 chars)
- No existing cluster with the same name in OCM

## Inputs

Ask the user (or infer from context):
- `CLUSTER_TYPE`: must be `hcp-autonode` for this skill
- `RUN_ID`: existing run ID to resume (leave blank to start fresh)

## Checkpoint & Resume

```bash
python3 scripts/record-event.py ls
python3 scripts/checkpoint.py status --run-id "$RUN_ID" --test 01-cluster-install
python3 scripts/checkpoint.py next   --run-id "$RUN_ID"
```

## Procedure

### Step 0 — Resolve run ID

If `RUN_ID` is provided, verify it exists. If status is `completed`, report results from the existing run and skip execution. If blank, `init_run` in the create script will generate a new run ID.

### Step 1 — Verify cluster does not exist

```bash
rosa describe cluster -c "$CLUSTER_NAME" -o json 2>&1
```

If it already exists, stop and instruct the user to run `make destroy-hcp-autonode` first.

### Step 2 — Terraform init with module upgrade

The module ref was bumped to `28b2933` to pick up `additional_cluster_properties`. Run `terraform init -upgrade` once so the local `.terraform/modules` cache reflects the new ref:

```bash
cd clusters/hcp/terraform
terraform init -upgrade -backend-config="path=terraform.${CLUSTER_NAME}.tfstate" -reconfigure
cd -
```

### Step 3 — Run create-hcp-autonode (inside tmux)

Run the create script in the **`01-create` window** of the `benchmark-hcp-autonode` session. If the session does not already exist, create it first.

**Session + window setup:**

1. `find-session` (name=`benchmark-hcp-autonode`, socket=`benchmark-<RUN_ID>`) — create the session if absent.
2. In the session's default pane, set env (once, skip if resuming):

```bash
cd /path/to/repo
source .venv/bin/activate
source autonode.env
export RHCS_TOKEN="$(rosa token)"
export KUBECONFIG="$PWD/tmp/kubeconfig.${ROSA_CLUSTER_NAME_AUTONODE}.yaml"
export BENCHMARK_RUN_ID="<RUN_ID>"
```

3. `create-window` (sessionId=…, name=`01-create`) → save `paneId`.
4. `execute-command` (paneId=…, command=`make create-hcp-autonode 2>&1 | tee /tmp/autonode-create.log`) → save `commandId`.
5. Poll every 60–90 s with `get-command-result(commandId)`; while `status=pending`, call `capture-pane` (last 50 lines) to show live progress. Continue until `status=completed` or `status=failed`.
6. Read `exitCode`: `0` = success; non-zero = apply recovery paths (Step 6 troubleshooting or destroy/re-create).

The create script performs:

1. **Terraform apply** — provisions VPC, IAM roles, OIDC config, and the HCP cluster with `additional_cluster_properties = { provision_shard_id = "..." }` injected into the generated tfvars
2. **Wait for cluster ready** — polls OCM until `ready` state
3. **oc login** — using the `admin` htpasswd user created by Terraform
4. **AutoNode IAM** — creates `$PREFIX-autonode-operator-role` with the Karpenter permission policy; attaches `ec2:CreateTags` inline policy to `$PREFIX-kube-system-control-plane-operator`
5. **Subnet/SG tagging** — tags private subnets and default SG with `karpenter.sh/discovery=<cluster-id>`
6. **Enable AutoNode** — `rosa edit cluster --autonode=enabled --autonode-iam-role-arn=...`
7. **Post-ready milestones** — waits for worker nodes Ready and ClusterOperators Available
8. **CRD verification** — polls `ec2nodeclass/default` and `openshiftec2nodeclass/default` for `READY=True`

### Step 4 — Collect timing milestones

Read from `results/<RUN_ID>/events.jsonl` after the script completes:

| Order | Milestone | Label |
|-------|-----------|-------|
| 1 | Terraform apply complete | `hcp.terraform_apply` |
| 2 | OCM cluster ready | `hcp.cluster_ready` |
| 3 | `oc login` succeeded | `hcp.oc_login_ok` |
| 4 | AutoNode IAM role ready | `hcp.autonode_iam_ready` |
| 5 | Subnets/SG tagged | `hcp.subnets_tagged` |
| 6 | AutoNode enabled | `hcp.autonode_enabled` |
| 7 | Worker nodes Ready | `hcp.machine_pools_ready` |
| 8 | ClusterOperators Available | `hcp.operators_ready` |
| 9 | CRDs verified | `hcp.autonode_crds_verified` |
| 10 | Total | `hcp.total` |

```bash
python3 scripts/record-event.py summary --run-id "$RUN_ID"
```

### Step 5 — Verify AutoNode manually (optional)

```bash
export KUBECONFIG="tmp/kubeconfig.${CLUSTER_NAME}.yaml"
oc get ec2nodeclass
oc get openshiftec2nodeclass
oc get ec2nodeclass/default -o json | jq .status.conditions
```

### Step 6 — Troubleshoot if CRDs not Ready

If `ec2nodeclass/default` shows `SubnetsReady=False` or `SecurityGroupsReady=False`:

**SubnetsReady=False** — the `karpenter.sh/discovery` tag is missing from subnets:
```bash
CLUSTER_ID=$(rosa describe cluster -c "$CLUSTER_NAME" -o json | jq -r .id)
aws ec2 describe-subnets \
  --filters "Name=tag:kubernetes.io/cluster/${CLUSTER_ID},Values=shared" \
  --query 'Subnets[*].{ID:SubnetId,Tags:Tags}' --output json
# Tag missing subnets:
aws ec2 create-tags --resources <subnet-id> \
  --tags Key=karpenter.sh/discovery,Value="${CLUSTER_ID}"
```

**SecurityGroupsReady=False** — either the default SG tag is missing or the `ec2:CreateTags` inline policy is absent from the control-plane-operator role:
```bash
# Check CloudTrail for ec2:CreateTags UnauthorizedOperation errors, then:
aws iam put-role-policy \
  --role-name "${AUTONODE_PREFIX}-kube-system-control-plane-operator" \
  --policy-name "AutoNodeCreateTags" \
  --policy-document file://tmp/cpo-createtags.json
# Manually tag the SG if needed:
SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=${CLUSTER_ID}-default-sg" \
  --query 'SecurityGroups[0].GroupId' --output text)
aws ec2 create-tags --resources "$SG_ID" \
  --tags Key=karpenter.sh/discovery,Value="${CLUSTER_ID}"
```

**CRDs not appearing after 5+ minutes** — verify the cluster is on the correct shard:
```bash
rosa describe cluster -c "$CLUSTER_NAME" -o json | jq -r .properties.provision_shard_id
# Must be: 9f11dd2b-98c1-11f0-8fe5-0a580a830a08
```

If the shard ID is wrong or empty, the cluster was not placed on the AutoNode-enabled management cluster. Destroy and re-create; verify `AUTONODE_SHARD_ID` is set in `autonode.env`.

### Step 7 — Canvas deliverable (mandatory close-out)

Read the `benchmark-create-hcp-autonode` Canvas skill for full canvas instructions. The canvas must include:

- **Cluster summary** — name, ID, version, shard ID, region, OIDC provider URL
- **IAM resources** — policy ARN, role ARN, control-plane-operator inline policy status
- **Timing breakdown** — table of all `hcp.*` milestones with elapsed times (from `events.jsonl`)
- **AutoNode status** — `ec2nodeclass/default` and `openshiftec2nodeclass/default` Ready status and conditions
- **Next steps** — create a NodePool, deploy a workload with `nodeSelector: autonode: "true"`, observe Karpenter scaling

Save the canvas file as `reports/autonode-<CLUSTER_NAME>-<RUN_ID>.canvas.tsx`.

Then update checkpoint:
```bash
python3 scripts/checkpoint.py complete --run-id "$RUN_ID" --test 01-cluster-install
```

## Destroy guidance

Before `make destroy-hcp-autonode`, delete Karpenter resources inside the cluster to avoid EC2 instances blocking deletion (KCS (3) in `references/autonode/`). The destroy script does this automatically if `oc` can reach the cluster. If the cluster API is unreachable, terminate instances manually:

```bash
CLUSTER_ID=$(rosa describe cluster -c "$CLUSTER_NAME" -o json | jq -r .id)
INSTANCE_IDS=$(aws ec2 describe-instances \
  --filters "Name=tag:eks:eks-cluster-name,Values=${CLUSTER_ID}" \
  --query 'Reservations[*].Instances[*].InstanceId' --output text)
# Review instance IDs before terminating:
echo "$INSTANCE_IDS"
aws ec2 terminate-instances --instance-ids $INSTANCE_IDS
```

Then run destroy in the **`destroy` window** of the `benchmark-hcp-autonode` session:

```bash
# create-window name="destroy", then execute-command:
make destroy-hcp-autonode
# On refresh / cluster_default / Invalid index errors after partial teardown:
ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH=1 make destroy-hcp-autonode
```

After confirmed teardown and the Canvas report are both complete, call `kill-session` to clean up the benchmark session.

## Timing reference (expected ranges)

| Segment | Expected |
|---------|----------|
| Terraform apply (VPC + IAM + cluster) | 15–30 min |
| Cluster ready → oc login | 2–10 min |
| AutoNode IAM + tagging + enable | ~2 min |
| Workers Ready | 5–15 min |
| ClusterOperators Available | 2–10 min |
| CRDs verified (Karpenter install) | 2–5 min |
| **Total** | **~30–60 min** |
