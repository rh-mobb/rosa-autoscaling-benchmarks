#!/usr/bin/env bash
# clusters/common.sh — shared utilities sourced by create/destroy scripts.
# Do not execute directly.

set -euo pipefail

# Repository root (clusters/common.sh lives in clusters/)
BENCHMARK_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Logging ───────────────────────────────────────────────────────────────────
log()  { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >&2; }
info() { log "INFO  $*"; }
warn() { log "WARN  $*"; }
ok()   { log "OK    $*"; }
fail() { log "ERROR $*"; exit 1; }

# ── Per-cluster kubeconfig (Classic + HCP + machine-pool scripts) ─────────────
# Avoid sharing ~/.kube/config: whichever ran `oc login` last wins there.
# Each ROSA_CLUSTER_NAME uses tmp/kubeconfig.<sanitized>.yaml under this repo.
benchmark_kubeconfig_path() {
  local cluster_name="${1:?cluster name required}"
  local safe
  # printf '%s' — no trailing newline. echo/mapfile would feed \n into tr -c on BSD/macOS, producing
  # kubeconfig.<name>_.yaml. Hyphen stays last in the charset so tr does not parse it as an option.
  safe="$(printf '%s' "${cluster_name}" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_')"
  mkdir -p "${BENCHMARK_REPO_ROOT}/tmp"
  printf '%s\n' "${BENCHMARK_REPO_ROOT}/tmp/kubeconfig.${safe}.yaml"
}

export_kubeconfig_for_cluster() {
  local cluster_name="${1:?cluster name required}"
  local path
  path="$(benchmark_kubeconfig_path "${cluster_name}")"
  export KUBECONFIG="${path}"
}

# ── Cluster create locks (mutex per ROSA topology) ────────────────────────────
# One concurrent create-classic and one concurrent create-hcp (separate dirs).
# Set ROSA_CLUSTER_CREATE_LOCK_DISABLE=1 to skip (emergencies only).
# Adjustable: CLUSTER_CREATE_LOCK_MAX_AGE_SEC (default 6 hours) for reclaim.
CLUSTER_CREATE_LOCK_DIR=""

_cluster_create_lock_release() {
  local dir="${CLUSTER_CREATE_LOCK_DIR:-}"
  [[ -n "${dir}" && -d "${dir}" ]] || return 0
  rm -rf "${dir}"
  CLUSTER_CREATE_LOCK_DIR=""
}

# Acquire exclusive lock for this topology before provisioning. Usage:
#   acquire_cluster_create_lock classic|hcp <cluster_name>
acquire_cluster_create_lock() {
  local kind="$1"
  local cluster_name="$2"
  if [[ -n "${ROSA_CLUSTER_CREATE_LOCK_DISABLE:-}" ]]; then
    warn "ROSA_CLUSTER_CREATE_LOCK_DISABLE is set — cluster create lock skipped."
    return 0
  fi
  if [[ "${kind}" != "classic" && "${kind}" != "hcp" && "${kind}" != "hcp-autonode" ]]; then
    fail "Internal error: unsupported cluster topology for lock '${kind}' (expected classic, hcp, or hcp-autonode)."
  fi
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  local lock="${root}/tmp/cluster-create-${kind}.lock"
  mkdir -p "${root}/tmp"
  local max_age="${CLUSTER_CREATE_LOCK_MAX_AGE_SEC:-21600}"
  while true; do
    if mkdir "${lock}" 2>/dev/null; then
      CLUSTER_CREATE_LOCK_DIR="${lock}"
      printf '%s\n' "$$" > "${lock}/pid"
      printf '%s\n' "${kind}" > "${lock}/kind"
      printf '%s\n' "${cluster_name}" > "${lock}/cluster"
      date -u +%s > "${lock}/started"
      trap '_cluster_create_lock_release' EXIT INT TERM HUP
      info "Acquired ${kind} cluster create lock (pid $$, cluster ${cluster_name})."
      return 0
    fi

    local holder_pid started now age
    holder_pid="$(cat "${lock}/pid" 2>/dev/null || true)"
    started="$(cat "${lock}/started" 2>/dev/null || echo 0)"
    now="$(date -u +%s)"
    age=$(( now - started ))

    if [[ -n "${holder_pid}" ]] && kill -0 "${holder_pid}" 2>/dev/null; then
      if (( age > max_age )); then
        warn "Reclaiming stale ${kind} cluster create lock (age ${age}s > max ${max_age}s, pid ${holder_pid})."
        rm -rf "${lock}"
        continue
      fi
      fail "Another ${kind} cluster create is already running (pid ${holder_pid}, cluster $(cat "${lock}/cluster" 2>/dev/null || echo '?')). Lock: ${lock}. Wait for it to finish, or set ROSA_CLUSTER_CREATE_LOCK_DISABLE=1 to override (not recommended)."
    else
      warn "Removing abandoned ${kind} cluster create lock (pid '${holder_pid:-}' not running)."
      rm -rf "${lock}"
    fi
  done
}

