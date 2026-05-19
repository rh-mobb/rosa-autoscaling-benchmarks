#!/usr/bin/env bash
# clusters/hcp-autonode/destroy.sh — Destroy a ROSA HCP cluster provisioned by create.sh.
#
# Pre-destroy step: if the cluster is reachable via oc, deletes Karpenter NodePools and
# OpenShiftEC2NodeClass CRs and waits for NodeClaims/Nodes to drain before Terraform destroy.
# Skipping this step can leave EC2 instances blocking cluster deletion (see KCS (3) in
# references/autonode/).
#
# Teardown path: hcp_run_terraform_destroy using clusters/hcp-autonode/terraform/ state.
# If the state file is missing, the cluster must be deleted via the OCM console or AWS CLI.
#
# Environment (Makefile / autonode.env):
#   ROSA_CLUSTER_NAME           — cluster name (required)
#   AWS_REGION                  — AWS region (default: us-east-1)
#   CLUSTER_ADMIN_PASSWORD      — used for oc login when draining Karpenter resources
#   ROSA_HCP_TERRAFORM_VAR_FILE — optional; must match the varfile used at create time
#   ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH — set to 1 to skip Terraform refresh on partial teardown

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clusters/common.sh
source "${SCRIPT_DIR}/../common.sh"
# shellcheck source=clusters/hcp-autonode/lib-terraform.sh
source "${SCRIPT_DIR}/lib-terraform.sh"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
AWS_REGION="${AWS_REGION:-us-east-1}"

TF_STATE="$(hcp_terraform_state_path "${ROSA_CLUSTER_NAME}")"
if [[ ! -f "${TF_STATE}" ]]; then
  fail "No Terraform state at ${TF_STATE}. AutoNode HCP teardown requires Terraform state. If state is lost, delete the cluster via the Red Hat/OpenShift console and clean up AWS resources manually."
fi

# ── Pre-destroy: drain Karpenter resources ────────────────────────────────────
# Karpenter-managed EC2 instances can block ROSA HCP cluster deletion if not removed first.
# Best-effort: attempt oc login and delete Karpenter CRs; continue even if it fails.
_drain_karpenter_resources() {
  local api_url password kubeconfig_path
  api_url="$(read_cluster_state_var "hcp-autonode" "api_url")"
  password="${CLUSTER_ADMIN_PASSWORD:-$(read_cluster_state_var "hcp-autonode" "password")}"
  kubeconfig_path="$(read_cluster_state_var "hcp-autonode" "kubeconfig")"

  if [[ -z "${api_url}" ]]; then
    warn "No api_url in cluster state — skipping Karpenter resource cleanup."
    warn "If the cluster has active NodePools, EC2 instances may block deletion."
    warn "Delete NodePools manually before Terraform destroy or terminate instances with:"
    warn "  aws ec2 terminate-instances --instance-ids \$(aws ec2 describe-instances --filters ..."
    return 0
  fi

  if [[ -n "${kubeconfig_path}" ]]; then
    export KUBECONFIG="${kubeconfig_path}"
  else
    export_kubeconfig_for_cluster "${ROSA_CLUSTER_NAME}"
  fi

  info "Attempting oc login to drain Karpenter resources before Terraform destroy..."
  if ! oc login "${api_url}" \
    --username admin \
    --password "${password}" \
    --insecure-skip-tls-verify=false 2>/dev/null; then
    warn "oc login failed — Karpenter resources will not be drained automatically."
    warn "Proceeding with Terraform destroy; EC2 instances may need manual termination."
    return 0
  fi

  info "Deleting all Karpenter NodePools..."
  oc delete nodepools --all --timeout=5m 2>/dev/null || true

  info "Deleting all OpenShiftEC2NodeClass resources..."
  oc delete openshiftec2nodeclasses --all --timeout=5m 2>/dev/null || true

  info "Waiting for NodeClaims to be removed (up to 10m)..."
  local deadline=$(( $(now_ms) + 10 * 60 * 1000 ))
  while true; do
    local claim_count
    claim_count="$(oc get nodeclaims --no-headers 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "${claim_count}" -eq 0 ]]; then
      ok "All NodeClaims removed."
      break
    fi
    if (( $(now_ms) > deadline )); then
      warn "NodeClaims still present after 10m; proceeding with Terraform destroy."
      warn "Remaining NodeClaims: $(oc get nodeclaims --no-headers 2>/dev/null)"
      break
    fi
    info "  ${claim_count} NodeClaims remaining; waiting 15s..."
    sleep 15
  done
}

_drain_karpenter_resources || true

# ── Terraform destroy ─────────────────────────────────────────────────────────
T_TFD0="$(now_ms)"
info "Destroying ROSA HCP AutoNode stack via Terraform (${TF_STATE})..."
hcp_run_terraform_destroy "${ROSA_CLUSTER_NAME}"
T_TFD1="$(now_ms)"
emit_timing "hcp.terraform_destroy" "${T_TFD0}" "${T_TFD1}"

rm -f "$(hcp_terraform_generated_varfile "${ROSA_CLUSTER_NAME}")" 2>/dev/null || true

T_DONE="$(now_ms)"
emit_timing "hcp.delete_total" "${T_TFD0}" "${T_DONE}"

ok "Terraform destroy finished for '${ROSA_CLUSTER_NAME}'."

clear_cluster_state "hcp-autonode"
