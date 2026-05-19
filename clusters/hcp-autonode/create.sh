#!/usr/bin/env bash
# clusters/hcp-autonode/create.sh — Provision ROSA HCP with AutoNode (Karpenter) enabled.
#
# AutoNode is a Private Preview feature (ROSA CLI ≥ 1.2.57, OCP ≥ 4.19, us-east-1 only).
# Uses a dedicated Terraform stack (clusters/hcp-autonode/terraform/) that injects
# provision_shard_id via additional_cluster_properties to land the cluster on the
# AutoNode-enabled HyperShift management shard.
#
#   Phase 1 — Terraform provisions VPC + IAM + HCP cluster with shard injection.
#   Phase 2 — AutoNode IAM setup (policy + role), subnet/SG Karpenter discovery tagging,
#              and `rosa edit cluster --autonode=enabled`.
#              TODO(GA): These steps should become part of the standard HCP create flow
#              (or a Terraform resource) once AutoNode exits private preview. Tracked in
#              the repo as a known manual step until the RHCS provider supports it.
#   Phase 3 — Post-ready milestones (oc login, workers, operators, CRD verification).
#
# Prerequisites: autonode.env (make init-env), ROSA CLI ≥ 1.2.57, terraform CLI,
#   rosa login + aws sts get-caller-identity success.
#
# Environment — see Makefile (autonode.env) plus:
#   AUTONODE_PREFIX          — IAM resource name prefix (required, e.g. "autonode")
#   AUTONODE_SHARD_ID        — OCM provision shard for AutoNode preview (default: 9f11dd2b-...)
#   AWS_ACCOUNT_ID           — Auto-detected via aws sts get-caller-identity if unset
#   ROSA_HCP_TERRAFORM_VAR_FILE — optional path to full .tfvars (skips generated varfile)
#   ROSA_HCP_MAX_POOL_REPLICAS  — per-pool Terraform max_replicas (falls back to AUTOSCALE_MAX_REPLICAS)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clusters/common.sh
source "${SCRIPT_DIR}/../common.sh"
# shellcheck source=clusters/hcp-autonode/lib-terraform.sh
source "${SCRIPT_DIR}/lib-terraform.sh"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_ADMIN_PASSWORD="${CLUSTER_ADMIN_PASSWORD:?CLUSTER_ADMIN_PASSWORD must be set (min 14 chars, upper+lower+digit/symbol)}"
AUTONODE_PREFIX="${AUTONODE_PREFIX:?AUTONODE_PREFIX must be set (IAM resource prefix, e.g. autonode)}"
AUTONODE_SHARD_ID="${AUTONODE_SHARD_ID:-9f11dd2b-98c1-11f0-8fe5-0a580a830a08}"
export AUTONODE_SHARD_ID

# AutoNode private preview requires us-east-1.
if [[ "${AWS_REGION}" != "us-east-1" ]]; then
  fail "AutoNode private preview is only available in us-east-1 (AWS_REGION=${AWS_REGION})."
fi

acquire_cluster_create_lock "hcp-autonode" "${ROSA_CLUSTER_NAME}"

# ── Resolve version ────────────────────────────────────────────────────────────
RESOLVED_VERSION="$(resolve_rosa_version hcp)"

# ── Initialise benchmark run ──────────────────────────────────────────────────
init_run "hcp-autonode" "${RESOLVED_VERSION}"

# ── Pre-flight checks ──────────────────────────────────────────────────────────
info "Checking for existing cluster '${ROSA_CLUSTER_NAME}'..."
if rosa describe cluster -c "${ROSA_CLUSTER_NAME}" &>/dev/null; then
  existing_state="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('state','unknown'))")"
  fail "Cluster '${ROSA_CLUSTER_NAME}' already exists (state: ${existing_state}). Aborting."
fi
info "No existing cluster found. Proceeding."

