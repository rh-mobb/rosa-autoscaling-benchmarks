#!/usr/bin/env bash
# machine-pools/common.sh — shared utilities for machine pool scripts.
# Do not execute directly.

set -euo pipefail

# Source cluster common utilities
POOL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clusters/common.sh
source "${POOL_SCRIPT_DIR}/../clusters/common.sh"

# Emit ROSA + in-cluster state while a new machine pool reconciles.
# Helps confirm OCM received the pool, spot quota / capacity stalls, and correlate timings.
# ROSA Classic exposes machine pools via `rosa`; **HCP** often uses node pools instead —
# `rosa describe machinepool` may fail on HCP (rely on `oc` / console for node pools there).
log_machine_pool_provision_snapshot() {
  local cluster="$1"
  local pool_name="$2"
  local node_selector="$3"
  local round="${4:-0}"

  info "── machine-pool snapshot (poll=${round}) cluster='${cluster}' pool='${pool_name}' ──"
  if rosa list machinepools -c "${cluster}" 2>/dev/null | grep -q "^${pool_name}[[:space:]]"; then
    info "ROSA: pool '${pool_name}' listed in 'rosa list machinepools'."
  else
    warn "ROSA: pool '${pool_name}' not listed yet (or HCP / API lag)."
  fi
  if rosa describe machinepool -c "${cluster}" --machinepool "${pool_name}" &>/dev/null; then
    rosa describe machinepool -c "${cluster}" --machinepool "${pool_name}" 2>&1 | head -40
  else
    warn "ROSA: 'rosa describe machinepool' failed for '${pool_name}' (possible HCP / not yet visible)."
  fi

  if command -v oc &>/dev/null && oc whoami &>/dev/null; then
    info "OpenShift: Machines matching pool id '${pool_name}':"
    oc get machines -n openshift-machine-api --no-headers 2>/dev/null | grep "${pool_name}" \
      || info "  (none yet — still provisioning or naming differs)"
    info "OpenShift: Nodes with ${node_selector}:"
    oc get nodes -l "${node_selector}" -o wide 2>/dev/null \
      || info "  (no nodes with this selector yet)"
  else
    warn "OpenShift: skip Machine/node snapshot — oc login required."
  fi
  info "── end snapshot ──"
}