# ── Cluster state file (persistent: create → destroy) ────────────────────────
# tmp/cluster.{type}.json holds all variables scripts need for a live cluster.
# Written by init_run (partial) and updated by create scripts (full, after login).
# Deleted by destroy scripts via clear_cluster_state. Accessible from Python via
# scripts/lib/bench.py:read_cluster_state() and from bash via read_cluster_state_var.

_cluster_state_path() {
  local kind="${1:?cluster type required}"
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  printf '%s\n' "${root}/tmp/cluster.${kind}.json"
}

# write_cluster_state <type> [key=value ...]
# Merge key=value pairs into tmp/cluster.{type}.json (creates if absent).
# Stores file as chmod 600 — contains credentials.
write_cluster_state() {
  local kind="${1:?cluster type required}"
  shift
  local state_file
  state_file="$(_cluster_state_path "${kind}")"
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  mkdir -p "${root}/tmp"

  # Build a Python dict literal from the remaining key=value args so we can
  # merge atomically without an external YAML/TOML dep.
  local py_updates="{}"
  if [[ $# -gt 0 ]]; then
    py_updates="{"
    local sep=""
    for kv in "$@"; do
      local key="${kv%%=*}"
      local val="${kv#*=}"
      # JSON-escape the value (just the basics; values here are paths/strings)
      py_updates+="${sep}$(printf '%s' "${key}" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()), end='')"): $(printf '%s' "${val}" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()), end='')")"
      sep=", "
    done
    py_updates+="}"
  fi

  python3 - "${state_file}" "${py_updates}" <<'PYEOF'
import json, os, sys
state_file, updates_str = sys.argv[1], sys.argv[2]
existing = {}
if os.path.exists(state_file):
    try:
        with open(state_file, encoding="utf-8") as f:
            existing = json.load(f)
    except json.JSONDecodeError:
        pass
existing.update(json.loads(updates_str))
tmp = state_file + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(existing, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, state_file)
PYEOF
  info "Cluster state updated: ${state_file}"
}

# read_cluster_state_var <type> <key>
# Print the value of <key> from tmp/cluster.{type}.json, or empty string.
read_cluster_state_var() {
  local kind="${1:?cluster type required}"
  local key="${2:?key required}"
  local state_file
  state_file="$(_cluster_state_path "${kind}")"
  [[ -f "${state_file}" ]] || { printf ''; return 0; }
  python3 -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    d = json.load(f)
print(d.get(sys.argv[2], ''), end='')
" "${state_file}" "${key}"
}

# clear_cluster_state <type>
# Remove tmp/cluster.{type}.json. Call from destroy scripts.
clear_cluster_state() {
  local kind="${1:?cluster type required}"
  local state_file
  state_file="$(_cluster_state_path "${kind}")"
  if [[ -f "${state_file}" ]]; then
    rm -f "${state_file}"
    info "Cleared cluster state: ${state_file}"
  fi
}

