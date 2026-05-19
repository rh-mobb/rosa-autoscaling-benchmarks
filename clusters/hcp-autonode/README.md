# ROSA HCP AutoNode (Karpenter)

> **Status: Private Preview** — us-east-1 only, ROSA CLI ≥ 1.2.57, OCP ≥ 4.19.

AutoNode replaces the Cluster Autoscaler with Karpenter for ROSA HCP clusters.
This directory (`clusters/hcp-autonode/`) is the canonical home for the AutoNode stack.
The alias `clusters/hcp-karpenter/` is a symlink to this directory — both names are valid
(AutoNode is the Red Hat product name; Karpenter is the upstream project).

## Structure

| File | Purpose |
|------|---------|
| `create.sh` | Provision ROSA HCP + AutoNode end-to-end (Terraform + IAM + shard + enable) |
| `destroy.sh` | Drain Karpenter resources then destroy via Terraform |
| `lib-terraform.sh` | Terraform helpers — points to `terraform/` in this directory; injects `provision_shard_id` |
| `terraform/` | Dedicated Terraform stack (separate from `clusters/hcp/terraform/`) |

## Key differences from `clusters/hcp/`

| Setting | `clusters/hcp/` | `clusters/hcp-autonode/` |
|---------|-----------------|--------------------------|
| Terraform stack | `hcp/terraform/` | `hcp-autonode/terraform/` |
| `additional_cluster_properties` | Not set | `provision_shard_id` injected via `AUTONODE_SHARD_ID` |
| Multi-AZ | Supported | Single-AZ only (AutoNode shard rejects machine pool autoscaling updates) |
| Default pool replicas | Autoscaling min/max | Fixed 2 replicas (Karpenter owns scaling) |
| Admin user | Terraform IDP resource | Same (Terraform htpasswd IDP) |
| Post-cluster steps | None | IAM role + policy, subnet/SG tagging, `rosa edit cluster --autonode=enabled`, CRD verification |

## Cluster name limit

ROSA HCP operator roles use the cluster name as a prefix. The longest suffix
(`-openshift-cluster-csi-drivers-ebs-cloud-credentials`) is 52 chars, so cluster names
must be **≤ 12 characters** to stay within IAM's 64-char role name limit.

## Lifecycle

```bash
# Configure
cp autonode.env.example autonode.env   # or: make init-env
# Edit autonode.env: ROSA_CLUSTER_NAME_AUTONODE, AUTONODE_PREFIX, AUTONODE_SHARD_ID

# Provision (30–60 min)
make create-hcp-autonode

# Destroy (20–30 min)
make destroy-hcp-autonode
```

## References

- [ROSA HCP AutoNode KCS](../../references/autonode/)
- [Karpenter upstream docs](https://karpenter.sh/docs/)
- Benchmark skill: `.cursor/skills/benchmark-create-hcp-autonode/`
