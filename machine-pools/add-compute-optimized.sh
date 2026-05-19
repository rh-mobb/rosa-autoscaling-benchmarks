#!/usr/bin/env bash
# machine-pools/add-compute-optimized.sh — Add a compute-optimized machine pool (c5.xlarge).
#
# c5.xlarge: 4 vCPU, 8 GiB RAM — high CPU-to-memory ratio for compute-intensive workloads.
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
  "bench-compute" \
  "c5.xlarge" \
  "benchmark=true,pool-type=compute-optimized"
