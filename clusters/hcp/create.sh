#!/usr/bin/env bash
# clusters/hcp/create.sh — Provision ROSA HCP via Terraform only (clusters/hcp/terraform/) and record timing.
#
# Classic clusters use clusters/classic/create.sh (ROSA CLI). HCP is intentionally Terraform-only.
#
# Prerequisites: README.md, hcp.env.example, clusters/hcp/terraform/README.md (RHCS_TOKEN / rosa token).
#
# Environment — see Makefile (hcp.env) plus:
#   ROSA_HCP_TERRAFORM_VAR_FILE — optional path to a full .tfvars (skips generated varfile)
#   ROSA_HCP_MAX_POOL_REPLICAS — Terraform default_max_replicas per pool (multi-AZ: per AZ).
#       If unset, falls back to AUTOSCALE_MAX_REPLICAS so benchmark pool caps stay independent when set.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clusters/common.sh
source "${SCRIPT_DIR}/../common.sh"
# shellcheck source=clusters/hcp/lib-terraform.sh
source "${SCRIPT_DIR}/lib-terraform.sh"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_ADMIN_PASSWORD="${CLUSTER_ADMIN_PASSWORD:?CLUSTER_ADMIN_PASSWORD must be set (min 14 chars, upper+lower+digit/symbol)}"

hcp_private_cluster_truthy() {
  local __v
  __v="$(echo "${ROSA_HCP_PRIVATE_CLUSTER:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  [[ "${__v}" == "1" || "${__v}" == "true" || "${__v}" == "yes" ]]
}

acquire_cluster_create_lock "hcp" "${ROSA_CLUSTER_NAME}"

# ── Resolve version ────────────────────────────────────────────────────────────
RESOLVED_VERSION="$(resolve_rosa_version hcp)"

# ── Initialise benchmark run ──────────────────────────────────────────────────
init_run "hcp" "${RESOLVED_VERSION}"

# ── Pre-flight checks ──────────────────────────────────────────────────────────
info "Checking for existing cluster '${ROSA_CLUSTER_NAME}'..."
if rosa describe cluster -c "${ROSA_CLUSTER_NAME}" &>/dev/null; then
  existing_state="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('state','unknown'))")"
  fail "Cluster '${ROSA_CLUSTER_NAME}' already exists (state: ${existing_state}). Aborting."
fi
info "No existing cluster found. Proceeding."

# ── Topology / pool sizing ────────────────────────────────────────────────────
ROSA_HCP_MULTI_AZ_NORM="$(echo "${ROSA_HCP_MULTI_AZ:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
MULTI_AZ_TF="false"
if [[ "${ROSA_HCP_MULTI_AZ_NORM}" == "1" || "${ROSA_HCP_MULTI_AZ_NORM}" == "true" || "${ROSA_HCP_MULTI_AZ_NORM}" == "yes" ]]; then
  MULTI_AZ_TF="true"
fi

info "Provisioning via Terraform (${ROSA_HCP_TERRAFORM_VAR_FILE:+custom }tfvars → clusters/hcp/terraform)."
if hcp_private_cluster_truthy; then
  fail "The HCP stack is pinned to public API (see clusters/hcp/terraform/main.tf check block). Clear ROSA_HCP_PRIVATE_CLUSTER or use ROSA_HCP_TERRAFORM_VAR_FILE with a root that supports private clusters."
fi
if [[ -n "${ROSA_HCP_CREATE_NETWORK:-}" ]] || [[ -n "${ROSA_HCP_SUBNET_IDS:-}" ]]; then
  info "Ignoring legacy ROSA_HCP_CREATE_NETWORK / ROSA_HCP_SUBNET_IDS — VPC is owned by Terraform modules."
fi

declare rep="${ROSA_HCP_REPLICAS:-2}"
[[ "${rep}" =~ ^[0-9]+$ ]] || fail "ROSA_HCP_REPLICAS must be a positive integer (got '${ROSA_HCP_REPLICAS:-}')."
# Multi-AZ default pools are per-AZ (workers-0/1/2); min 1 per AZ = 3 workers cluster-wide.
if [[ "${MULTI_AZ_TF}" == "true" ]]; then
  (( rep >= 1 )) || fail "ROSA_HCP_REPLICAS must be at least 1 per AZ for multi-AZ (got ${rep})."
else
  (( rep >= 2 )) || fail "ROSA_HCP_REPLICAS must be at least 2 for single-AZ (got ${rep})."
fi
ROSA_HCP_REPLICAS_EFFECTIVE="${rep}"

# Terraform default_max_replicas is per machine pool; for multi-AZ that is per AZ (not cluster total).
# Use ROSA_HCP_MAX_POOL_REPLICAS so cluster caps stay separate from AUTOSCALE_MAX_REPLICAS (benchmark pools).
declare max_rep="${ROSA_HCP_MAX_POOL_REPLICAS:-${AUTOSCALE_MAX_REPLICAS:-10}}"

T_START="$(now_ms)"
hcp_run_terraform_apply "${ROSA_CLUSTER_NAME}" "${RESOLVED_VERSION}" "${MULTI_AZ_TF}" "${ROSA_HCP_REPLICAS_EFFECTIVE}" "${max_rep}"

# ── Wait for cluster ready ────────────────────────────────────────────────────
info "Waiting for cluster to reach 'ready' state..."
wait_for_cluster_state "${ROSA_CLUSTER_NAME}" "ready" 30

T_READY="$(now_ms)"
emit_timing "hcp.cluster_ready" "${T_START}" "${T_READY}"

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
    --cluster-type "${CLUSTER_TYPE:-hcp}" \
    --cluster-name "${ROSA_CLUSTER_NAME}" \
    2>&1 >&2 || warn "Install log milestone collection failed (non-fatal); benchmark results unaffected."
fi

# ── Cluster operators / login / machine pools (ordered milestones) ─────────
info "Kubernetes post-ready checks (login → machine pools → operators)..."

API_URL="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('api',{}).get('url',''))")"
[[ -n "${API_URL}" ]] || fail "No API URL in rosa describe after cluster ready; cannot run oc benchmarks."

export_kubeconfig_for_cluster "${ROSA_CLUSTER_NAME}"
info "Using KUBECONFIG=${KUBECONFIG}"

wait_oc_login_success "${API_URL}" "${CLUSTER_ADMIN_PASSWORD}" 30 admin
T_LOGIN="$(now_ms)"
emit_timing "hcp.oc_login_ok" "${T_START}" "${T_LOGIN}"

# Persist full cluster state now that we have the API URL and credentials.
write_cluster_state "hcp" \
  api_url="${API_URL}" \
  username="admin" \
  password="${CLUSTER_ADMIN_PASSWORD}" \
  rosa_version="${RESOLVED_VERSION}" \
  created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  kubeconfig="${KUBECONFIG}"

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

info ""
info "ROSA HCP cluster provisioning complete."
info "  Cluster name: ${ROSA_CLUSTER_NAME}"
info "  Version:      ${RESOLVED_VERSION}"
emit_timing "hcp.total" "${T_START}" "$(now_ms)"
info ""
info "Next step: open Cursor and invoke 'benchmark-cluster-install' to record results."