# ── Timing ────────────────────────────────────────────────────────────────────
# Emit a timing record to stdout AND persist it to the run's JSONL event log
# when BENCHMARK_RUN_ID is set in the environment.
# Usage: emit_timing LABEL START_EPOCH_MS END_EPOCH_MS
emit_timing() {
  local label="$1"
  local start_ms="$2"
  local end_ms="$3"
  local elapsed_ms=$(( end_ms - start_ms ))
  local elapsed_s=$(( elapsed_ms / 1000 ))

  # Human-readable to stdout (always)
  printf 'TIMING %s start=%s end=%s elapsed_ms=%s elapsed_human=%dm%ds\n' \
    "$label" "$start_ms" "$end_ms" "$elapsed_ms" \
    $(( elapsed_s / 60 )) $(( elapsed_s % 60 ))

  # Persist to JSONL event log when a run is active
  if [[ -n "${BENCHMARK_RUN_ID:-}" ]]; then
    local script_root
    script_root="$(dirname "${BASH_SOURCE[0]}")/.."
    python3 "${script_root}/scripts/record-event.py" record \
      --run-id    "${BENCHMARK_RUN_ID}" \
      --label     "${label}" \
      --start-ms  "${start_ms}" \
      --end-ms    "${end_ms}" \
      --cluster-type  "${CLUSTER_TYPE:-}" \
      --cluster-name  "${ROSA_CLUSTER_NAME:-}" \
      2>/dev/null || true  # never let persistence failure abort a benchmark
  fi
}

# ── Run initialisation ────────────────────────────────────────────────────────
# Call once at the top of a create script to create the results directory and
# export BENCHMARK_RUN_ID so all subsequent emit_timing calls are persisted.
# Usage: init_run CLUSTER_TYPE [ROSA_VERSION]
init_run() {
  local cluster_type="${1:-unknown}"
  local rosa_version="${2:-}"
  local script_root
  script_root="$(dirname "${BASH_SOURCE[0]}")/.."

  BENCHMARK_RUN_ID="$(python3 "${script_root}/scripts/record-event.py" init \
    --cluster-type  "${cluster_type}" \
    --cluster-name  "${ROSA_CLUSTER_NAME:-}" \
    --region        "${AWS_REGION:-}" \
    --rosa-version  "${rosa_version}")"
  export BENCHMARK_RUN_ID
  export CLUSTER_TYPE="${cluster_type}"

  # Write partial state — api_url / credentials filled in by create scripts after login.
  write_cluster_state "${cluster_type}" \
    run_id="${BENCHMARK_RUN_ID}" \
    cluster_name="${ROSA_CLUSTER_NAME:-}" \
    cluster_type="${cluster_type}" \
    region="${AWS_REGION:-}"
  info "Run ID persisted to cluster state: tmp/cluster.${cluster_type}.json"

  # Initialise the checkpoint file so skills can track test progress
  python3 "${script_root}/scripts/checkpoint.py" init \
    --run-id       "${BENCHMARK_RUN_ID}" \
    --cluster-type "${cluster_type}" \
    --cluster-name "${ROSA_CLUSTER_NAME:-}" \
    2>/dev/null || true

  # Mark test 01 in progress when not already completed (create scripts only call init_run once per run)
  local st
  st="$(python3 "${script_root}/scripts/checkpoint.py" status --run-id "${BENCHMARK_RUN_ID}" --test 01-cluster-install 2>/dev/null || echo pending)"
  if [[ "${st}" != "completed" ]]; then
    python3 "${script_root}/scripts/checkpoint.py" start \
      --run-id "${BENCHMARK_RUN_ID}" --test 01-cluster-install \
      2>/dev/null || true
  fi

  info "Benchmark run ID: ${BENCHMARK_RUN_ID}"
  info "Results will be written to: results/${BENCHMARK_RUN_ID}/"
}

