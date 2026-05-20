#!/usr/bin/env bash
# load-test/deploy.sh
#
# Idempotent deploy and management script for the OTel demo load-test harness.
#
# Commands:
#   ./load-test/deploy.sh install   -- deploy OTel demo + autoscaling configs
#   ./load-test/deploy.sh status    -- show pod/HPA/KEDA status
#   ./load-test/deploy.sh run-k6 <scenario> [params...]
#                                   -- run a k6 scenario and tail output
#   ./load-test/deploy.sh fetch-results <scenario> <timestamp>
#                                   -- copy k6 CSV results locally
#   ./load-test/deploy.sh uninstall -- remove everything (prompts for confirm)
#
# Environment:
#   CLUSTER_TYPE   -- classic | hcp | hcp-autonode (default: classic)
#   KUBECONFIG     -- if set, used directly; otherwise resolved from CLUSTER_TYPE
#
# Node isolation strategy:
#   install provisions a dedicated node pool (Karpenter NodePool or ROSA
#   MachinePool) labelled and tainted workload=otel-demo:NoSchedule.  All
#   OTel Demo microservices are pinned there via nodeSelector + toleration in
#   values-rosa.yaml.  k6 Job pods have neither and land on default workers.
#
# Requires: helm, oc, envsubst
# For CAS/HCP pool creation: rosa CLI must also be authenticated.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOAD_TEST_DIR="${REPO_ROOT}/load-test"
CHART_VERSION="0.40.8"
RELEASE_NAME="otel-demo"
NAMESPACE="otel-demo"
CLUSTER_TYPE="${CLUSTER_TYPE:-classic}"

# ---------------------------------------------------------------------------
# Resolve kubeconfig
# ---------------------------------------------------------------------------
resolve_kubeconfig() {
  if [[ -n "${KUBECONFIG:-}" ]]; then
    return
  fi
  local state_file="${REPO_ROOT}/tmp/cluster.${CLUSTER_TYPE}.json"
  if [[ ! -f "$state_file" ]]; then
    echo "ERROR: no cluster state file at ${state_file}" >&2
    echo "       Set KUBECONFIG manually or run make create-${CLUSTER_TYPE} first" >&2
    exit 1
  fi
  local cluster_name
  cluster_name=$(python3 -c "import json; print(json.load(open('${state_file}'))['cluster_name'])")
  export KUBECONFIG="${REPO_ROOT}/tmp/kubeconfig.${cluster_name}.yaml"
  echo "[deploy] Using kubeconfig: ${KUBECONFIG}"
}

# Read cluster name from state file (empty string if unavailable).
resolve_cluster_name() {
  local state_file="${REPO_ROOT}/tmp/cluster.${CLUSTER_TYPE}.json"
  if [[ -f "$state_file" ]]; then
    python3 -c "import json; print(json.load(open('${state_file}'))['cluster_name'])" 2>/dev/null || echo ""
  else
    echo ""
  fi
}

