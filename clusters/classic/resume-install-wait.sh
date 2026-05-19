#!/usr/bin/env bash
# Resume cluster ready + operator wait when create.sh was interrupted after rosa submit.
# Usage: BENCHMARK_RUN_ID=... ROSA_CLUSTER_NAME=... CLUSTER_ADMIN_PASSWORD=... bash clusters/classic/resume-install-wait.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"
# shellcheck source=clusters/common.sh
source "${SCRIPT_DIR}/../common.sh"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME required}"
CLUSTER_ADMIN_PASSWORD="${CLUSTER_ADMIN_PASSWORD:?CLUSTER_ADMIN_PASSWORD required}"
BENCHMARK_RUN_ID="${BENCHMARK_RUN_ID:?BENCHMARK_RUN_ID required}"
export CLUSTER_TYPE="${CLUSTER_TYPE:-classic}"

T_START="$(
  python3 -c "
import json
path = 'results/${BENCHMARK_RUN_ID}/events.jsonl'
with open(path) as f:
    for line in f:
        e = json.loads(line)
        if e.get('label') == 'classic.create_submitted':
            print(e['start_ms'])
            break
    else:
        raise SystemExit('no classic.create_submitted in events')
"
)"

info "Resuming wait for cluster '${ROSA_CLUSTER_NAME}' (run ${BENCHMARK_RUN_ID}, T_START=${T_START})..."
wait_for_cluster_state "${ROSA_CLUSTER_NAME}" "ready" 90

T_READY="$(now_ms)"
emit_timing "classic.cluster_ready" "${T_START}" "${T_READY}"

info "Post-ready: oc login → worker nodes (pools) → ClusterOperators..."
API_URL="$(rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('api',{}).get('url',''))")"
[[ -n "${API_URL}" ]] || fail "No API URL in rosa describe after cluster ready; cannot run oc benchmarks."

export_kubeconfig_for_cluster "${ROSA_CLUSTER_NAME}"
info "Using KUBECONFIG=${KUBECONFIG}"

wait_oc_login_success "${API_URL}" "${CLUSTER_ADMIN_PASSWORD}" 30
T_LOGIN="$(now_ms)"
emit_timing "classic.oc_login_ok" "${T_START}" "${T_LOGIN}"

info "Waiting for all worker nodes (default machine pools) to report Ready..."
oc wait node -l node-role.kubernetes.io/worker \
  --for=condition=Ready \
  --timeout=45m 2>/dev/null || {
  warn "oc wait worker nodes timed out or failed; continuing."
}
T_POOLS="$(now_ms)"
emit_timing "classic.machine_pools_ready" "${T_START}" "${T_POOLS}"
emit_timing "classic.workers_ready" "${T_START}" "${T_POOLS}"

info "Waiting for all ClusterOperators to report Available=True..."
oc wait clusteroperators --all \
  --for=condition=Available=True \
  --timeout=30m 2>/dev/null || true

T_OPERATORS="$(now_ms)"
emit_timing "classic.operators_ready" "${T_START}" "${T_OPERATORS}"

info "ROSA Classic provisioning complete (resumed)."
emit_timing "classic.total" "${T_START}" "$(now_ms)"
