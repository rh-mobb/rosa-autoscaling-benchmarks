#!/usr/bin/env bash
# clusters/classic/create.sh — Provision a ROSA Classic cluster and record timing.
#
# Environment variables (set by Makefile from classic.env + hcp.env; exported to create.sh):
#   ROSA_CLUSTER_NAME      — cluster name (required)
#   AWS_REGION             — AWS region (default: us-east-1)
#   ROSA_VERSION           — OCP version (blank = auto-detect latest common version)
#   ROSA_CLASSIC_MULTI_AZ  — if yes/true/1: --multi-az and worker autoscaling (see below)
#   ROSA_CLASSIC_COMPUTE_* — min/max compute nodes when multi-AZ + autoscaling (defaults: 3 / 9)
#   CLUSTER_ADMIN_PASSWORD — password for the cluster-admin user (required)
#                            Min 14 chars; must include upper, lower, and digit or symbol.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clusters/common.sh
source "${SCRIPT_DIR}/../common.sh"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_ADMIN_PASSWORD="${CLUSTER_ADMIN_PASSWORD:?CLUSTER_ADMIN_PASSWORD must be set (min 14 chars, upper+lower+digit/symbol)}"

acquire_cluster_create_lock "classic" "${ROSA_CLUSTER_NAME}"

# ── Resolve version ────────────────────────────────────────────────────────────
RESOLVED_VERSION="$(resolve_rosa_version classic)"

# ── Initialise benchmark run (creates results dir + checkpoint) ───────────────
init_run "classic" "${RESOLVED_VERSION}"

# Tee all subsequent output into the results raw dir so create.log is always
# preserved regardless of how the caller captures stdout/stderr.
RAW_DIR="${BENCHMARK_REPO_ROOT}/results/${BENCHMARK_RUN_ID}/raw"
mkdir -p "${RAW_DIR}"
exec > >(tee -a "${RAW_DIR}/create.log") 2>&1

# ── Pre-flight checks ─────────────────────────────────────────────────────────
info "Checking for existing cluster '${ROSA_CLUSTER_NAME}'..."
if rosa describe cluster -c "${ROSA_CLUSTER_NAME}" &>/dev/null; then
  existing_state="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('state','unknown'))")"
  fail "Cluster '${ROSA_CLUSTER_NAME}' already exists (state: ${existing_state}). Aborting."
fi
info "No existing cluster found. Proceeding."

