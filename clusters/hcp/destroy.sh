#!/usr/bin/env bash
# clusters/hcp/destroy.sh — Destroy ROSA HCP only via Terraform (same state backend as create.sh).
#
# There is no ROSA CLI delete path for HCP in this repository. If terraform.<cluster>.tfstate is missing,
# restore it or delete the cluster through OCM/AWS manually.
#
# Environment (Makefile / hcp.env): ROSA_CLUSTER_NAME, AWS_REGION; optional CLUSTER_ADMIN_PASSWORD,
#   ROSA_HCP_TERRAFORM_VAR_FILE for destroy-time -var-file (must match apply when custom).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clusters/common.sh
source "${SCRIPT_DIR}/../common.sh"
# shellcheck source=clusters/hcp/lib-terraform.sh
source "${SCRIPT_DIR}/lib-terraform.sh"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
AWS_REGION="${AWS_REGION:-us-east-1}"

TF_STATE="$(hcp_terraform_state_path "${ROSA_CLUSTER_NAME}")"
if [[ ! -f "${TF_STATE}" ]]; then
  fail "No Terraform state at ${TF_STATE}. HCP teardown in this repo is Terraform-only. If you deleted state, remove the cluster in the Red Hat/OpenShift console and clean up AWS resources, or restore the state file from backup."
fi

T_TFD0="$(now_ms)"
info "Destroying ROSA HCP stack via Terraform (${TF_STATE})..."
hcp_run_terraform_destroy "${ROSA_CLUSTER_NAME}"
T_TFD1="$(now_ms)"
emit_timing "hcp.terraform_destroy" "${T_TFD0}" "${T_TFD1}"

rm -f "$(hcp_terraform_generated_varfile "${ROSA_CLUSTER_NAME}")" 2>/dev/null || true

T_DONE="$(now_ms)"
emit_timing "hcp.delete_total" "${T_TFD0}" "${T_DONE}"

ok "Terraform destroy finished for '${ROSA_CLUSTER_NAME}'."

# Clear the persistent cluster state so benchmark scripts don't inherit
# stale credentials or a run ID from the now-destroyed cluster.
clear_cluster_state "hcp"