# ── Auto-detect AWS account ID ────────────────────────────────────────────────
if [[ -z "${AWS_ACCOUNT_ID:-}" ]]; then
  AWS_ACCOUNT_ID="$(aws sts get-caller-identity --region "${AWS_REGION}" --query Account --output text)"
  export AWS_ACCOUNT_ID
fi
info "AWS account: ${AWS_ACCOUNT_ID}"

# ── Topology / pool sizing ────────────────────────────────────────────────────
ROSA_HCP_MULTI_AZ_NORM="$(echo "${ROSA_HCP_MULTI_AZ:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
MULTI_AZ_TF="false"
if [[ "${ROSA_HCP_MULTI_AZ_NORM}" == "1" || "${ROSA_HCP_MULTI_AZ_NORM}" == "true" || "${ROSA_HCP_MULTI_AZ_NORM}" == "yes" ]]; then
  MULTI_AZ_TF="true"
fi

declare rep="${ROSA_HCP_REPLICAS:-2}"
[[ "${rep}" =~ ^[0-9]+$ ]] || fail "ROSA_HCP_REPLICAS must be a positive integer (got '${ROSA_HCP_REPLICAS:-}')."
if [[ "${MULTI_AZ_TF}" == "true" ]]; then
  (( rep >= 1 )) || fail "ROSA_HCP_REPLICAS must be at least 1 per AZ for multi-AZ (got ${rep})."
else
  (( rep >= 2 )) || fail "ROSA_HCP_REPLICAS must be at least 2 for single-AZ (got ${rep})."
fi
ROSA_HCP_REPLICAS_EFFECTIVE="${rep}"
declare max_rep="${ROSA_HCP_MAX_POOL_REPLICAS:-${AUTOSCALE_MAX_REPLICAS:-10}}"

# ── Phase 1: Terraform apply (cluster + VPC + IAM) ───────────────────────────
info "Provisioning ROSA HCP via Terraform (shard: ${AUTONODE_SHARD_ID})."
info "additional_cluster_properties will be injected via generated tfvars."

T_START="$(now_ms)"
TERRAFORM_APPLY_OK=true
if ! hcp_run_terraform_apply "${ROSA_CLUSTER_NAME}" "${RESOLVED_VERSION}" "${MULTI_AZ_TF}" "${ROSA_HCP_REPLICAS_EFFECTIVE}" "${max_rep}"; then
  TERRAFORM_APPLY_OK=false
  warn "Terraform apply failed after retries. Checking if cluster exists and is ready..."
  if ! rosa describe cluster -c "${ROSA_CLUSTER_NAME}" &>/dev/null; then
    fail "Terraform apply failed and cluster '${ROSA_CLUSTER_NAME}' does not exist. Cannot continue."
  fi
  existing_state="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('state','unknown'))")"
  if [[ "${existing_state}" != "ready" ]]; then
    fail "Terraform apply failed and cluster '${ROSA_CLUSTER_NAME}' is not ready (state: ${existing_state}). Cannot continue."
  fi
  warn "Cluster '${ROSA_CLUSTER_NAME}' exists and is ready. Continuing with manual setup."
  warn "NOTE: The AutoNode shard blocks Terraform from configuring machine pool autoscaling"
  warn "      and creating identity providers via RHCS provider. Using rosa CLI fallbacks."
fi

# ── Wait for cluster ready ────────────────────────────────────────────────────
info "Waiting for cluster to reach 'ready' state..."
wait_for_cluster_state "${ROSA_CLUSTER_NAME}" "ready" 30

T_READY="$(now_ms)"
emit_timing "hcp.cluster_ready" "${T_START}" "${T_READY}"