ROSA_CLASSIC_MULTI_AZ_NORM="$(echo "${ROSA_CLASSIC_MULTI_AZ:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
MULTI_AZ_CLASSIC="false"
if [[ "${ROSA_CLASSIC_MULTI_AZ_NORM}" == "1" || "${ROSA_CLASSIC_MULTI_AZ_NORM}" == "true" || "${ROSA_CLASSIC_MULTI_AZ_NORM}" == "yes" ]]; then
  MULTI_AZ_CLASSIC="true"
fi

CLASSIC_COMPUTE_MIN="${ROSA_CLASSIC_COMPUTE_MIN_REPLICAS:-3}"
CLASSIC_COMPUTE_MAX="${ROSA_CLASSIC_COMPUTE_MAX_REPLICAS:-9}"
[[ "${CLASSIC_COMPUTE_MIN}" =~ ^[0-9]+$ ]] || fail "ROSA_CLASSIC_COMPUTE_MIN_REPLICAS must be an integer (got '${ROSA_CLASSIC_COMPUTE_MIN_REPLICAS:-}')."
[[ "${CLASSIC_COMPUTE_MAX}" =~ ^[0-9]+$ ]] || fail "ROSA_CLASSIC_COMPUTE_MAX_REPLICAS must be an integer (got '${ROSA_CLASSIC_COMPUTE_MAX_REPLICAS:-}')."
(( CLASSIC_COMPUTE_MAX >= CLASSIC_COMPUTE_MIN )) || fail "Classic compute max (${CLASSIC_COMPUTE_MAX}) must be >= min (${CLASSIC_COMPUTE_MIN})."

if [[ "${MULTI_AZ_CLASSIC}" == "true" ]]; then
  (( CLASSIC_COMPUTE_MIN >= 3 )) || fail "Multi-AZ Classic requires --min-replicas >= 3 (got ${CLASSIC_COMPUTE_MIN})."
fi

# Verify OIDC configuration exists (required for Classic)
info "Verifying OIDC configuration..."
if ! rosa verify quota --region "${AWS_REGION}" &>/dev/null; then
  fail "Rosa quota verification failed. Check AWS limits for region ${AWS_REGION}."
fi

# ── Create cluster ────────────────────────────────────────────────────────────
T_START="$(now_ms)"
info "Creating ROSA Classic cluster: ${ROSA_CLUSTER_NAME}"
info "  Region:  ${AWS_REGION}"
info "  Version: ${RESOLVED_VERSION}"
if [[ "${MULTI_AZ_CLASSIC}" == "true" ]]; then
  info "  Topology: multi-AZ, autoscaling workers ${CLASSIC_COMPUTE_MIN}–${CLASSIC_COMPUTE_MAX}"
fi
info ""

declare -a rosa_create_cmd=(
  rosa create cluster
  --cluster-name "${ROSA_CLUSTER_NAME}"
  --region "${AWS_REGION}"
  --version "${RESOLVED_VERSION}"
  --sts
  --mode auto
  --create-admin-user
  --cluster-admin-password "${CLUSTER_ADMIN_PASSWORD}"
)

if [[ "${MULTI_AZ_CLASSIC}" == "true" ]]; then
  # With --enable-autoscaling, ROSA rejects --replicas; use min/max only.
  rosa_create_cmd+=(--multi-az --enable-autoscaling
    --min-replicas "${CLASSIC_COMPUTE_MIN}"
    --max-replicas "${CLASSIC_COMPUTE_MAX}")
fi

rosa_create_cmd+=(--yes)

"${rosa_create_cmd[@]}"

T_CREATED="$(now_ms)"
emit_timing "classic.create_submitted" "${T_START}" "${T_CREATED}"

# ── Stream install log in the background during the wait ─────────────────────
# rosa logs install --watch streams the OpenShift installer log in real time.
# We start it immediately after rosa create cluster returns (cluster is being
# provisioned) so we capture every milestone line as it appears.  The process
# is killed once the cluster is ready and we've had a brief flush window.
INSTALL_LOG_RAW="${RAW_DIR}/install.log"
info "Streaming install log to ${INSTALL_LOG_RAW} (background)..."
rosa logs install -c "${ROSA_CLUSTER_NAME}" --watch \
  >>"${INSTALL_LOG_RAW}" 2>&1 &
INSTALL_LOG_PID=$!

# ── Wait for cluster ready ────────────────────────────────────────────────────
info "Cluster creation submitted. Waiting for cluster to reach 'ready' state..."
wait_for_cluster_state "${ROSA_CLUSTER_NAME}" "ready" 90

T_READY="$(now_ms)"
emit_timing "classic.cluster_ready" "${T_START}" "${T_READY}"

# Give the log stream a brief flush window then stop it.
sleep 5
kill "${INSTALL_LOG_PID}" 2>/dev/null || true
wait "${INSTALL_LOG_PID}" 2>/dev/null || true
info "Install log captured: ${INSTALL_LOG_RAW} ($(wc -l <"${INSTALL_LOG_RAW}") lines)"

# ── Parse install log milestones into events.jsonl ───────────────────────────
info "Parsing install log milestones..."
python3 "${BENCHMARK_REPO_ROOT}/scripts/collect-install-log-milestones.py" \
  --log-file     "${INSTALL_LOG_RAW}" \
  --run-id       "${BENCHMARK_RUN_ID}" \
  --raw-dir      "${RAW_DIR}" \
  --since-ms     "${T_START}" \
  --prefix       "classic.install_log" \
  --cluster-type "classic" \
  --cluster-name "${ROSA_CLUSTER_NAME}" \
  || warn "Install log milestone parsing failed (non-fatal); benchmark results unaffected."

# ── Post-ready: login → machine pools → operators ───────────────────────────
info "Kubernetes post-ready checks (login → default machine pools → operators)..."

# Extract the API URL to poll cluster operators via oc
API_URL="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('api',{}).get('url',''))")"
[[ -n "${API_URL}" ]] || fail "No API URL in rosa describe after cluster ready; cannot run oc benchmarks."

export_kubeconfig_for_cluster "${ROSA_CLUSTER_NAME}"
info "Using KUBECONFIG=${KUBECONFIG}"

wait_oc_login_success "${API_URL}" "${CLUSTER_ADMIN_PASSWORD}" 30
T_LOGIN="$(now_ms)"
emit_timing "classic.oc_login_ok" "${T_START}" "${T_LOGIN}"

# Persist full cluster state now that we have the API URL and credentials.
write_cluster_state "classic" \
  api_url="${API_URL}" \
  username="cluster-admin" \
  password="${CLUSTER_ADMIN_PASSWORD}" \
  rosa_version="${RESOLVED_VERSION}" \
  created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  kubeconfig="${KUBECONFIG}"

info "Waiting for all worker nodes (default machine pools) to report Ready..."
oc wait node -l node-role.kubernetes.io/worker \
  --for=condition=Ready \
  --timeout=45m 2>/dev/null || warn "oc wait worker nodes timed out or failed; continuing."
T_POOLS="$(now_ms)"
emit_timing "classic.machine_pools_ready" "${T_START}" "${T_POOLS}"
emit_timing "classic.workers_ready" "${T_START}" "${T_POOLS}"

info "Waiting for all ClusterOperators to report Available=True..."
oc wait clusteroperators --all \
  --for=condition=Available=True \
  --timeout=30m 2>/dev/null || true

T_OPERATORS="$(now_ms)"
emit_timing "classic.operators_ready" "${T_START}" "${T_OPERATORS}"

# ── Summary ───────────────────────────────────────────────────────────────────
info ""
info "ROSA Classic cluster provisioning complete."
info "  Cluster name: ${ROSA_CLUSTER_NAME}"
info "  Version:      ${RESOLVED_VERSION}"
emit_timing "classic.total" "${T_START}" "$(now_ms)"
info ""
info "Next step: open Cursor and invoke 'benchmark-cluster-install' to record results."
