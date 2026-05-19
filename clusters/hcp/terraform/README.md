# ROSA HCP (public, multi-AZ) — Terraform (`clusters/hcp/terraform`)

Benchmark harness stack; used by **`clusters/hcp/create.sh`** and **`clusters/hcp/destroy.sh`**.

This directory is meant to live in Git **without** a local `references/` copy.
It wires together three modules from **[rh-mobb/validated-pattern-terraform-rosa](https://github.com/rh-mobb/validated-pattern-terraform-rosa)** pulled over **HTTPS Git** at `?ref=main`.

## Pinning modules

Terraform does **not** allow variables inside `module.source`. To update the pin, edit **`main.tf`** and replace the SHA on **all three** `module "…" { source = "…?ref=…" }` lines with the same new SHA or tag.

Currently pinned to **`d6ae385`** — "fix: use cluster-total min/max replicas for rhcs_cluster_rosa_hcp autoscaling": passes `autoscaling_enabled` and cluster-**total** `min_replicas` / `max_replicas` (= per-pool × num AZs) to `rhcs_cluster_rosa_hcp` at creation time. This ensures default pools are autoscaling-enabled from day one and the subsequent `rhcs_hcp_machine_pool` reconciliation is a no-op, eliminating the `CLUSTERS-MGMT-403` race on multi-AZ clusters. The previous pin (`07b724e`) incorrectly used per-pool values, causing a 400 error on multi-AZ clusters.

## Variables root file

[`variables.generated.tf`](variables.generated.tf) is synced from upstream `terraform/01-variables.tf` plus **root-level** machine-pool knobs (`default_min_replicas`, `default_max_replicas`). Refresh instructions are in that file header.

Example apply settings: [`terraform.tfvars.example`](terraform.tfvars.example) (defaults to **≈6–12 workers** via **2–4 replicas per AZ** × 3 pools, **`m5.large`**).

## Prerequisites

- **AWS** credentials for the install account.
- **`RHCS_TOKEN`** (or service account equivalents) — see validated-pattern README.

## Apply strategy

**`clusters/hcp/create.sh`** runs a **single-shot** `terraform apply` via **`lib-terraform.sh`**. Terraform resolves the dependency graph internally. If OCM returns a transient **CLUSTERS-MGMT-403** the apply is retried (configurable via **`ROSA_HCP_TERRAFORM_403_MAX_RETRIES`** / **`ROSA_HCP_TERRAFORM_403_RETRY_SLEEP_SEC`** in **`hcp.env`**).

## Commands

From **this directory**:

```bash
terraform init -backend-config="path=terraform.tfstate"
terraform plan  -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

Copy `terraform.tfvars.example` → `terraform.tfvars` before apply (and tune `cluster_name`, `region`).

Retrieve admin password (**after** Secret version is populated for your apply mode):

```bash
aws secretsmanager get-secret-value --secret-id "$(terraform output -raw admin_password_secret_arn)" \
  --query SecretString --output text
```

## Provider lockfile

Commit [`.terraform.lock.hcl`](.terraform.lock.hcl) so installs stay reproducible.