# ── Create admin IDP if Terraform failed to do so ────────────────────────────
# The AutoNode shard returns 403 to the Terraform RHCS provider when creating
# identity providers. Fall back to rosa CLI which uses a different API path.
if [[ "${TERRAFORM_APPLY_OK}" == "false" ]]; then
  if ! rosa list idps -c "${ROSA_CLUSTER_NAME}" 2>/dev/null | grep -q "admin"; then
    info "Creating admin htpasswd IDP via rosa CLI (Terraform fallback)..."
    rosa create idp \
      --cluster "${ROSA_CLUSTER_NAME}" \
      --type htpasswd \
      --name admin \
      --users "admin:${CLUSTER_ADMIN_PASSWORD}" || warn "rosa create idp failed; may already exist."
    rosa grant user cluster-admin \
      --user admin \
      --cluster "${ROSA_CLUSTER_NAME}" 2>/dev/null || warn "cluster-admin grant failed; may already be granted."
    info "Sleeping 30s for IDP propagation..."
    sleep 30
  else
    info "Admin IDP already exists — skipping rosa create idp."
  fi
fi

# ── Collect install log milestones (immediately, before logs expire) ──────────
# HCP has no bootstrap node so fewer installer patterns will match, but the raw
# log is still saved for LLM analysis. Fetch immediately — logs may expire soon.
if [[ -n "${BENCHMARK_RUN_ID:-}" ]]; then
  info "Collecting install log milestones (fetching while logs are still available)..."
  python3 "${BENCHMARK_REPO_ROOT}/scripts/collect-install-log-milestones.py" \
    --cluster      "${ROSA_CLUSTER_NAME}" \
    --run-id       "${BENCHMARK_RUN_ID}" \
    --raw-dir      "${BENCHMARK_REPO_ROOT}/results/${BENCHMARK_RUN_ID}/raw" \
    --since-ms     "${T_START}" \
    --prefix       "hcp.install_log" \
    --cluster-type "${CLUSTER_TYPE:-hcp-autonode}" \
    --cluster-name "${ROSA_CLUSTER_NAME}" \
    2>&1 >&2 || warn "Install log milestone collection failed (non-fatal); benchmark results unaffected."
fi

CLUSTER_ID="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))")"
[[ -n "${CLUSTER_ID}" ]] || fail "Could not retrieve cluster ID from rosa describe."
info "Cluster ID: ${CLUSTER_ID}"

API_URL="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('api',{}).get('url',''))")"
[[ -n "${API_URL}" ]] || fail "No API URL in rosa describe after cluster ready."

export_kubeconfig_for_cluster "${ROSA_CLUSTER_NAME}"
info "Using KUBECONFIG=${KUBECONFIG}"

wait_oc_login_success "${API_URL}" "${CLUSTER_ADMIN_PASSWORD}" 30 admin
T_LOGIN="$(now_ms)"
emit_timing "hcp.oc_login_ok" "${T_START}" "${T_LOGIN}"

# Persist cluster state with credentials so other scripts can connect.
write_cluster_state "hcp-autonode" \
  api_url="${API_URL}" \
  cluster_id="${CLUSTER_ID}" \
  username="admin" \
  password="${CLUSTER_ADMIN_PASSWORD}" \
  rosa_version="${RESOLVED_VERSION}" \
  created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  kubeconfig="${KUBECONFIG}" \
  autonode_prefix="${AUTONODE_PREFIX}" \
  autonode_shard_id="${AUTONODE_SHARD_ID}"

# ── Phase 2: AutoNode IAM setup ───────────────────────────────────────────────
info ""
info "Phase 2: AutoNode IAM setup"
info "  Prefix:   ${AUTONODE_PREFIX}"
info "  Shard:    ${AUTONODE_SHARD_ID}"
info ""

mkdir -p "${BENCHMARK_REPO_ROOT}/tmp"
AUTONODE_POLICY_FILE="${BENCHMARK_REPO_ROOT}/tmp/autonode-policy.json"
TRUST_POLICY_FILE="${BENCHMARK_REPO_ROOT}/tmp/${AUTONODE_PREFIX}-trust-policy.json"