# ── Add a machine pool with autoscaling and timing ────────────────────────────
# Usage: add_machine_pool POOL_NAME INSTANCE_TYPE LABELS
#   ROSA_CLUSTER_NAME, AUTOSCALE_MIN_REPLICAS, AUTOSCALE_MAX_REPLICAS,
#   AWS_REGION must be set in the environment.
#
# Single-AZ follow-up pools (recommended on multi-AZ clusters when quota is tight):
#   ROSA_MACHINE_POOL_SINGLE_AZ=yes  — one subnet/AZ; default 1–1 nodes (overridable).
#   ROSA_MACHINE_POOL_AZ=us-east-1a  — optional; default: first AZ from the cluster.
#   ROSA_MACHINE_POOL_MIN_REPLICAS / ROSA_MACHINE_POOL_MAX_REPLICAS — optional; default 1/1.
add_machine_pool() {
  local pool_name="$1"
  local instance_type="$2"
  local labels="${3:-}"

  ROSA_CLUSTER_NAME="${ROSA_CLUSTER_NAME:?ROSA_CLUSTER_NAME must be set}"
  export_kubeconfig_for_cluster "${ROSA_CLUSTER_NAME}"
  AUTOSCALE_MIN_REPLICAS="${AUTOSCALE_MIN_REPLICAS:-1}"
  AUTOSCALE_MAX_REPLICAS="${AUTOSCALE_MAX_REPLICAS:-10}"
  AWS_REGION="${AWS_REGION:-us-east-1}"

  local hypershift_cluster="no"
  if rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('hypershift',{}).get('enabled') else 1)" 2>/dev/null; then
    hypershift_cluster="yes"
  fi

  local single_az_norm
  single_az_norm="$(echo "${ROSA_MACHINE_POOL_SINGLE_AZ:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  local use_single_az="no"
  if [[ "${single_az_norm}" == "1" || "${single_az_norm}" == "true" || "${single_az_norm}" == "yes" ]]; then
    use_single_az="yes"
  fi

  local min_r max_r
  local pool_az=""
  if [[ "${use_single_az}" == "yes" ]]; then
    min_r="${ROSA_MACHINE_POOL_MIN_REPLICAS:-1}"
    max_r="${ROSA_MACHINE_POOL_MAX_REPLICAS:-1}"
    (( max_r >= min_r )) || max_r=$min_r
    pool_az="${ROSA_MACHINE_POOL_AZ:-}"
    if [[ -z "${pool_az}" ]]; then
      pool_az="$(
        rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json 2>/dev/null \
          | python3 -c "import sys,json; z=json.load(sys.stdin).get('nodes',{}).get('availability_zones') or []; print(z[0] if z else '')" \
          || true
      )"
    fi
    if [[ "${hypershift_cluster}" == "yes" ]]; then
      info "HCP (hosted control planes): replicas ${min_r}–${max_r} (ROSA does not support --multi-availability-zone on machine pools here)."
    else
      [[ -n "${pool_az}" ]] || fail "Single-AZ machine pool requires ROSA_MACHINE_POOL_AZ or cluster availability_zones from rosa describe."
      info "Single-AZ machine pool mode: AZ=${pool_az}, replicas ${min_r}–${max_r}."
    fi
  else
    min_r="${AUTOSCALE_MIN_REPLICAS}"
    max_r="${AUTOSCALE_MAX_REPLICAS}"
    local multi_az
    multi_az="$(
      rosa describe cluster -c "${ROSA_CLUSTER_NAME}" -o json 2>/dev/null \
        | python3 -c "import sys,json; print('yes' if json.load(sys.stdin).get('multi_az') else 'no')" \
        || echo no
    )"
    if [[ "${multi_az}" == "yes" ]]; then
      if (( min_r < 3 )); then min_r=3; fi
      max_r=$(( (max_r / 3) * 3 ))
      (( max_r >= min_r )) || max_r=$min_r
      info "Multi-AZ cluster: using machine pool replicas ${min_r}–${max_r} (multiples of 3)."
    fi
  fi

  info "Adding machine pool '${pool_name}' to cluster '${ROSA_CLUSTER_NAME}'"
  info "  Instance type: ${instance_type}"
  info "  Autoscaling:   ${min_r}–${max_r} nodes"

  # Verify the instance type is available in the target region
  info "Verifying instance type availability in ${AWS_REGION}..."
  if ! aws ec2 describe-instance-types \
      --region "${AWS_REGION}" \
      --instance-types "${instance_type}" \
      --query 'InstanceTypes[0].InstanceType' \
      --output text &>/dev/null; then
    fail "Instance type '${instance_type}' is not available in ${AWS_REGION}."
  fi
  ok "Instance type '${instance_type}' is available."

  # Record start time — the benchmark begins from here
  T_POOL_START="$(now_ms)"

  # Build the rosa command
  local rosa_cmd=(
    rosa create machinepool
    --cluster "${ROSA_CLUSTER_NAME}"
    --name "${pool_name}"
    --instance-type "${instance_type}"
    --enable-autoscaling
    --min-replicas "${min_r}"
    --max-replicas "${max_r}"
  )
  if [[ -n "${labels}" ]]; then
    rosa_cmd+=(--labels "${labels}")
  fi
  if [[ "${use_single_az}" == "yes" && "${hypershift_cluster}" != "yes" ]]; then
    rosa_cmd+=(--multi-availability-zone=false --availability-zone "${pool_az}")
  fi

  "${rosa_cmd[@]}"

  local node_selector
  node_selector="$(echo "${labels}" | tr ',' '\n' | grep '^pool-type=' || true)"
  if [[ -z "${node_selector}" ]]; then
    fail "Machine pool labels must include pool-type=... (used to poll nodes)."
  fi

  T_POOL_SUBMITTED="$(now_ms)"
  emit_timing "pool.${pool_name}.submitted" "${T_POOL_START}" "${T_POOL_SUBMITTED}"

  log_machine_pool_provision_snapshot "${ROSA_CLUSTER_NAME}" "${pool_name}" "${node_selector}" 0

  # ── Wait for at least one node from this pool to be Ready ─────────────────
  info "Waiting for the first node from pool '${pool_name}' to be Ready (selector ${node_selector})..."
  # Bare metal frequently exceeds 30m; virtual pools rarely need more than 15m.
  local wait_ms
  if [[ "${pool_name}" == *"bare-metal"* ]] || [[ "${instance_type}" == *.metal ]]; then
    wait_ms=$(( 90 * 60 * 1000 ))
  else
    wait_ms=$(( 45 * 60 * 1000 ))
  fi
  local deadline=$(( $(now_ms) + wait_ms ))
  local poll_iter=0

  while true; do
    local ready_count
    ready_count="$(oc get nodes \
      -l "${node_selector}" \
      --no-headers 2>/dev/null \
      | grep -c " Ready " || true)"

    if (( ready_count >= 1 )); then
      ok "  ${ready_count} node(s) from pool '${pool_name}' are Ready."
      break
    fi

    if (( $(now_ms) > deadline )); then
      log_machine_pool_provision_snapshot "${ROSA_CLUSTER_NAME}" "${pool_name}" "${node_selector}" "timeout"
      fail "Timeout waiting for nodes from pool '${pool_name}' to become Ready."
    fi

    info "  Ready nodes: ${ready_count} (waiting...)"
    sleep 20
    poll_iter=$((poll_iter + 1))
    if (( poll_iter % 6 == 0 )); then
      log_machine_pool_provision_snapshot "${ROSA_CLUSTER_NAME}" "${pool_name}" "${node_selector}" "${poll_iter}"
    fi
  done

  T_POOL_READY="$(now_ms)"
  emit_timing "pool.${pool_name}.first_node_ready" "${T_POOL_START}" "${T_POOL_READY}"

  # ── Collect post-factum EC2 deep telemetry ─────────────────────────────────
  # Runs after node Ready so CloudTrail events and journal logs are available.
  # Failures are non-fatal: a warning is printed and the benchmark continues.
  if [[ -n "${BENCHMARK_RUN_ID:-}" ]]; then
    info "Collecting node telemetry for '${pool_name}' (CloudTrail + journal + oc debug)..."
    python3 "${BENCHMARK_REPO_ROOT}/scripts/collect-node-telemetry.py" \
      --cluster       "${ROSA_CLUSTER_NAME}" \
      --pool          "${pool_name}" \
      --node-selector "${node_selector}" \
      --run-id        "${BENCHMARK_RUN_ID}" \
      --region        "${AWS_REGION}" \
      --raw-dir       "${BENCHMARK_REPO_ROOT}/results/${BENCHMARK_RUN_ID}/raw" \
      --prefix        "pool.${pool_name}" \
      --cluster-type  "${CLUSTER_TYPE:-classic}" \
      --cluster-name  "${ROSA_CLUSTER_NAME}" \
      --since-ms      "${T_POOL_START}" \
      ${KUBECONFIG:+--kubeconfig "${KUBECONFIG}"} \
      2>&1 >&2 || warn "Node telemetry collection failed (non-fatal); benchmark results unaffected."
  fi

  info ""
  info "Machine pool '${pool_name}' (${instance_type}) is ready."
  emit_timing "pool.${pool_name}.total" "${T_POOL_START}" "$(now_ms)"
}
