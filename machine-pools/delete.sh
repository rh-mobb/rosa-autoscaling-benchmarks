#!/usr/bin/env bash
# machine-pools/delete.sh — Delete a named machine pool and terminate its nodes.
#
# Usage: bash machine-pools/delete.sh <pool-name>
#
# Environment variables:
#   ROSA_CLUSTER_NAME  — cluster name (required)
#   AWS_REGION         — AWS region (default: us-east-1)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clusters/common.sh
source "${SCRIPT_DIR}/../clusters/common.sh"

POOL_NAME="${1:?Usage: $0 <pool-name>}"
ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
AWS_REGION="${AWS_REGION:-us-east-1}"

info "Deleting machine pool '${POOL_NAME}' from cluster '${ROSA_CLUSTER_NAME}'..."

pool_list="$(rosa list machinepools -c "${ROSA_CLUSTER_NAME}" 2>/dev/null || true)"
if ! echo "${pool_list}" | grep -qE "^${POOL_NAME} "; then
  warn "Machine pool '${POOL_NAME}' not found on cluster '${ROSA_CLUSTER_NAME}' — nothing to delete."
  exit 0
fi

rosa delete machinepool \
  --cluster "${ROSA_CLUSTER_NAME}" \
  --machinepool "${POOL_NAME}" \
  --yes

ok "Machine pool '${POOL_NAME}' deleted. AWS will terminate its EC2 instances asynchronously."
