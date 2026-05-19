#!/usr/bin/env bash
# clusters/classic/destroy.sh — Destroy a ROSA Classic cluster.
#
# Deletes the cluster, waits until it disappears from OCM, then removes
# operator IAM roles and the OIDC provider (same sequence `rosa delete cluster`
# recommends). Captures cluster id before delete because only the id remains
# valid for STS cleanup afterward.
#
# Environment variables (set by Makefile):
#   ROSA_CLUSTER_NAME — cluster name (required)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clusters/common.sh
source "${SCRIPT_DIR}/../common.sh"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"

# ── Pre-flight ─────────────────────────────────────────────────────────────────
info "Looking up cluster '${ROSA_CLUSTER_NAME}'..."
if ! rosa describe cluster -c "${ROSA_CLUSTER_NAME}" &>/dev/null; then
  fail "Cluster '${ROSA_CLUSTER_NAME}' not found. Nothing to destroy."
fi

current_state="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('state','unknown'))")"
info "Current cluster state: ${current_state}"

ROSA_CLUSTER_ID="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
  | python3 -c "import sys, json; cid = json.load(sys.stdin).get('id'); print(cid or '')")"
[[ -n "${ROSA_CLUSTER_ID}" ]] \
  || fail "Could not read cluster id from 'rosa describe' for '${ROSA_CLUSTER_NAME}'."

# ── Delete ────────────────────────────────────────────────────────────────────
T_START="$(now_ms)"
info "Deleting ROSA Classic cluster: ${ROSA_CLUSTER_NAME}"

rosa delete cluster \
  --cluster "${ROSA_CLUSTER_NAME}" \
  --yes

T_SUBMITTED="$(now_ms)"
emit_timing "classic.delete_submitted" "${T_START}" "${T_SUBMITTED}"

# ── Wait for deletion ─────────────────────────────────────────────────────────
info "Waiting for cluster deletion to complete..."
wait_for_cluster_state "${ROSA_CLUSTER_NAME}" "uninstalling" 5 || true

# Poll until the cluster is gone entirely
DEADLINE=$(( $(now_ms) + 60 * 60 * 1000 ))  # 60 minute timeout
while rosa describe cluster -c "${ROSA_CLUSTER_NAME}" &>/dev/null; do
  if (( $(now_ms) > DEADLINE )); then
    fail "Timeout waiting for cluster '${ROSA_CLUSTER_NAME}' to be deleted."
  fi
  info "  Cluster still deleting..."
  sleep 60
done

T_DONE="$(now_ms)"
emit_timing "classic.delete_total" "${T_START}" "${T_DONE}"
ok "Cluster '${ROSA_CLUSTER_NAME}' has been fully deleted."

# ── STS cleanup (cluster id remains valid after OCM deletion) ────────────────
info "Deleting operator IAM roles for cluster id ${ROSA_CLUSTER_ID}..."
rosa delete operator-roles \
  --cluster "${ROSA_CLUSTER_ID}" \
  --mode auto \
  --yes

info "Deleting OIDC provider for cluster id ${ROSA_CLUSTER_ID}..."
rosa delete oidc-provider \
  --cluster "${ROSA_CLUSTER_ID}" \
  --mode auto \
  --yes

ok "Classic STS cleanup finished (operator-roles + oidc-provider) for '${ROSA_CLUSTER_NAME}'."

# Clear the persistent cluster state so benchmark scripts don't inherit
# stale credentials or a run ID from the now-destroyed cluster.
clear_cluster_state "classic"
