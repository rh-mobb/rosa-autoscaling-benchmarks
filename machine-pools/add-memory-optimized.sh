#!/usr/bin/env bash
# machine-pools/add-memory-optimized.sh — Add a memory-optimized machine pool (r5.xlarge).
#
# r5.xlarge: 4 vCPU, 32 GiB RAM — 2x the memory of m5.xlarge at the same core count.
#
# Environment variables:
#   ROSA_CLUSTER_NAME        — cluster name (required)
#   AUTOSCALE_MIN_REPLICAS   — minimum nodes (default: 1)
#   AUTOSCALE_MAX_REPLICAS   — maximum nodes (default: 10)
#   AWS_REGION               — AWS region (default: us-east-1)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=machine-pools/common.sh
source "${SCRIPT_DIR}/common.sh"

add_machine_pool \
  "bench-memory" \
  "r5.xlarge" \
  "benchmark=true,pool-type=memory-optimized"
