---
name: rosa-cli
description: >-
  Provides full syntax reference and workflow guidance for the ROSA CLI (Red Hat
  OpenShift Service on AWS). Use when the user asks about rosa commands, flags,
  cluster creation, machine pools, IDPs, upgrades, STS/IAM setup, OIDC
  configuration, architecture (Classic vs hosted control planes), or any rosa CLI
  operation. Covers ROSA Classic and ROSA with HCP (hosted control planes): install and
  teardown ordering, VPC/network prerequisites, subnet tagging, VPC and PrivateLink
  behavior, account-wide and Operator IAM roles, and OIDC for in-cluster Operators.
  For IaC HCP provisioning in this repository, prefer clusters/hcp/terraform (Terraform
  modules from github.com/rh-mobb/validated-pattern-terraform-rosa via Git), applied by **`make create-hcp`** / **`clusters/hcp/create.sh`** (bash is not used for HCP `rosa create` / `rosa delete`). Not a local references/ checkout — references is gitignored and may be missing on fresh clones.
  Architecture and STS summaries below are maintained inside this
  skill. Before proposing or running a specific rosa subcommand, read that command's
  section in commands-reference.md; flag syntax there is authoritative.
---

# ROSA CLI

## Tooling gate (agents)

Before running `rosa` or related cluster commands, verify required tools/integrations are available (`rosa`, `oc`, `aws`; and `terraform` where HCP Terraform flows are in scope).

If any required dependency is missing or failing, **stop and ask the user to install/fix it first**. Proceed in reduced mode only if the user explicitly declines.

Do not silently work around missing prerequisites.

Full syntax reference for the `rosa` CLI (v1.2.60+).
Human-readable flag text for every command lives in [commands-reference.md](commands-reference.md).
Re-generate after upgrading: `bash .cursor/skills/rosa-cli/scripts/gen-reference.sh`.

**Scope:** Sections below summarize platform concepts (Classic vs hosted control planes, STS/IAM/OIDC intent, networking and sizing basics). They deliberately omit exhaustive lists from upstream docs—those belong in Red Hat product documentation when someone needs full tables or policies. For **`rosa` flags and examples**, always use [commands-reference.md](commands-reference.md).

**Classic ↔ HCP:** You **cannot** upgrade or convert an existing **Classic** cluster to **hosted control planes**—provision a **new** `--hosted-cp` cluster and migrate workloads. Current ROSA with HCP installs are **STS-only** (no non‑STS path in supported flows).

## Prerequisites (before any install)

- **Accounts:** Red Hat account + AWS account (`rosa login`, AWS credentials in `~/.aws/credentials` or env); dedicated AWS account is recommended for production.
- **AWS for ROSA:** Enable ROSA in the AWS console (ROSA “Get started” / prerequisites wizard), confirm **service quotas**, and ensure **`AWSServiceRoleForElasticLoadBalancing`** exists—preflight in the console mirrors what **`rosa verify quota`** / **`rosa verify permissions`** exercise from the CLI.
- **CLIs:** Current **`aws`**, **`rosa`** (this repo’s reference assumes **v1.2.60+**; **`rosa create network`** requires **≥ v1.2.48**), and **`oc`**—install **`oc`** with **`rosa download openshift-client`** then **`rosa verify openshift-client`**.
- **Hybrid Cloud / OCM:** Some **auto** IAM paths initiated from the Hybrid Cloud Console expect an admin‑privileged **`ocm-role`** linked to your AWS account; CLI‑only flows may not hit that requirement.

## How to use this skill (do not skip the reference)

**This file (`SKILL.md`) is orientation and rough workflow only.** Bash blocks here are illustrative; they are **not** guaranteed to include every mandatory or env-specific flag.

**Mandatory discipline before you propose or run any `rosa …` invocation:**

1. Decide the exact verb and resource (e.g. `rosa create cluster`, `rosa create operator-roles`).
2. Open [commands-reference.md](commands-reference.md) and locate the heading `## rosa <verb> <resource>` (e.g. `## rosa create cluster`).
3. Read **all** flags relevant to your cluster type (**Classic vs `--hosted-cp`**) and to non-interactive use (`--yes`, automation, CI).
4. Construct or validate the command line against that section. If the reference documents a coupling (examples: subnets, replicas, STS/OIDC, installer role ARN), obey it—the narrative sections below will not spell out every coupling.