# ── 2a: Add ec2:CreateTags to $PREFIX-kube-system-control-plane-operator ──────
# HyperShift needs this to auto-tag the default security group with the cluster ID
# so Karpenter can discover it. Without it SecurityGroupsReady stays False.
CPO_ROLE="${ROSA_CLUSTER_NAME}-kube-system-control-plane-operator"
info "Adding ec2:CreateTags inline policy to ${CPO_ROLE}..."
cat > "${BENCHMARK_REPO_ROOT}/tmp/cpo-createtags.json" <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowCreateTagsOnRedHatManagedResources",
      "Effect": "Allow",
      "Action": ["ec2:CreateTags"],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/red-hat-managed": "true"
        }
      }
    }
  ]
}
POLICY

if aws iam get-role --role-name "${CPO_ROLE}" &>/dev/null; then
  aws iam put-role-policy \
    --role-name "${CPO_ROLE}" \
    --policy-name "AutoNodeCreateTags" \
    --policy-document "file://${BENCHMARK_REPO_ROOT}/tmp/cpo-createtags.json"
  ok "Inline policy attached to ${CPO_ROLE}."
else
  warn "Role ${CPO_ROLE} not found — skipping inline policy. Security group auto-tagging may not work."
  warn "If ec2nodeclass/default shows SecurityGroupsReady=False, attach the policy manually."
fi

