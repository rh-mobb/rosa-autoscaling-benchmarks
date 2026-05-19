#!/usr/bin/env bash
# machine-pools/add-spot.sh — Add a spot instance machine pool (m5.xlarge) to
# a ROSA Classic cluster for the spot benchmark (test 15).
#
# Spot instances bid on spare EC2 capacity at a lower hourly price.  The pool
# starts at 0 nodes (min-replicas=0) so the benchmark measures autoscaler-driven
# scale-up from zero rather than pre-warming.
#
# Environment variables:
#   ROSA_CLUSTER_NAME        — cluster name (required)
#   AUTOSCALE_MIN_REPLICAS   — minimum nodes (default: 0)
#   AUTOSCALE_MAX_REPLICAS   — maximum nodes (default: 5)
#   AWS_REGION               — AWS region (default: us-east-1)
#   SPOT_MAX_PRICE           — max bid price per instance-hour (default: on-demand price)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=machine-pools/common.sh
source "${SCRIPT_DIR}/common.sh"

AUTOSCALE_MIN_REPLICAS="${AUTOSCALE_MIN_REPLICAS:-0}"
AUTOSCALE_MAX_REPLICAS="${AUTOSCALE_MAX_REPLICAS:-5}"
SPOT_MAX_PRICE="${SPOT_MAX_PRICE:-}"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
export_kubeconfig_for_cluster "${ROSA_CLUSTER_NAME}"
AWS_REGION="${AWS_REGION:-us-east-1}"

info "Adding spot machine pool 'bench-spot' to cluster '${ROSA_CLUSTER_NAME}'"
info "  Instance type:  m5.xlarge (spot)"
info "  Autoscaling:    ${AUTOSCALE_MIN_REPLICAS}–${AUTOSCALE_MAX_REPLICAS} nodes"
if [[ -n "${SPOT_MAX_PRICE}" ]]; then
  info "  Max spot price: \$${SPOT_MAX_PRICE}/hr"
else
  info "  Max spot price: on-demand (default)"
fi

# Verify instance type availability
info "Verifying instance type availability in ${AWS_REGION}..."
if ! aws ec2 describe-instance-types \
    --region "${AWS_REGION}" \
    --instance-types "m5.xlarge" \
    --query 'InstanceTypes[0].InstanceType' \
    --output text &>/dev/null; then
  fail "m5.xlarge is not available in ${AWS_REGION}."
fi
ok "m5.xlarge is available."

T_POOL_START="$(now_ms)"

rosa_cmd=(
  rosa create machinepool
  --cluster "${ROSA_CLUSTER_NAME}"
  --name "bench-spot"
  --instance-type "m5.xlarge"
  --use-spot-instances
  --enable-autoscaling
  --min-replicas "${AUTOSCALE_MIN_REPLICAS}"
  --max-replicas "${AUTOSCALE_MAX_REPLICAS}"
  --labels "benchmark=true,pool-type=spot"
)
if [[ -n "${SPOT_MAX_PRICE}" ]]; then
  rosa_cmd+=(--spot-max-price "${SPOT_MAX_PRICE}")
fi
"${rosa_cmd[@]}"

T_POOL_SUBMITTED="$(now_ms)"
emit_timing "pool.bench-spot.submitted" "${T_POOL_START}" "${T_POOL_SUBMITTED}"
info "bench-spot pool submitted to OCM."

# The pool starts at min=0 nodes so no Ready-node wait here; the test script
# triggers scale-up by applying a workload and then polls for Ready nodes.