# ---------------------------------------------------------------------------
# provision_node_pool
#
# Creates a dedicated node pool labelled workload=otel-demo with a matching
# NoSchedule taint so only otel-demo pods schedule there.
#
# Detection order:
#   1. Karpenter CRDs present → apply karpenter-nodepool.yaml
#   2. rosa CLI available     → rosa create machine-pool (Classic or HCP)
#   3. Neither                → warn and continue without isolation
#
# Returns 0 if ready nodes exist, 1 if provisioning was skipped or timed out.
# ---------------------------------------------------------------------------
provision_node_pool() {
  echo ""
  echo "=== Step 2/6: Dedicated node pool (workload=otel-demo) ==="

  # Already have otel-demo nodes — nothing to do.
  if oc get nodes -l workload=otel-demo --no-headers 2>/dev/null | grep -q " Ready "; then
    local count
    count=$(oc get nodes -l workload=otel-demo --no-headers 2>/dev/null | grep -c " Ready " || true)
    echo "[pool] ${count} otel-demo node(s) already Ready — skipping provision"
    return 0
  fi

  if oc get crd nodepools.karpenter.sh &>/dev/null 2>&1; then
    echo "[pool] Karpenter detected — applying otel-demo NodePool"
    oc apply -f "${LOAD_TEST_DIR}/manifests/karpenter-nodepool.yaml"
    echo "[pool] NodePool applied (Karpenter provisions on demand; nodes appear when pods are pending)"
    # Karpenter provisions lazily — nodes will appear once pods are unschedulable.
    # No need to wait here; Helm --wait will handle pod readiness after scheduling.
    return 0
  fi

  if command -v rosa &>/dev/null; then
    local cluster_name
    cluster_name=$(resolve_cluster_name)
    if [[ -z "$cluster_name" ]]; then
      echo "[pool] WARNING: rosa available but cluster name unknown — skipping machine pool"
      return 1
    fi

    # Idempotent: skip if otel-demo pool already exists.
    local existing
    existing=$(rosa list machine-pools --cluster "${cluster_name}" -o json 2>/dev/null | \
      python3 -c "
import json, sys
data = sys.stdin.read().strip()
pools = json.loads(data) if data and data != 'null' else []
print('yes' if any(p.get('id','') == 'otel-demo' for p in pools) else 'no')
" 2>/dev/null || echo "no")

    if [[ "$existing" == "yes" ]]; then
      echo "[pool] ROSA machine pool 'otel-demo' already exists"
    else
      echo "[pool] Creating ROSA machine pool otel-demo on cluster ${cluster_name}..."
      rosa create machine-pool \
        --cluster "${cluster_name}" \
        --name otel-demo \
        --instance-type m5.xlarge \
        --replicas 2 \
        --labels "workload=otel-demo" \
        --taints "workload=otel-demo:NoSchedule"
      echo "[pool] Machine pool created"
    fi

    echo "[pool] Waiting up to 10 min for otel-demo nodes to be Ready..."
    local deadline=$(( SECONDS + 600 ))
    while [[ $SECONDS -lt $deadline ]]; do
      if oc get nodes -l workload=otel-demo --no-headers 2>/dev/null | grep -q " Ready "; then
        local count
        count=$(oc get nodes -l workload=otel-demo --no-headers 2>/dev/null | grep -c " Ready " || true)
        echo "[pool] ${count} otel-demo node(s) Ready"
        return 0
      fi
      echo "[pool] Still waiting... ($(( (deadline - SECONDS) / 60 ))m remaining)"
      sleep 30
    done

    echo "[pool] WARNING: otel-demo nodes not ready after 10 min — proceeding without node isolation"
    return 1
  fi

  echo "[pool] WARNING: neither Karpenter CRDs nor rosa CLI found"
  echo "       OTel Demo pods will schedule on default worker nodes"
  return 1
}

# ---------------------------------------------------------------------------
# install: namespace → SCC → pool → Helm → autoscaling configs → k6 ConfigMaps
# ---------------------------------------------------------------------------
cmd_install() {
  resolve_kubeconfig

  echo ""
  echo "=== Step 1/6: Namespace + SCC ==="
  # Use 'oc create namespace' so OpenShift auto-generates the required
  # openshift.io/sa.scc.mcs annotation. Then apply labels via patch.
  if ! oc get namespace "${NAMESPACE}" &>/dev/null; then
    oc create namespace "${NAMESPACE}"
    echo "[deploy] Namespace created; waiting for SCC annotations..."
    sleep 3
  fi
  # Patch labels only — do not apply the full namespace manifest which would
  # overwrite OpenShift-managed SCC annotations
  oc label namespace "${NAMESPACE}" workload=otel-demo --overwrite
  oc apply -f "${LOAD_TEST_DIR}/manifests/scc-otelcol.yaml"

  # Provision dedicated node pool before Helm so pods land there from the start.
  # On Karpenter clusters this is non-blocking; on CAS clusters we wait for nodes.
  local pool_ready=true
  provision_node_pool || pool_ready=false

  echo ""
  echo "=== Step 3/6: Helm install (chart ${CHART_VERSION}) ==="
  helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts 2>/dev/null || true
  helm repo update open-telemetry

  local values_file="${LOAD_TEST_DIR}/helm/values-rosa.yaml"
  if [[ "$pool_ready" == "false" ]] && \
     ! oc get nodes -l workload=otel-demo --no-headers 2>/dev/null | grep -q " Ready "; then
    echo "[deploy] No otel-demo nodes available — deploying without nodeSelector/toleration"
    local tmp_values
    tmp_values=$(mktemp /tmp/values-rosa-XXXXXX.yaml)
    python3 - "${values_file}" "${tmp_values}" <<'PYEOF'
import sys, re

src = open(sys.argv[1]).read()

# Remove the nodeSelector block (key + value lines until next non-indented key)
src = re.sub(
    r'(\s+nodeSelector:\n)(\s+workload: otel-demo\n)',
    r'\1',
    src,
)
# Replace nodeSelector value with empty map
src = src.replace(
    'nodeSelector:\n      workload: otel-demo',
    'nodeSelector: {}',
)
# Remove the toleration block
src = re.sub(
    r'\s+tolerations:\n(\s+- key: workload\n\s+value: otel-demo\n\s+effect: NoSchedule\n\s+operator: Equal\n)',
    '\n    tolerations: []\n',
    src,
)
open(sys.argv[2], 'w').write(src)
PYEOF
    values_file="${tmp_values}"
    trap "rm -f ${tmp_values}" EXIT
  else
    echo "[deploy] otel-demo nodes available — applying nodeSelector + toleration"
  fi

  helm upgrade --install "${RELEASE_NAME}" \
    open-telemetry/opentelemetry-demo \
    --version "${CHART_VERSION}" \
    --namespace "${NAMESPACE}" \
    -f "${values_file}" \
    --timeout 15m \
    --wait

  echo ""
  echo "=== Step 4/6: Autoscaling configs ==="
  # VPA operator check — skip VPA manifests if operator not installed
  if oc get crd verticalpodautoscalers.autoscaling.k8s.io &>/dev/null; then
    echo "[deploy] VPA operator present — applying VPA manifests"
    oc apply -f "${LOAD_TEST_DIR}/manifests/autoscaling/vpa-all-services.yaml"
  else
    echo "[deploy] VPA operator not found — skipping VPA manifests"
    echo "         Install VPA operator and re-run 'deploy.sh install' to add VPA"
  fi

  # KEDA check — skip KEDA manifests if operator not installed
  if oc get crd scaledobjects.keda.sh &>/dev/null; then
    echo "[deploy] KEDA operator present — applying KEDA manifests"
    oc apply -f "${LOAD_TEST_DIR}/manifests/autoscaling/email-keda.yaml"
  else
    echo "[deploy] KEDA operator not found — skipping KEDA manifests"
    echo "         Install KEDA and re-run 'deploy.sh install' to add email ScaledObject"
  fi

  # HPA configs always apply
  for f in "${LOAD_TEST_DIR}/manifests/autoscaling/"*-hpa.yaml; do
    echo "[deploy] Applying $(basename "$f")"
    oc apply -f "$f"
  done

  echo ""
  echo "=== Step 5/6: k6 ConfigMaps ==="
  # Create ConfigMap for scenario scripts
  oc create configmap k6-scenarios \
    --from-file="${LOAD_TEST_DIR}/k6/scenarios/" \
    --namespace "${NAMESPACE}" \
    --dry-run=client -o yaml | oc apply -f -

  # Create ConfigMap for lib files
  oc create configmap k6-lib \
    --from-file="${LOAD_TEST_DIR}/k6/lib/" \
    --namespace "${NAMESPACE}" \
    --dry-run=client -o yaml | oc apply -f -

  echo ""
  echo "=== Step 6/6: Waiting for pods to be Ready ==="
  # Helm --wait handles readiness; this is an extra check for autoscaling/KEDA
  # Wait for the core frontend-proxy which is the entry point for k6 traffic
  oc wait deployment/frontend-proxy \
    -n "${NAMESPACE}" \
    --for=condition=Available \
    --timeout=300s

  echo ""
  echo "=== Deploy complete ==="
  cmd_status
  echo ""
  echo "Access the web store via:"
  echo "  oc port-forward -n ${NAMESPACE} svc/frontend-proxy 8080:8080 &"
  echo "  open http://localhost:8080"
  echo "  open http://localhost:8080/grafana"
}

# ---------------------------------------------------------------------------
# status: show pod, HPA, KEDA, VPA state
# ---------------------------------------------------------------------------
cmd_status() {
  resolve_kubeconfig

  echo ""
  echo "=== Pods (otel-demo) ==="
  oc get pods -n "${NAMESPACE}" \
    --sort-by=.metadata.name \
    --no-headers \
    | awk '{print $1, $3, $4}'

  echo ""
  echo "=== HPAs ==="
  oc get hpa -n "${NAMESPACE}" 2>/dev/null || echo "(none)"

  echo ""
  echo "=== KEDA ScaledObjects ==="
  oc get scaledobject -n "${NAMESPACE}" 2>/dev/null || echo "(none or KEDA not installed)"

  echo ""
  echo "=== VPAs ==="
  oc get vpa -n "${NAMESPACE}" 2>/dev/null || echo "(none or VPA not installed)"

  echo ""
  echo "=== otel-demo nodes ==="
  oc get nodes -l workload=otel-demo --no-headers 2>/dev/null || echo "(none)"

  echo ""
  echo "=== SCC violations (last 30 min) ==="
  oc get events -n "${NAMESPACE}" \
    --field-selector reason=SCCViolation \
    --sort-by=.lastTimestamp 2>/dev/null | tail -10 || echo "(none)"
}

# ---------------------------------------------------------------------------
# run-k6: launch a k6 Job for a named scenario
# ---------------------------------------------------------------------------
cmd_run_k6() {
  local scenario="${1:-sudden-spike}"
  shift || true

  resolve_kubeconfig

  local timestamp
  timestamp=$(date +%Y%m%dt%H%M%S)

  # Default params — override via remaining positional args as KEY=VALUE
  local BASELINE_RPS=30
  local SPIKE_RPS=300
  local SPIKE_AT_S=60
  local TOTAL_S=480
  local PEAK_RPS=150
  local SUSTAINED_RPS=90
  local BURST_RPS=150

  # Parse optional KEY=VALUE overrides
  for arg in "$@"; do
    export "${arg?}"
  done

  export SCENARIO="${scenario}"
  export TIMESTAMP="${timestamp}"

  echo "[k6] Launching scenario '${scenario}' at ${timestamp}"
  echo "[k6] BASELINE_RPS=${BASELINE_RPS} SPIKE_RPS=${SPIKE_RPS:-n/a} PEAK_RPS=${PEAK_RPS:-n/a}"

  # Render and apply the Job
  envsubst < "${LOAD_TEST_DIR}/k6/jobs/k6-job-template.yaml" \
    | oc apply -f - -n "${NAMESPACE}"

  echo "[k6] Job created: k6-${scenario}-${timestamp}"
  echo "[k6] Waiting for Pod to start..."
  sleep 5

  local pod
  pod=$(oc get pods -n "${NAMESPACE}" \
    -l "load-test/scenario=${scenario},load-test/timestamp=${timestamp}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

  if [[ -z "${pod}" ]]; then
    echo "[k6] WARNING: pod not found yet — check: oc get pods -n ${NAMESPACE} -l load-test/scenario=${scenario}"
    return
  fi

  echo "[k6] Pod: ${pod}"
  echo "[k6] Tailing logs (Ctrl-C to detach; Job keeps running)..."
  oc logs -n "${NAMESPACE}" -f "${pod}" || true

  echo ""
  echo "[k6] Fetch results with:"
  echo "  ./load-test/deploy.sh fetch-results ${scenario} ${timestamp}"
}

# ---------------------------------------------------------------------------
# fetch-results: copy k6 output CSV from completed Job pod
# ---------------------------------------------------------------------------
cmd_fetch_results() {
  local scenario="${1:?usage: fetch-results <scenario> <timestamp>}"
  local timestamp="${2:?usage: fetch-results <scenario> <timestamp>}"

  resolve_kubeconfig

  local pod
  pod=$(oc get pods -n "${NAMESPACE}" \
    -l "load-test/scenario=${scenario},load-test/timestamp=${timestamp}" \
    -o jsonpath='{.items[0].metadata.name}')

  local dest="${LOAD_TEST_DIR}/results/k6-${scenario}-${timestamp}"
  mkdir -p "${dest}"

  echo "[k6] Copying results from ${pod}:/results/ → ${dest}/"
  oc cp "${NAMESPACE}/${pod}:/results/" "${dest}/"
  echo "[k6] Results saved to ${dest}/"
  ls -lh "${dest}/"
}

# ---------------------------------------------------------------------------
# uninstall: remove everything
# ---------------------------------------------------------------------------
cmd_uninstall() {
  resolve_kubeconfig

  echo "This will delete the '${NAMESPACE}' namespace, all its resources,"
  echo "and the otel-demo node pool (if one was provisioned)."
  read -r -p "Type 'yes' to confirm: " confirm
  if [[ "${confirm}" != "yes" ]]; then
    echo "Aborted."
    exit 0
  fi

  echo "[uninstall] Removing Helm release..."
  helm uninstall "${RELEASE_NAME}" -n "${NAMESPACE}" 2>/dev/null || true

  echo "[uninstall] Removing autoscaling configs..."
  oc delete -f "${LOAD_TEST_DIR}/manifests/autoscaling/" \
    -n "${NAMESPACE}" --ignore-not-found 2>/dev/null || true

  echo "[uninstall] Removing SCC bindings..."
  oc delete -f "${LOAD_TEST_DIR}/manifests/scc-otelcol.yaml" \
    --ignore-not-found 2>/dev/null || true

  echo "[uninstall] Deleting namespace..."
  oc delete namespace "${NAMESPACE}" --ignore-not-found

  # Remove the dedicated node pool so the underlying instances terminate.
  if oc get crd nodepools.karpenter.sh &>/dev/null 2>&1; then
    echo "[uninstall] Removing Karpenter NodePool otel-demo..."
    oc delete nodepool.karpenter.sh otel-demo --ignore-not-found 2>/dev/null || true
  elif command -v rosa &>/dev/null; then
    local cluster_name
    cluster_name=$(resolve_cluster_name)
    if [[ -n "$cluster_name" ]]; then
      local existing
      existing=$(rosa list machine-pools --cluster "${cluster_name}" -o json 2>/dev/null | \
        python3 -c "
import json, sys
data = sys.stdin.read().strip()
pools = json.loads(data) if data and data != 'null' else []
print('yes' if any(p.get('id','') == 'otel-demo' for p in pools) else 'no')
" 2>/dev/null || echo "no")
      if [[ "$existing" == "yes" ]]; then
        echo "[uninstall] Deleting ROSA machine pool otel-demo on ${cluster_name}..."
        rosa delete machine-pool \
          --cluster "${cluster_name}" \
          --machine-pool otel-demo \
          --yes 2>/dev/null || true
      fi
    fi
  fi

  echo "[uninstall] Done."
}

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
COMMAND="${1:-help}"
shift || true

case "${COMMAND}" in
  install)         cmd_install "$@" ;;
  status)          cmd_status "$@" ;;
  run-k6)          cmd_run_k6 "$@" ;;
  fetch-results)   cmd_fetch_results "$@" ;;
  uninstall)       cmd_uninstall "$@" ;;
  help|--help|-h)
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  install                       Deploy OTel demo + autoscaling configs"
    echo "  status                        Show pod/HPA/KEDA/VPA state"
    echo "  run-k6 <scenario> [KEY=VAL]   Run a k6 scenario Job"
    echo "  fetch-results <scenario> <ts> Copy k6 CSV results locally"
    echo "  uninstall                     Remove all resources (with confirmation)"
    echo ""
    echo "Scenarios: sudden-spike | ramp | daily-pattern | sustained-high | burst-and-drop"
    echo ""
    echo "Examples:"
    echo "  CLUSTER_TYPE=hcp-autonode ./load-test/deploy.sh install"
    echo "  CLUSTER_TYPE=classic ./load-test/deploy.sh install"
    echo "  ./load-test/deploy.sh run-k6 sudden-spike BASELINE_RPS=30 SPIKE_RPS=150"
    echo "  ./load-test/deploy.sh run-k6 ramp BASELINE_RPS=30 PEAK_RPS=150"
    echo "  ./load-test/deploy.sh fetch-results sudden-spike 20260519T143000"
    ;;
  *)
    echo "Unknown command: ${COMMAND}" >&2
    echo "Run '$0 help' for usage." >&2
    exit 1
    ;;
esac