# ── 2b: Create AutoNode IAM permission policy ──────────────────────────────────
info "Creating AutoNode IAM permission policy..."
cat > "${AUTONODE_POLICY_FILE}" <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowScopedEC2InstanceAccessActions",
      "Effect": "Allow",
      "Resource": [
        "arn:*:ec2:*::image/*",
        "arn:*:ec2:*::snapshot/*",
        "arn:*:ec2:*:*:security-group/*",
        "arn:*:ec2:*:*:subnet/*"
      ],
      "Action": ["ec2:RunInstances", "ec2:CreateFleet"]
    },
    {
      "Sid": "AllowScopedEC2LaunchTemplateAccessActions",
      "Effect": "Allow",
      "Resource": "arn:*:ec2:*:*:launch-template/*",
      "Action": ["ec2:RunInstances", "ec2:CreateFleet"]
    },
    {
      "Sid": "AllowScopedEC2InstanceActionsWithTags",
      "Effect": "Allow",
      "Resource": [
        "arn:*:ec2:*:*:fleet/*",
        "arn:*:ec2:*:*:instance/*",
        "arn:*:ec2:*:*:volume/*",
        "arn:*:ec2:*:*:network-interface/*",
        "arn:*:ec2:*:*:launch-template/*",
        "arn:*:ec2:*:*:spot-instances-request/*"
      ],
      "Action": ["ec2:RunInstances", "ec2:CreateFleet", "ec2:CreateLaunchTemplate"],
      "Condition": {
        "StringLike": { "aws:RequestTag/karpenter.sh/nodepool": "*" }
      }
    },
    {
      "Sid": "AllowScopedResourceCreationTagging",
      "Effect": "Allow",
      "Resource": [
        "arn:*:ec2:*:*:fleet/*",
        "arn:*:ec2:*:*:instance/*",
        "arn:*:ec2:*:*:volume/*",
        "arn:*:ec2:*:*:network-interface/*",
        "arn:*:ec2:*:*:launch-template/*",
        "arn:*:ec2:*:*:spot-instances-request/*"
      ],
      "Action": "ec2:CreateTags",
      "Condition": {
        "StringEquals": {
          "ec2:CreateAction": ["RunInstances", "CreateFleet", "CreateLaunchTemplate"]
        },
        "StringLike": { "aws:RequestTag/karpenter.sh/nodepool": "*" }
      }
    },
    {
      "Sid": "AllowScopedResourceTagging",
      "Effect": "Allow",
      "Resource": "arn:*:ec2:*:*:instance/*",
      "Action": "ec2:CreateTags",
      "Condition": {
        "StringLike": { "aws:ResourceTag/karpenter.sh/nodepool": "*" }
      }
    },
    {
      "Sid": "AllowScopedDeletion",
      "Effect": "Allow",
      "Resource": [
        "arn:*:ec2:*:*:instance/*",
        "arn:*:ec2:*:*:launch-template/*"
      ],
      "Action": ["ec2:TerminateInstances", "ec2:DeleteLaunchTemplate"],
      "Condition": {
        "StringLike": { "aws:ResourceTag/karpenter.sh/nodepool": "*" }
      }
    },
    {
      "Sid": "AllowRegionalReadActions",
      "Effect": "Allow",
      "Resource": "*",
      "Action": [
        "ec2:DescribeImages",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceTypeOfferings",
        "ec2:DescribeInstanceTypes",
        "ec2:DescribeLaunchTemplates",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSpotPriceHistory",
        "ec2:DescribeSubnets"
      ]
    },
    {
      "Sid": "AllowSSMReadActions",
      "Effect": "Allow",
      "Resource": "arn:*:ssm:*::parameter/aws/service/*",
      "Action": "ssm:GetParameter"
    },
    {
      "Sid": "AllowPricingReadActions",
      "Effect": "Allow",
      "Resource": "*",
      "Action": "pricing:GetProducts"
    },
    {
      "Sid": "AllowInterruptionQueueActions",
      "Effect": "Allow",
      "Resource": "*",
      "Action": [
        "sqs:DeleteMessage",
        "sqs:GetQueueUrl",
        "sqs:ReceiveMessage"
      ]
    },
    {
      "Sid": "AllowPassingInstanceRole",
      "Effect": "Allow",
      "Resource": "arn:*:iam::*:role/*",
      "Action": "iam:PassRole",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": ["ec2.amazonaws.com", "ec2.amazonaws.com.cn"]
        }
      }
    },
    {
      "Sid": "AllowScopedInstanceProfileCreationActions",
      "Effect": "Allow",
      "Resource": "arn:*:iam::*:instance-profile/*",
      "Action": ["iam:CreateInstanceProfile"],
      "Condition": {
        "StringLike": { "aws:RequestTag/karpenter.k8s.aws/ec2nodeclass": "*" }
      }
    },
    {
      "Sid": "AllowScopedInstanceProfileTagActions",
      "Effect": "Allow",
      "Resource": "arn:*:iam::*:instance-profile/*",
      "Action": ["iam:TagInstanceProfile"],
      "Condition": {
        "StringLike": {
          "aws:ResourceTag/karpenter.k8s.aws/ec2nodeclass": "*",
          "aws:RequestTag/karpenter.k8s.aws/ec2nodeclass": "*"
        }
      }
    },
    {
      "Sid": "AllowScopedInstanceProfileActions",
      "Effect": "Allow",
      "Resource": "arn:*:iam::*:instance-profile/*",
      "Action": [
        "iam:AddRoleToInstanceProfile",
        "iam:RemoveRoleFromInstanceProfile",
        "iam:DeleteInstanceProfile"
      ],
      "Condition": {
        "StringLike": { "aws:ResourceTag/karpenter.k8s.aws/ec2nodeclass": "*" }
      }
    },
    {
      "Sid": "AllowInstanceProfileReadActions",
      "Effect": "Allow",
      "Resource": "arn:*:iam::*:instance-profile/*",
      "Action": "iam:GetInstanceProfile"
    }
  ]
}
POLICY

POLICY_ARN="$(aws iam create-policy \
  --policy-name "${AUTONODE_PREFIX}-autonode-policy" \
  --policy-document "file://${AUTONODE_POLICY_FILE}" \
  --query 'Policy.Arn' \
  --output text)"
ok "AutoNode IAM policy created: ${POLICY_ARN}"

# ── 2c: Get OIDC provider URL for the cluster ──────────────────────────────────
OIDC_PROVIDER_URL="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
url = d.get('aws', {}).get('sts', {}).get('oidc_endpoint_url', '')
# strip https:// prefix
if url.startswith('https://'):
    url = url[len('https://'):]