now_ms() {
  # Portable millisecond epoch: date on macOS lacks %3N
  if date +%s%3N &>/dev/null 2>&1 && [[ "$(date +%s%3N)" =~ ^[0-9]{13}$ ]]; then
    date +%s%3N
  else
    python3 -c 'import time; print(int(time.time() * 1000))'
  fi
}

# ── Version resolution ────────────────────────────────────────────────────────
# Resolve ROSA_VERSION: if blank, auto-detect latest version common to both
# Classic and HCP. Prints the resolved version string.
# The cluster_type parameter is accepted for forward-compatibility (hcp-karpenter)
# but the version script always finds the common version across all types.
resolve_rosa_version() {
  local cluster_type="${1:-classic}"
  # Suppress unused-variable warning — kept for API consistency with future callers
  : "${cluster_type}"
  if [[ -n "${ROSA_VERSION:-}" ]]; then
    info "Using pinned ROSA_VERSION=${ROSA_VERSION}"
    echo "${ROSA_VERSION}"
    return
  fi
  info "Auto-detecting latest ROSA version supported on both Classic and HCP..."
  local version
  version="$(python3 "$(dirname "${BASH_SOURCE[0]}")/../scripts/get-rosa-version.py")"
  info "Resolved ROSA version: ${version}"
  echo "${version}"
}

# ── Cluster readiness ────────────────────────────────────────────────────────
# Poll until the cluster reaches the target state (default: ready).
# Usage: wait_for_cluster_state CLUSTER_NAME [TARGET_STATE] [TIMEOUT_MINUTES]
wait_for_cluster_state() {
  local cluster_name="$1"
  local target_state="${2:-ready}"
  local timeout_min="${3:-90}"
  local deadline=$(( $(now_ms) + timeout_min * 60 * 1000 ))

  info "Waiting for cluster '${cluster_name}' to reach state '${target_state}' (timeout: ${timeout_min}m)..."

  while true; do
    local current_state
    current_state="$(rosa describe cluster -c "${cluster_name}" -o json 2>/dev/null \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',{}).get('state','unknown'))")"

    if [[ "${current_state}" == "${target_state}" ]]; then
      ok "Cluster '${cluster_name}' is ${target_state}."
      return 0
    fi

    if (( $(now_ms) > deadline )); then
      fail "Timeout waiting for cluster '${cluster_name}' to reach state '${target_state}'. Last state: ${current_state}"
    fi

    info "  current state: ${current_state} (waiting...)"
    sleep 30
  done
}

# ── OC API login ────────────────────────────────────────────────────────────
# Retry until oc login succeeds (API + auth propagation after OCM "ready").
# Caller must set KUBECONFIG first (see export_kubeconfig_for_cluster) so the
# session merges into tmp/kubeconfig.<cluster>.yaml, not ~/.kube/config.
# Usage: wait_oc_login_success API_URL CLUSTER_ADMIN_PASSWORD [TIMEOUT_MINUTES] [OC_USERNAME]
# OC_USERNAME defaults to cluster-admin (ROSA Classic). Use admin for HCP Terraform htpasswd IDP.
wait_oc_login_success() {
  local api_url="${1:?}"
  local admin_password="${2:?}"
  local timeout_min="${3:-30}"
  local oc_user="${4:-cluster-admin}"
  local deadline=$(( $(now_ms) + timeout_min * 60 * 1000 ))

  [[ -n "${KUBECONFIG:-}" ]] || fail "KUBECONFIG is unset; call export_kubeconfig_for_cluster before wait_oc_login_success."

  info "Waiting for oc login as ${oc_user} (timeout: ${timeout_min}m)..."
  while true; do
    if oc login "${api_url}" \
      --username "${oc_user}" \
      --password "${admin_password}" \
      --insecure-skip-tls-verify=true 2>/dev/null; then
      ok "oc login succeeded."
      return 0
    fi
    if (( $(now_ms) > deadline )); then
      fail "Timeout waiting for oc login after ${timeout_min}m."
    fi
    info "  oc login not ready yet; retrying in 30s..."
    sleep 30
  done
}