Skipping step 2–3 causes wrong assumptions (e.g. `--yes` while required networking flags are missing, or interactive prompts blocking automation).

## Where ROSA is operated from

Clusters are subscribed through your AWS account. Day‑2 operations use the **OpenShift web console**, **`rosa`**, or **OpenShift Cluster Manager (OCM)**—cluster create/delete, identity providers, machine pools and autoscaling, privacy, and upgrade scheduling. Prefer **`rosa`** when automating or when you need repeatable CLI flows.

## Key Concepts

| Term | Meaning |
|------|---------|
| **Classic** | Control plane (API, etcd, etc.) runs in **your** AWS account/VPC; workers (and control plane nodes) use your VPC topology |
| **ROSA with HCP / `--hosted-cp`** | Control plane runs in a **Red Hat–owned** AWS account; **workers** run in **your** VPC **private subnets**. Workers reach the control plane over **AWS PrivateLink** |
| **STS** | AWS Security Token Service — recommended model: short‑lived credentials via IAM roles and scoped AWS managed policies (`rosa` creates/attaches roles and can use `--mode auto` or `--mode manual`) |
| **OIDC configuration (`rosa create oidc-config`)** | Defines how cluster Operators authenticate to AWS; **each production cluster needs its own OIDC configuration**. Often created **before** `rosa create cluster`; pass **`--oidc-config-id`** on create for HCP. Separate from end‑user login (**`rosa create idp`**) |
| **OIDC provider (IAM)** | IAM trust for the issuer; **managed OIDC** setups may create/update this during **`rosa create oidc-config`**. Classic STS flows often add **`rosa create oidc-provider`** **after** the cluster exists—ordering differs by topology |
| **Cluster identity providers (IDP)** | End‑user login (GitHub, LDAP, OpenID Connect, htpasswd, etc.) via **`rosa create idp`** — separate from IAM OIDC for Operators |
| **Account-wide roles (HCP naming)** | IAM roles such as `<prefix>-HCP-ROSA-Installer-Role`, `-Worker-Role`, `-Support-Role`; trust policies allow Red Hat’s automation role to assume them (cross‑account) and EC2 to assume worker/instance roles; AWS attaches ROSA **managed policies** scoped to ROSA resources |
| **Operator roles** | IAM roles Operators use via STS; **HCP** quick‑install paths usually create them **before** the cluster using **`--hosted-cp`**, **`--prefix`**, **`--oidc-config-id`**, and **`--installer-role-arn`** pointing at **`*-HCP-ROSA-Installer-Role`**. **Classic** commonly creates them **after** `rosa create cluster` using **`--cluster=…`** |
| **Account roles** | IAM roles created per account (`rosa create account-roles`; use **`--hosted-cp`** for HCP‑oriented account roles) |
| **Machine pool** | Homogeneous group of worker nodes; **`rosa create machinepool`** applies to **both** Classic and HCP |
| **Node pool** | Hosted‑control‑plane terminology for worker pools; in practice still **`machinepool`** subcommands in `rosa` |

### Classic vs HCP (architecture snapshot)

**HCP** (`--hosted-cp`): control plane always spans multiple AZs; **each machine pool lives in a single AZ** (private subnet); no dedicated **infrastructure** nodes—ingress, image registry, and monitoring run on **workers**. **Classic**: control plane can be single‑ or multi‑AZ; **infrastructure** nodes (typically **2** single‑AZ or **3** multi‑AZ) host those platform components; machine pools may span one or more AZs. **Upgrades:** on HCP, control plane and **individual machine pools** can move independently; on Classic, the **cluster is upgraded as one**. **Rough minimum EC2** count **only for provisioning**: **2** instances for HCP vs **7** (Classic single‑AZ) or **9** (Classic multi‑AZ)—capacity grows quickly beyond minimum with workloads.

### STS and IAM workflow (ROSA with HCP — supported CLI order)

Canonical **CLI** order for hosted control planes is: (1) **`rosa create account-roles --hosted-cp`** (account‑wide STS roles; default prefix is often **`HCP-ROSA`** unless you override), (2) **`rosa create oidc-config --mode=auto --yes`** (capture **`--oidc-config-id`**; managed OIDC also wires **IAM OIDC provider** pieces), (3) **`rosa create operator-roles --hosted-cp`** with **`--prefix`**, **`--oidc-config-id`**, and **`--installer-role-arn`** for **`*…-HCP-ROSA-Installer-Role`**, (4) **`rosa create cluster --hosted-cp`** with **`--mode=auto`**, **`--sts`**, **`--oidc-config-id`**, **`--operator-roles-prefix`**, **`--subnet-ids`**, plus **`--private`** when the cluster/API should be private (**private‑only subnets** in that case).

