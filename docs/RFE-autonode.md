# RFE: Native AutoNode (Karpenter) Support in validated-pattern-terraform-rosa

**Project:** [rh-mobb/validated-pattern-terraform-rosa](https://github.com/rh-mobb/validated-pattern-terraform-rosa)
**Feature area:** `modules/infrastructure/cluster` — ROSA HCP cluster module

## Summary

Add first-class support for provisioning a ROSA HCP cluster with AutoNode (Karpenter) enabled. Today, enabling AutoNode requires several manual post-Terraform steps that cannot be expressed in the existing module surface. The goal of this RFE is to bring those steps into the module so that a single `terraform apply` produces a fully operational Karpenter-managed cluster.

## Background

AutoNode is Red Hat's managed Karpenter offering for ROSA HCP (currently in Private Preview, targeting GA with OCP 4.19+). It replaces Cluster Autoscaler with Karpenter for node provisioning, providing significantly faster scale-up by using the EC2 Fleet API instead of the Machine API / Auto Scaling Group path.

Enabling AutoNode today requires:

1. Placing the cluster on a specific HyperShift management shard (via `provision_shard_id` in the OCM cluster properties).
2. Creating a dedicated Karpenter IAM permission policy and IRSA role.
3. Attaching an `ec2:CreateTags` inline policy to the existing control-plane-operator IAM role so HyperShift can auto-tag the default security group for Karpenter discovery.
4. Tagging private subnets with `karpenter.sh/discovery=<cluster-id>`.
5. Tagging the default security group with `karpenter.sh/discovery=<cluster-id>`.
6. Calling `rosa edit cluster --autonode=enabled --autonode-iam-role-arn=<arn>`.

Steps 2–6 are currently scripted outside Terraform in [`clusters/hcp-autonode/create.sh`](../clusters/hcp-autonode/create.sh). Step 1 is already possible via the `additional_cluster_properties` variable added in commit `28b2933`.

## Current Workaround

This repository maintains a separate Terraform stack at `clusters/hcp-autonode/terraform/` that:

- Uses the same three modules (`network_public`, `iam`, `cluster`) pinned to ref `28b293329af938f1f7b5662e7223831eee0df506`.
- Passes `additional_cluster_properties = { provision_shard_id = "<shard-id>" }` into `module "cluster"` to land the cluster on the AutoNode-enabled management shard.
- After `terraform apply`, runs a bash script that performs steps 2–6 using `aws` and `rosa` CLI calls.

The generated tfvars used for the benchmark harness are representative of a minimal AutoNode cluster:

```hcl
cluster_name          = "an-bench"
region                = "us-east-1"
network_type          = "public"
private               = false
zero_egress           = false
vpc_cidr              = "10.1.0.0/16"
multi_az              = false
openshift_version     = "4.19.30"
default_instance_type = "m5.xlarge"
default_min_replicas  = 2
default_max_replicas  = 2
additional_machine_pools     = {}
persists_through_sleep       = true
enable_gitops_bootstrap      = false
enable_persistent_dns_domain = false
# ... other feature flags set to false ...
additional_cluster_properties = {
  provision_shard_id = "9f11dd2b-98c1-11f0-8fe5-0a580a830a08"
}
```

## Requested Changes

### 1. `modules/infrastructure/cluster` — expose `additional_cluster_properties`

This is already done in `28b2933`. No further change needed here.

### 2. `modules/infrastructure/iam` — add AutoNode IAM resources

Add an `enable_autonode` boolean variable (default `false`). When `true`, create:

**a. AutoNode permission policy** (`<prefix>-autonode-policy`):

The policy must grant Karpenter the following capabilities, all scoped to `karpenter.sh/nodepool` and `karpenter.k8s.aws/ec2nodeclass` resource tags where applicable:

| Sid | Actions | Resources |
|-----|---------|-----------|
| `AllowScopedEC2InstanceAccessActions` | `ec2:RunInstances`, `ec2:CreateFleet` | images, snapshots, security groups, subnets |
| `AllowScopedEC2LaunchTemplateAccessActions` | `ec2:RunInstances`, `ec2:CreateFleet` | launch templates |
| `AllowScopedEC2InstanceActionsWithTags` | `ec2:RunInstances`, `ec2:CreateFleet`, `ec2:CreateLaunchTemplate` | fleet, instance, volume, NIC, launch-template, spot-request — conditioned on `karpenter.sh/nodepool` request tag |
| `AllowScopedResourceCreationTagging` | `ec2:CreateTags` | same resource set — conditioned on CreateAction + `karpenter.sh/nodepool` request tag |
| `AllowScopedResourceTagging` | `ec2:CreateTags` | instances — conditioned on `karpenter.sh/nodepool` resource tag |
| `AllowScopedDeletion` | `ec2:TerminateInstances`, `ec2:DeleteLaunchTemplate` | instances, launch templates — conditioned on `karpenter.sh/nodepool` resource tag |
| `AllowRegionalReadActions` | `ec2:Describe*` (images, instances, types, launch templates, SGs, spot prices, subnets) | `*` |
| `AllowSSMReadActions` | `ssm:GetParameter` | `arn:*:ssm:*::parameter/aws/service/*` |
| `AllowPricingReadActions` | `pricing:GetProducts` | `*` |
| `AllowInterruptionQueueActions` | `sqs:DeleteMessage`, `sqs:GetQueueUrl`, `sqs:ReceiveMessage` | `*` |
| `AllowPassingInstanceRole` | `iam:PassRole` | any role — conditioned on `iam:PassedToService=ec2.amazonaws.com` |
| `AllowScopedInstanceProfileCreationActions` | `iam:CreateInstanceProfile` | instance profiles — conditioned on `karpenter.k8s.aws/ec2nodeclass` request tag |
| `AllowScopedInstanceProfileTagActions` | `iam:TagInstanceProfile` | instance profiles — conditioned on both request and resource `karpenter.k8s.aws/ec2nodeclass` tags |
| `AllowScopedInstanceProfileActions` | `iam:AddRoleToInstanceProfile`, `iam:RemoveRoleFromInstanceProfile`, `iam:DeleteInstanceProfile` | instance profiles — conditioned on `karpenter.k8s.aws/ec2nodeclass` resource tag |
| `AllowInstanceProfileReadActions` | `iam:GetInstanceProfile` | instance profiles |

**b. AutoNode IRSA role** (`<prefix>-autonode-operator-role`):

Trust policy using `sts:AssumeRoleWithWebIdentity` from the cluster OIDC provider, scoped to:

```json
{
  "<oidc-provider-url>:sub": "system:serviceaccount:kube-system:karpenter"
}
```

Requires the OIDC endpoint URL as an input (already available from `module.iam.oidc_endpoint_url` in the cluster module).

**c. `ec2:CreateTags` inline policy on the control-plane-operator role:**

The existing `<cluster-name>-kube-system-control-plane-operator` role (created by the `iam` module) needs an inline policy that allows HyperShift to auto-tag the default security group with `karpenter.sh/discovery=<cluster-id>`. Without this, `ec2nodeclass/default` will show `SecurityGroupsReady=False`.

```json
{
  "Sid": "AllowCreateTagsOnRedHatManagedResources",
  "Effect": "Allow",
  "Action": ["ec2:CreateTags"],
  "Resource": "*",
  "Condition": {
    "StringEquals": { "aws:ResourceTag/red-hat-managed": "true" }
  }
}
```

**Suggested module outputs to add:**

- `autonode_policy_arn`
- `autonode_role_arn`

### 3. `modules/infrastructure/cluster` — subnet and security group tagging

When `enable_autonode = true`, tag resources for Karpenter discovery after the cluster is created. The tag key/value is `karpenter.sh/discovery=<cluster-id>`.

Resources to tag:

- All private subnets (identifiable by `kubernetes.io/cluster/<cluster-id>=shared` and `kubernetes.io/role/internal-elb` tags applied by ROSA at install time).
- The default security group (identifiable by name `<cluster-id>-default-sg`).

This can be implemented using the `scottwinkler/shell` provider (already a dependency in the stack) or `aws_ec2_tag` resources — whichever fits the existing module patterns.

### 4. `modules/infrastructure/cluster` — invoke `rosa edit cluster --autonode`

After the cluster is `ready` and the IRSA role ARN is known, call:

```
rosa edit cluster -c <cluster-name> --autonode=enabled --autonode-iam-role-arn=<arn>
```

This can be expressed as a `null_resource` or `shell` resource (using the `scottwinkler/shell` provider) with a `depends_on` on the cluster resource and the IRSA role. The IRSA role ARN can be threaded in from the `iam` module output.

## Known Constraints (Private Preview)

- `AWS_REGION` must be `us-east-1`.
- `provision_shard_id` must be set to `9f11dd2b-98c1-11f0-8fe5-0a580a830a08` for the current preview shard.
- The RHCS Terraform provider returns `403 Forbidden` when creating identity providers (HTPasswd IDPs) via the `cluster` module against the AutoNode shard. A fallback to `rosa create idp` via CLI is needed until this is resolved in the provider or the shard configuration.
- ROSA CLI version ≥ 1.2.57 is required for `--autonode` flags on `rosa edit cluster`.
- OCP version ≥ 4.19 is required.

## Suggested Variable Interface

```hcl
# In modules/infrastructure/iam/variables.tf
variable "enable_autonode" {
  description = "Create Karpenter IAM policy and IRSA role for AutoNode (ROSA HCP Private Preview)."
  type        = bool
  default     = false
}

variable "autonode_oidc_provider_url" {
  description = "OIDC provider URL (without https://) for the Karpenter IRSA trust policy. Required when enable_autonode = true."
  type        = string
  default     = null
}

variable "autonode_cluster_id" {
  description = "OCM cluster ID used for subnet/SG discovery tagging. Required when enable_autonode = true."
  type        = string
  default     = null
}
```

```hcl
# In modules/infrastructure/cluster/variables.tf
variable "enable_autonode" {
  description = "Tag subnets and security groups for Karpenter discovery and call rosa edit cluster --autonode=enabled."
  type        = bool
  default     = false
}

variable "autonode_iam_role_arn" {
  description = "ARN of the Karpenter IRSA role. Required when enable_autonode = true."
  type        = string
  default     = null
}
```

## Testing Reference

This benchmark harness has run `create-hcp-autonode` end-to-end against the current private preview shard and validated:

- `ec2nodeclass/default` reaches `Ready=True`
- `openshiftec2nodeclass/default` reaches `Ready=True`
- Karpenter provisions nodes from Pending → Ready in ~60–90 s for a 3-node scale event (vs ~4–5 min for CAS on Classic)

Timing and verification data are in `results/` and `reports/` of this repository.

## References

- [`clusters/hcp-autonode/create.sh`](../clusters/hcp-autonode/create.sh) — current manual setup script
- [`clusters/hcp-autonode/terraform/main.tf`](../clusters/hcp-autonode/terraform/main.tf) — AutoNode-specific Terraform stack
- [`clusters/hcp-autonode/lib-terraform.sh`](../clusters/hcp-autonode/lib-terraform.sh) — tfvars generation and Terraform helpers
- [`references/autonode/`](../references/autonode/) — AutoNode architecture and scaling test references
- [validated-pattern-terraform-rosa on GitHub](https://github.com/rh-mobb/validated-pattern-terraform-rosa)