print(url)
")"
[[ -n "${OIDC_PROVIDER_URL}" ]] || fail "Could not retrieve OIDC provider URL from cluster description."
info "OIDC provider URL: ${OIDC_PROVIDER_URL}"

# ── 2d: Create trust policy and IAM role ──────────────────────────────────────
info "Creating AutoNode IAM role..."
cat > "${TRUST_POLICY_FILE}" <<TRUST
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER_URL}"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "${OIDC_PROVIDER_URL}:sub": "system:serviceaccount:kube-system:karpenter"
        }
      }
    }
  ]
}
TRUST

ROLE_ARN="$(aws iam create-role \
  --role-name "${AUTONODE_PREFIX}-autonode-operator-role" \
  --assume-role-policy-document "file://${TRUST_POLICY_FILE}" \
  --query 'Role.Arn' \
  --output text)"

aws iam attach-role-policy \
  --role-name "${AUTONODE_PREFIX}-autonode-operator-role" \
  --policy-arn "${POLICY_ARN}"

ok "AutoNode IAM role created: ${ROLE_ARN}"

T_IAM="$(now_ms)"
emit_timing "hcp.autonode_iam_ready" "${T_START}" "${T_IAM}"

# Update cluster state with IAM details.
write_cluster_state "hcp-autonode" \
  autonode_role_arn="${ROLE_ARN}" \
  autonode_policy_arn="${POLICY_ARN}"

# ── 2e: Tag private subnet(s) and security group for Karpenter discovery ──────
info "Tagging private subnets and security group for Karpenter discovery (tag: karpenter.sh/discovery=${CLUSTER_ID})..."

# Tag all private subnets (tagged kubernetes.io/cluster/<id>=shared by ROSA at install time).
PRIVATE_SUBNET_IDS="$(aws ec2 describe-subnets \
  --region "${AWS_REGION}" \
  --filters \
    "Name=tag:kubernetes.io/role/internal-elb,Values=*" \
    "Name=tag:kubernetes.io/cluster/${CLUSTER_ID},Values=shared" \
  --query 'Subnets[*].SubnetId' \
  --output text)"

if [[ -z "${PRIVATE_SUBNET_IDS}" ]]; then
  warn "No private subnets found with kubernetes.io/cluster/${CLUSTER_ID}=shared tag."
  warn "Karpenter SubnetsReady may be False. Tag subnets manually:"
  warn "  aws ec2 create-tags --resources <subnet-id> --tags Key=karpenter.sh/discovery,Value=${CLUSTER_ID}"
else
  for subnet_id in ${PRIVATE_SUBNET_IDS}; do
    aws ec2 create-tags \
      --region "${AWS_REGION}" \
      --resources "${subnet_id}" \
      --tags "Key=karpenter.sh/discovery,Value=${CLUSTER_ID}"
    info "  Tagged subnet: ${subnet_id}"
  done
fi

# The default security group is auto-tagged by HyperShift (via the inline policy added above).
# Verify it has been tagged; if not, tag manually.
SG_ID="$(aws ec2 describe-security-groups \
  --region "${AWS_REGION}" \
  --filters "Name=tag:Name,Values=${CLUSTER_ID}-default-sg" \
  --query 'SecurityGroups[0].GroupId' \
  --output text 2>/dev/null || true)"

if [[ -n "${SG_ID}" && "${SG_ID}" != "None" ]]; then
  aws ec2 create-tags \
    --region "${AWS_REGION}" \
    --resources "${SG_ID}" \
    --tags "Key=karpenter.sh/discovery,Value=${CLUSTER_ID}" || true
  info "  Tagged security group: ${SG_ID}"
else
  warn "Default security group '${CLUSTER_ID}-default-sg' not found yet."
  warn "HyperShift should auto-tag it. If ec2nodeclass/default shows SecurityGroupsReady=False, see troubleshooting."
fi