**`--mode auto`** applies IAM immediately in the current AWS account; **`--mode manual`** prints **`aws`** commands for audited/IaC workflows.

**Classic STS ordering is different** (commonly OIDC config → **cluster** → operator‑roles **`--cluster`** → **`rosa create oidc-provider`**)—do **not** assume the HCP sequence applies.

## Networking: Classic default vs HCP

- **ROSA Classic (`rosa create cluster` without BYO flags):** The usual path is **installer / ROSA-managed networking**—VPC and subnets can be **provisioned for you** when you do not supply existing subnet IDs. **`--availability-zones`** applies to **non-BYOVPC** installs; exact behavior and flags are defined in **`## rosa create cluster`** in [commands-reference.md](commands-reference.md). Bringing your own VPC/subnets is optional and flag-driven.

- **ROSA HCP (`--hosted-cp`):** Clusters install into a **preexisting VPC** in one AWS region; workers run on **your private subnets**. Plan on bringing your own VPC/subnets (same expectation when using AWS PrivateLink patterns). API reachability to the hosted control plane goes through **PrivateLink** whether you expose a public or private API endpoint. **Region cannot be changed** after install.

- **Network verification:** Automated checks run when deploying into an **existing** VPC or when adding a machine pool whose subnet is **new** to the cluster; you can run verification manually for an existing cluster to validate firewall/subnet routes before changes bite—specific **`rosa`** verbs live in [commands-reference.md](commands-reference.md).

- When you need a **fresh VPC**, **`rosa create network`** (CloudFormation) provisions public **and** private subnets, NAT, gateways, and optional interface endpoints—defaults are typically **one AZ**, **`us-east-1`**, **`10.0.0.0/16`** when you omit **`--param`** overrides; stacks usually finish in ~**5 minutes**. Read **`### rosa create network`** in [commands-reference.md](commands-reference.md). Use stack outputs for **`--subnet-ids`** on **`rosa create cluster`** (documented quick starts often pass **both** public and private subnet IDs for **public** clusters).

### Subnet tags (BYO VPC)

Preflight expects ELB‑discovery tags on subnets: **public** subnets **`kubernetes.io/role/elb` = `1`** (empty value is also documented); **private** subnets **`kubernetes.io/role/internal-elb` = `1`**. Tag **at least one private** subnet and, when you have public subnets, **at least one public** subnet. Example:

```bash
aws ec2 create-tags --resources "$PUBLIC_SUBNET_ID"  --region "$AWS_REGION" --tags Key=kubernetes.io/role/elb,Value=1
aws ec2 create-tags --resources "$PRIVATE_SUBNET_ID" --region "$AWS_REGION" --tags Key=kubernetes.io/role/internal-elb,Value=1
```

Manual VPCs also need DNS hostnames/resolution enabled; **public** installs need a **public subnet with a NAT gateway**; **private** installs do **not** require a public subnet. Align VPC **CIDR** with **`--machine-cidr`** if you override the default (**`10.0.0.0/16`**).

## Authentication

```bash
rosa login                          # browser-based OCM login (stores token)
rosa login --token=<offline-token>  # non-interactive (CI/CD)
rosa whoami                         # verify logged-in identity
rosa token                          # print current OCM token
```

Offline tokens are obtained at <https://console.redhat.com/openshift/token>.

## Classic Cluster Lifecycle

Before `rosa create cluster` (Classic / STS paths), read **`## rosa create cluster`** and any related IAM/OIDC helper commands you will run in [commands-reference.md](commands-reference.md).

