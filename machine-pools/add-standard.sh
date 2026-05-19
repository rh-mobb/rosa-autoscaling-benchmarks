#!/usr/bin/env bash
# machine-pools/add-standard.sh — Add a general-purpose machine pool (m5.xlarge).
#
# m5.xlarge: 4 vCPU, 16 GiB RAM — baseline for most workload benchmarks.
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
  "bench-standard" \
  "m5.xlarge" \
  "benchmark=true,pool-type=standard"