T_TAGGED="$(now_ms)"
emit_timing "hcp.subnets_tagged" "${T_START}" "${T_TAGGED}"

# ── 2f: Enable AutoNode on the cluster ────────────────────────────────────────
info "Enabling AutoNode on cluster ${ROSA_CLUSTER_NAME}..."
rosa edit cluster -c "${ROSA_CLUSTER_NAME}" \
  --autonode=enabled \
  --autonode-iam-role-arn="${ROLE_ARN}"

T_AUTONODE="$(now_ms)"
emit_timing "hcp.autonode_enabled" "${T_START}" "${T_AUTONODE}"
ok "AutoNode enabled."

# ── Phase 3: Post-ready milestones (same as create.sh) ───────────────────────
info "Waiting for all worker nodes (default machine pools) to report Ready..."
oc wait node -l node-role.kubernetes.io/worker \
  --for=condition=Ready \
  --timeout=45m 2>/dev/null || warn "oc wait worker nodes timed out or failed; continuing."
T_POOLS="$(now_ms)"
emit_timing "hcp.machine_pools_ready" "${T_START}" "${T_POOLS}"

info "Waiting for all ClusterOperators to report Available=True..."
oc wait clusteroperators --all \
  --for=condition=Available=True \
  --timeout=20m 2>/dev/null || true
T_OPERATORS="$(now_ms)"
emit_timing "hcp.operators_ready" "${T_START}" "${T_OPERATORS}"

# ── Verify AutoNode CRDs ──────────────────────────────────────────────────────
info "Verifying AutoNode CRDs (waiting up to 10m for Karpenter controller to install CRDs)..."
AUTONODE_VERIFY_OK=true
for attempt in $(seq 1 20); do
  EC2NC_READY="$(oc get ec2nodeclass default -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo '')"
  OSH_READY="$(oc get openshiftec2nodeclass default -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo '')"
  if [[ "${EC2NC_READY}" == "True" && "${OSH_READY}" == "True" ]]; then
    ok "ec2nodeclass/default: READY=True"
    ok "openshiftec2nodeclass/default: READY=True"
    break
  fi
  if [[ "${attempt}" -eq 20 ]]; then
    warn "AutoNode CRDs not both Ready after 10m."
    warn "  ec2nodeclass/default READY=${EC2NC_READY:-unknown}"
    warn "  openshiftec2nodeclass/default READY=${OSH_READY:-unknown}"
    warn "Check: oc get ec2nodeclass/default -o json | jq .status.conditions"
    warn "See troubleshooting in references/autonode/ for SubnetsReady / SecurityGroupsReady failures."
    AUTONODE_VERIFY_OK=false
    break
  fi
  info "  CRDs not yet ready (attempt ${attempt}/20); waiting 30s..."
  sleep 30
done

T_CRDS="$(now_ms)"
emit_timing "hcp.autonode_crds_verified" "${T_START}" "${T_CRDS}"

# ── Summary ───────────────────────────────────────────────────────────────────
emit_timing "hcp.total" "${T_START}" "$(now_ms)"

info ""
info "ROSA HCP + AutoNode provisioning complete."
info "  Cluster name:   ${ROSA_CLUSTER_NAME}"
info "  Cluster ID:     ${CLUSTER_ID}"
info "  Version:        ${RESOLVED_VERSION}"
info "  Shard:          ${AUTONODE_SHARD_ID}"
info "  Karpenter role: ${ROLE_ARN}"
if [[ "${AUTONODE_VERIFY_OK}" == "true" ]]; then
  info "  AutoNode CRDs:  READY"
else
  warn "  AutoNode CRDs:  NOT READY — see troubleshooting above"
fi
info ""
info "Next steps:"
info "  1. Create a NodePool referencing ec2nodeclass/default"
info "  2. Deploy a workload with nodeSelector autonode=true to verify Karpenter scaling"
info "  3. Run 'benchmark-create-hcp-autonode' skill to record results in a Canvas"
