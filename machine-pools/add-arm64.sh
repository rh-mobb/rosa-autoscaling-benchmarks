#!/usr/bin/env bash
# machine-pools/add-arm64.sh — Add an ARM64 (Graviton) machine pool (m6g.xlarge)
# to a ROSA Classic or HCP cluster for the ARM benchmark (test 16).
#
# The pool starts at 0 nodes (min-replicas=0) so the benchmark measures
# autoscaler-driven scale-up from zero rather than pre-warming.
#
# Environment variables:
#   ROSA_CLUSTER_NAME        — cluster name (required)
#   AUTOSCALE_MIN_REPLICAS   — minimum nodes (default: 0)
#   AUTOSCALE_MAX_REPLICAS   — maximum nodes (default: 5)
#   AWS_REGION               — AWS region (default: us-east-1)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=machine-pools/common.sh
source "${SCRIPT_DIR}/common.sh"

AUTOSCALE_MIN_REPLICAS="${AUTOSCALE_MIN_REPLICAS:-0}"
AUTOSCALE_MAX_REPLICAS="${AUTOSCALE_MAX_REPLICAS:-5}"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
export_kubeconfig_for_cluster "${ROSA_CLUSTER_NAME}"
AWS_REGION="${AWS_REGION:-us-east-1}"

info "Adding ARM64 machine pool 'bench-arm64' to cluster '${ROSA_CLUSTER_NAME}'"
info "  Instance type:  m6g.xlarge (Graviton2, arm64)"
info "  Autoscaling:    ${AUTOSCALE_MIN_REPLICAS}–${AUTOSCALE_MAX_REPLICAS} nodes"

# Verify instance type availability (m6g may not be present in all regions)
info "Verifying m6g.xlarge availability in ${AWS_REGION}..."
if ! aws ec2 describe-instance-types \
    --region "${AWS_REGION}" \
    --instance-types "m6g.xlarge" \
    --query 'InstanceTypes[0].InstanceType' \
    --output text &>/dev/null; then
  fail "m6g.xlarge is not available in ${AWS_REGION}. Try a region with Graviton support."
fi
ok "m6g.xlarge is available."

T_POOL_START="$(now_ms)"

rosa create machinepool \
  --cluster "${ROSA_CLUSTER_NAME}" \
  --name "bench-arm64" \
  --instance-type "m6g.xlarge" \
  --enable-autoscaling \
  --min-replicas "${AUTOSCALE_MIN_REPLICAS}" \
  --max-replicas "${AUTOSCALE_MAX_REPLICAS}" \
  --labels "benchmark=true,pool-type=arm64"

T_POOL_SUBMITTED="$(now_ms)"
emit_timing "pool.bench-arm64.submitted" "${T_POOL_START}" "${T_POOL_SUBMITTED}"
info "bench-arm64 pool submitted to OCM."

# The pool starts at min=0 nodes so no Ready-node wait here; the test script
# triggers scale-up by applying a workload and then polls for Ready nodes.