**Default networking:** see [Networking: Classic default vs HCP](#networking-classic-default-vs-hcp). The sample below omits `--subnet-ids` on purpose (installer-provisioned path); if you pass subnet/VPC flags, treat it as BYO and read every related flag in the reference.

### 1. Pre-flight (once per AWS account)

```bash
rosa verify quota --region=us-east-1
rosa verify permissions
rosa create account-roles --mode=auto --yes   # creates IAM roles
```

### 2. Create cluster (STS — recommended)

**Ordering:** Classic STS differs from **HCP**—here OIDC config precedes **cluster**, then Operator roles and **`rosa create oidc-provider`** reference the cluster.

```bash
rosa create oidc-config --mode=auto --yes
rosa create cluster \
  --cluster-name=mycluster \
  --region=us-east-1 \
  --sts \
  --mode=auto \
  --yes
rosa create operator-roles --cluster=mycluster --mode=auto --yes
rosa create oidc-provider   --cluster=mycluster --mode=auto --yes
rosa logs install --cluster=mycluster --watch
```

### 3. Add an admin user

```bash
rosa create admin --cluster=mycluster
```

### 4. Upgrade

```bash
rosa list upgrades --cluster=mycluster
rosa upgrade cluster --cluster=mycluster --version=4.15.12 --schedule-date=2025-06-01
```

On **HCP**, control plane and **machine pools** can follow **different** upgrade schedules than on Classic (where the cluster tends to move together); confirm supported operations and flags under **`## rosa upgrade`** and machine‑pool upgrade headings in [commands-reference.md](commands-reference.md).

### 5. Delete

Wait until **`rosa delete cluster`** finishes before tearing down IAM—account‑wide roles are still needed during cleanup; Operators need **cluster‑scoped** roles and the **OIDC provider** until AWS objects are gone.

**This repository:** **`make destroy-classic`** runs **`clusters/classic/destroy.sh`**, which waits for uninstall then runs **`rosa delete operator-roles`** and **`rosa delete oidc-provider`** using the cluster **id** captured before teardown (prefer that over re‑teaching manual steps).

```bash
rosa delete cluster --cluster=mycluster --watch
rosa delete operator-roles --cluster=<cluster-id> --mode=auto --yes
rosa delete oidc-provider --cluster=<cluster-id> --mode=auto --yes
```

(`rosa delete cluster` suggests this order when it prints follow‑up commands; **`--cluster`** accepts the OCM cluster id.)

Use **`--prefix=<operator_roles_prefix>`** instead of **`--cluster`** when removing Operator roles tied to a **reusable OIDC config** without a cluster reference—see **`### rosa delete operator-roles`** in [commands-reference.md](commands-reference.md). Run **`rosa delete account-roles`** **only** when **no** other cluster in the account shares that account‑role prefix/policies.

## HCP Cluster Lifecycle

**Terraform in this workspace:** provisioning and teardown for benchmarks use **`make create-hcp`** / **`make destroy-hcp`** only — they shell out to **`clusters/hcp/terraform`** and do **not** run **`rosa create cluster`** / **`rosa delete cluster`** against HCP. Keep local Terraform **state** safe; **`destroy-hcp`** fails without **`clusters/hcp/terraform/terraform.<cluster>.tfstate`**.

The **`rosa` CLI** material below describes the **underlying** STS/OIDC/subnet order that validated-pattern Terraform implements; reach for **`rosa`** tasks that remain CLI-only (**`rosa logs`**, **machine pools**, **ingress**, **quota checks**, **`rosa describe cluster`** for polling, **`rosa token`** feeding **`RHCS_TOKEN`**) or when working **outside** this repository’s benchmark harness.

**Before any scripted `rosa` HCP flow (elsewhere):** read **`## rosa create cluster`**, **`## rosa create operator-roles`**, and **`## rosa create oidc-config`** in [commands-reference.md](commands-reference.md). Hosted clusters require **`--subnet-ids`** in **your** VPC; **`--private`** forces private‑only networking—then supply **only private** subnets.

**Sizing and limits (HCP):** expect at least **2 worker nodes**; hosted clusters support large fleets—product guides commonly cite **500 worker nodes** as an upper bound per cluster (limits evolve by version, so validate with `rosa`/`ocm` output or current release notes before designing at the edge). Do **not** stop or “pause” worker EC2 instances from the AWS console—unsupported and risks data loss or broken scheduling.

**Defaults you may override:** quick‑start defaults often include **single‑zone** worker pools, **`m5.xlarge`** workers × **2**, **public** API/ingress, **`gp3`** root volumes (~**300 GiB**), and machine/service/pod CIDR blocks centered on **`10.0.0.0/16`** / **`172.30.0.0/16`** / **`10.128.0.0/14`**—reserve **`172.20.0.1`** for the internal Kubernetes API address (do not collide). Long **`--cluster-name`** values auto‑truncate into DNS labels; **`--domain-prefix`** caps at **15** chars and is **immutable**.

### Terraform (`clusters/hcp/terraform`) — IaC stack in this repo

When the user wants **ROSA with HCP** provisioned with **Terraform** (or you are choosing between CLI and IaC here), use the root stack at **`clusters/hcp/terraform/`** in this workspace.

- **Do not** assume a local **`references/`** tree exists. That directory is **gitignored** and is often absent after clone; configs under it are **not** the durable source of truth for agents or CI.
- **`clusters/hcp/terraform`** wires **`network-public`**, **`iam`**, and **`cluster`** from **`https://github.com/rh-mobb/validated-pattern-terraform-rosa`** (see **`clusters/hcp/terraform/main.tf`** for exact `git::…` sources). Pin **`?ref=`** to a **commit SHA** in all three module blocks when you need reproducible applies.
- **Operator flow:** follow **`clusters/hcp/terraform/README.md`**. Typical benchmark path: **`make create-hcp`**, which runs **`clusters/hcp/create.sh`** (Terraform **init**/**apply**) and writes **`terraform.<cluster>.tfstate`** plus auto-generated **`clusters/hcp/terraform/.generated.<cluster>.tfvars`**. Optionally set **`RHCS_TOKEN`**, export **`rosa token`**, pin refs in **`main.tf`**, maintain **`.terraform.lock.hcl`**.

#### Agents: HCP Terraform apply / init — intermittent failures & retries

**Harness behavior:** **`clusters/hcp/lib-terraform.sh`** runs **`terraform init`** once, then **`hcp_terraform_apply_retry_on_ocm_403`** for every **`terraform apply`** (phased **phase 1**, **phase 2**, or single-shot). That wrapper **re-runs apply after `ROSA_HCP_TERRAFORM_403_RETRY_SLEEP_SEC`** (default **90**) when stderr includes **`CLUSTERS-MGMT-403`**, **`Forbidden access`**, or **`status is 403`**, up to **`ROSA_HCP_TERRAFORM_403_MAX_RETRIES`** (default **5**) per phase — mitigating the **transient OCM race** when machine pools / IDP mutate immediately after the cluster object exists. **`terraform init`** is **not** retried by this loop.

After **`make create-hcp`** or **`clusters/hcp/create.sh`** exits non‑zero (or tooling times out):

- **Read** the **`terraform`** / provider output the user captured (or rerun **`terraform apply -input=false -auto-approve -var-file=…`** under **`clusters/hcp/terraform`** with the same **`-backend-config=path=terraform.<cluster>.tfstate`** after **`terraform init`** if you are resuming manually — mirror **`hcp_run_terraform_apply`** in **`clusters/hcp/lib-terraform.sh`**).
- **Safe to retry** (same inputs, backoff, generous **`block_until_ms`**) when output suggests **infrastructure flake**: e.g. **Plugin did not respond**, gRPC / **Early EOF**, **connection reset**, **timeouts**, transient **503/504**, **`context deadline exceeded`** without a durable **`CLUSTERS-MGMT`** / **`AccessDenied`** cause.
- **`CLUSTERS-MGMT-403` on pools / identity provider:** the harness **already retried** in-process; one or two **manual** **`terraform apply`** passes with the same state is still reasonable for the same race. **Do not** assume permanent **RBAC** denial until **all** scripted retries + a manual apply have failed.
- **Do not** blindly retry when you see other **`CLUSTERS-MGMT-*`**, **`Cannot upgrade cluster`** / **`openshift_version`** skew, **`InsufficientInstanceCapacity`**, **`AccessDenied`** (IAM), or clear **validation** errors — **fix** **`tfvars`** / quotas / **`RHCS_TOKEN`**, then rerun.
- **Partial apply:** Terraform retains state — a follow‑up **`terraform apply`** with the **same backend and var‑file** is usually correct once the blocker is cleared; **`make create-hcp`** alone may **fail early** if the cluster row already exists in OCM (**`rosa describe`**), so prefer **manual** **`apply`** continuation when halfway through provisioning.

(This section complements **Agents: HCP Terraform destroy — auth, interruptions, refresh failures** below.)

#### Agents: HCP Terraform destroy — auth, interruptions, refresh failures

Operational detail for **`clusters/hcp/destroy.sh`** / **`make destroy-hcp`** (implemented in **`clusters/hcp/lib-terraform.sh`**: **`hcp_run_terraform_destroy`**):

- **`ensure_rhcs_token`:** if **`RHCS_TOKEN`** is unset, the harness runs **`rosa token`**. Detached shells (e.g. **`nohup`** without inherited env, non-interactive wrappers) often **lack** refreshable **`rosa`** credentials → token export fails. **Agents:** Before background or headless teardown, persist **`RHCS_TOKEN`** into the subprocess environment **or** only run **`destroy.sh`** where **`rosa token`** succeeds in-process.
- **Interrupted destroy:** a partial run can delete the **`rhcs_cluster`** and cluster-scoped SGs **before** VPC/IAM teardown completes. **Refresh** during a later **`terraform destroy`** may evaluate **`data.aws_security_groups.cluster_default`** → **empty** **`ids`** → **Invalid index** (e.g. EFS rules). **Hands-off recovery (this repo):** from the repo root, **`printf '%s\n' "${ROSA_CLUSTER_NAME_HCP}" | make destroy-hcp ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH=1`** — **`hcp_run_terraform_destroy`** adds **`-refresh=false`** when that variable is set (**`clusters/hcp/lib-terraform.sh`**). **Do not** ask the user for this flag; agents retry per **`benchmark-run-all`** → **Agents — HCP destroy**. **Last resort** if **`make`** still fails: **`cd clusters/hcp/terraform`**, **`terraform init -input=false -backend-config="path=terraform.<cluster>.tfstate"`** **‑reconfigure**, same **`-var-file=.generated.<cluster>.tfvars`**, **`TF_VAR_admin_password_override`**, **`RHCS_TOKEN`**, **`terraform destroy -refresh=false -input=false -auto-approve …`**.
- **OCM machine-pool deletion warnings** (e.g. “last node pool can not be deleted” with resources dropped from state / ignore-deletion): treat as upstream module behavior during destroy; continuation or rerun may still converge **if** **`rhcs_cluster`** removal progresses.
- **Long wall-clock:** HCP destroys can exceed tens of minutes; agent shell timeouts that **SIGINT** Terraform leave stacks in ambiguous states (**above** applies). Prefer one uninterrupted **`destroy`** run with tooling **`block_until_ms`** sized generously, **or** user-approved background execution with **`RHCS_TOKEN`** already exported.

The **numbered ROSA CLI steps** under **### 1. VPC** onward are reference / troubleshooting—they are **not** how **`make create-hcp`** installs this repo's HCP cluster.

### 1. VPC (optional helper)

```bash
# Minimal CloudFormation VPC — subnet IDs appear in stack output (often public + private)
rosa create network --mode=auto --yes
# or explicit template + params:
rosa create network rosa-quickstart-default-vpc \
  --mode=auto --yes \
  --param Region=us-east-1 \
  --param Name=my-hcp-network \
  --param AvailabilityZoneCount=1 \
  --param VpcCidr=10.0.0.0/16
```

Tag BYO subnets per [Subnet tags (BYO VPC)](#subnet-tags-byo-vpc).

### 2. Account roles, OIDC config, Operator roles (HCP)

```bash
rosa create account-roles --hosted-cp --mode=auto --yes
export ACCOUNT_ROLES_PREFIX=HCP-ROSA   # or the prefix you chose / were assigned
export OPERATOR_ROLES_PREFIX=myoperators   # any stable label you choose for this Operator-role bundle

rosa create oidc-config --mode=auto --yes
export OIDC_ID=<oidc_config_id_from_output>

rosa create operator-roles --hosted-cp --mode=auto --yes \
  --prefix="$OPERATOR_ROLES_PREFIX" \
  --oidc-config-id="$OIDC_ID" \
  --installer-role-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:role/${ACCOUNT_ROLES_PREFIX}-HCP-ROSA-Installer-Role"
```

### 3. Create cluster (HCP)

```bash
# Public API/ingress example: comma-separated subnet IDs from your VPC/stack (often public,private)
rosa create cluster \
  --cluster-name=myhcp \
  --mode=auto --yes --sts --hosted-cp \
  --operator-roles-prefix "$OPERATOR_ROLES_PREFIX" \
  --oidc-config-id "$OIDC_ID" \
  --subnet-ids subnet-public-aaa,subnet-private-bbb

# Private variant adds --private and private-only subnets
rosa logs install --cluster=myhcp --watch
rosa describe cluster --cluster=myhcp
```

Optional **`--external-id`** appears in hardened org policies. Use **`--machine-cidr`** when your VPC does **not** align with **`10.0.0.0/16`**.

### 4. Delete (HCP)

Finish cluster deletion **before** removing IAM—Operators still need STS/OIDC during teardown.

```bash
rosa delete cluster --cluster=myhcp --watch
rosa delete oidc-provider --cluster=myhcp --mode=auto --yes
rosa delete operator-roles --cluster=myhcp --mode=auto --yes
rosa delete account-roles --prefix "$ACCOUNT_ROLES_PREFIX" --mode=auto --yes  # only if unused elsewhere
```

Detach leftover IAM **policies** only when your teams created extra attachments beyond what `rosa` manages (otherwise rely on **`--mode auto`** cleanup). Default account prefixes include **`HCP-ROSA`** and legacy **`ManagedOpenShift`**—match the prefix you actually created.

**HCP admin access:** Normal cluster admins use OpenShift RBAC. ROSA includes a **`dedicated-admin`** OpenShift group for customer administrators who must manage quotas, NetworkPolicy, Operators from the catalog, and related day‑2 controls without full AWS/IAM access—that model pairs with **`rosa`** IDP and group membership workflows. **`rosa create admin`** remains the usual path for a **time‑limited cluster‑admin kubeconfig** when breaking glass is acceptable.

### Grant/revoke RBAC for IdP users (cluster-admin / dedicated-admin)

After **`rosa create idp`** and user login identities exist:

```bash
rosa grant user cluster-admin    --user=<idp_username> --cluster=myhcp
rosa grant user dedicated-admin  --user=<idp_username> --cluster=myhcp
rosa list users --cluster=myhcp

rosa revoke user cluster-admin   --user=<idp_username> --cluster=myhcp
rosa revoke user dedicated-admin --user=<idp_username> --cluster=myhcp
```

Node pools (HCP: still **`machinepool`** in `rosa`):

```bash
rosa create  machinepool --cluster=myhcp --name=extra --replicas=2 --instance-type=m5.xlarge
rosa list    machinepools --cluster=myhcp
rosa edit    machinepool  --cluster=myhcp --name=extra --replicas=4
rosa delete  machinepool  --cluster=myhcp --name=extra --yes
```

## Machine Pools (Classic)

```bash
rosa create machinepool --cluster=mycluster --name=high-mem \
  --instance-type=r5.2xlarge --replicas=3
rosa edit   machinepool --cluster=mycluster --name=high-mem --replicas=5
rosa list   machinepools --cluster=mycluster
rosa delete machinepool  --cluster=mycluster --name=high-mem --yes
```

## Autoscaler

```bash
# Cluster-level autoscaler
rosa create autoscaler --cluster=mycluster \
  --min-replicas=2 --max-replicas=10
rosa describe autoscaler --cluster=mycluster
rosa edit     autoscaler --cluster=mycluster --max-replicas=20
rosa delete   autoscaler --cluster=mycluster --yes
```

## Identity Providers (IDP)

```bash
rosa list   idps   --cluster=mycluster
rosa create idp    --cluster=mycluster --type=github --name=gh-idp
rosa delete idp    --cluster=mycluster --name=gh-idp --yes
```

Supported types commonly include **GitHub**, **GitHub Enterprise**, **GitLab**, **Google**, **htpasswd**, **LDAP**, and **OpenID Connect**—confirm allowed **`--type`** strings and flags in [commands-reference.md](commands-reference.md).

## Common Flags

| Flag | Commands | Purpose |
|------|----------|---------|
| `--cluster / -c` | most resource commands | cluster name or ID |
| `--region` | create, verify, list | AWS region (or `AWS_REGION` env var) |
| `--mode=auto` | IAM/STS commands | apply changes automatically (no manual steps) |
| `--yes / -y` | destructive commands | skip confirmation prompt |
| `--interactive / -i` | create commands | guided wizard mode |
| `--watch` | logs | stream logs until completion |
| `--output json` | list, describe | machine-readable output |
| `--debug` | all | verbose HTTP/API logging |
| `--profile` | AWS commands | use named AWS credentials profile |

## Full command reference

Authoritative syntax: [commands-reference.md](commands-reference.md).

Search inside that file by heading: `## rosa <verb> <resource>` (e.g., `## rosa create cluster`, `## rosa create operator-roles`). Subcommands such as **`rosa create network`** appear under `### rosa create network`.
