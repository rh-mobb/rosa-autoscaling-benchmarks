#!/usr/bin/env bash
# clusters/hcp/reconcile.sh — Terraform full apply only (recovery when create phase 2 failed, etc.).
# Does not init_run, acquire the cluster create lock, or require cluster absence in OCM.
# Run from repo root via: make reconcile-hcp
#
# Environment: same as clusters/hcp/create.sh (hcp.env / Makefile).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clusters/common.sh
source "${SCRIPT_DIR}/../common.sh"
# shellcheck source=clusters/hcp/lib-terraform.sh
source "${SCRIPT_DIR}/lib-terraform.sh"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_ADMIN_PASSWORD="${CLUSTER_ADMIN_PASSWORD:?CLUSTER_ADMIN_PASSWORD must be set}"

RESOLVED_VERSION="$(resolve_rosa_version hcp)"

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

info "Terraform reconcile for HCP cluster '${ROSA_CLUSTER_NAME}' (version ${RESOLVED_VERSION}, region ${AWS_REGION})."
hcp_run_terraform_reconcile_apply "${ROSA_CLUSTER_NAME}" "${RESOLVED_VERSION}" "${MULTI_AZ_TF}" "${ROSA_HCP_REPLICAS_EFFECTIVE}" "${max_rep}"
