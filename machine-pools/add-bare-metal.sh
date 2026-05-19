#!/usr/bin/env bash
# machine-pools/add-bare-metal.sh — Add a bare-metal machine pool (m5.metal).
#
# m5.metal: 96 vCPU, 384 GiB RAM — bare metal, no hypervisor overhead.
# Expect significantly longer provisioning times than virtualized instance types.
#
# NOTE: Bare metal instances may not be available in all availability zones.
# The script selects the first AZ in the region that has m5.metal capacity.
#
# Environment variables:
#   ROSA_CLUSTER_NAME        — cluster name (required)
#   ROSA_MACHINE_POOL_SINGLE_AZ — if yes: one-AZ pool, max 1 bare-metal node here
#   AUTOSCALE_MIN_REPLICAS   — minimum nodes (default: 1)
#   AUTOSCALE_MAX_REPLICAS   — ignored for bare metal unless single-AZ (then 1); else capped at 3
#   AWS_REGION               — AWS region (default: us-east-1)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=machine-pools/common.sh
source "${SCRIPT_DIR}/common.sh"

ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
AWS_REGION="${AWS_REGION:-us-east-1}"
# Cap bare-metal pool size — single-node when benchmarking one-AZ follow-up pools.
single_az_norm="$(echo "${ROSA_MACHINE_POOL_SINGLE_AZ:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
if [[ "${single_az_norm}" == "1" || "${single_az_norm}" == "true" || "${single_az_norm}" == "yes" ]]; then
  AUTOSCALE_MIN_REPLICAS="${AUTOSCALE_MIN_REPLICAS:-1}"
  AUTOSCALE_MAX_REPLICAS=1
else
  AUTOSCALE_MIN_REPLICAS="${AUTOSCALE_MIN_REPLICAS:-1}"
  AUTOSCALE_MAX_REPLICAS=3
fi

# ── Verify bare-metal availability ────────────────────────────────────────────
info "Checking m5.metal availability in ${AWS_REGION}..."
available_azs="$(aws ec2 describe-instance-type-offerings \
  --region "${AWS_REGION}" \
  --location-type availability-zone \
  --filters "Name=instance-type,Values=m5.metal" \
  --query 'InstanceTypeOfferings[].Location' \
  --output json)"

az_count="$(echo "${available_azs}" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")"

if (( az_count == 0 )); then
  fail "m5.metal is not available in any AZ in ${AWS_REGION}. Choose a different region."
fi

info "m5.metal is available in ${az_count} AZ(s) in ${AWS_REGION}."
info "Note: bare-metal provisioning typically takes 20–40 minutes."
info ""

# Pool name must be ≤15 characters on ROSA HCP (hosted control planes).
add_machine_pool \
  "bench-metal" \
  "m5.metal" \
  "benchmark=true,pool-type=bare-metal"
