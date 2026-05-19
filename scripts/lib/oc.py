#!/usr/bin/env python3
"""
scripts/lib/oc.py

Thin wrappers around the `oc` CLI for benchmark test scripts.

All functions raise OcError on unrecoverable failures. Transient connection
errors (exit code 1 with a network/TLS message) are retried up to MAX_RETRIES
times with exponential backoff before raising.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

# Number of retries for transient oc connection errors
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_S = 5  # doubles each retry: 5, 10, 20


class OcError(RuntimeError):
    """Raised when an oc command fails in a non-retryable way."""


class PollTimeout(RuntimeError):
    """Raised when poll_until exceeds its timeout without the condition being met."""


# ── Internal helpers ──────────────────────────────────────────────────────────


def _is_transient(stderr: str) -> bool:
    """Return True if the error message looks like a retryable network issue."""
    transient_patterns = [
        "connection refused",
        "unable to connect",
        "tls handshake",
        "dial tcp",
        "EOF",
        "context deadline exceeded",
        "i/o timeout",
    ]
    low = stderr.lower()
    return any(p in low for p in transient_patterns)


def _build_env(kubeconfig: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    return env


# ── Public API ────────────────────────────────────────────────────────────────


def run_oc(
    args: list[str],
    *,
    json_output: bool = True,
    kubeconfig: str | None = None,
    retries: int = MAX_RETRIES,
    capture_stderr: bool = True,
) -> Any:
    """
    Run an oc command and return parsed JSON (or raw stdout string).

    args          — list of oc sub-command parts, e.g. ["get", "nodes", "-o", "json"]
    json_output   — if True, appends ["-o", "json"] automatically and parses output
    kubeconfig    — path to kubeconfig file; overrides KUBECONFIG env var
    retries       — number of times to retry on transient connection errors
    capture_stderr — capture stderr for inspection; set False to let it stream to terminal

    Raises OcError on persistent failure.
    """
    cmd = ["oc", *args]
    if json_output and "-o" not in args and "--output" not in args:
        cmd += ["-o", "json"]

    env = _build_env(kubeconfig)
    attempt = 0

    while True:
        result = subprocess.run(
            cmd,
            capture_output=capture_stderr,
            text=True,
            env=env,
        )

        if result.returncode == 0:
            if json_output:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError as exc:
                    raise OcError(
                        f"oc {' '.join(args)}: JSON parse error — {exc}\nraw: {result.stdout[:500]}"
                    ) from exc
            return result.stdout

        stderr = result.stderr or ""
        if attempt < retries and _is_transient(stderr):
            wait = RETRY_BACKOFF_BASE_S * (2**attempt)
            print(
                f"[oc] transient error (attempt {attempt + 1}/{retries}), "
                f"retrying in {wait}s: {stderr.strip()[:120]}",
                file=sys.stderr,
            )
            time.sleep(wait)
            attempt += 1
            continue

        raise OcError(
            f"oc {' '.join(args)} failed (exit {result.returncode}):\n{stderr.strip()[:500]}"
        )


def apply_manifest(path: str, *, kubeconfig: str | None = None) -> None:
    """Apply a manifest file. Uses --dry-run=none (real apply)."""
    run_oc(
        ["apply", "-f", path],
        json_output=False,
        kubeconfig=kubeconfig,
        capture_stderr=False,
    )


def delete_manifest(path: str, *, kubeconfig: str | None = None, ignore_not_found: bool = True) -> None:
    """Delete resources defined in a manifest file."""
    extra = ["--ignore-not-found"] if ignore_not_found else []
    run_oc(
        ["delete", "-f", path, *extra],
        json_output=False,
        kubeconfig=kubeconfig,
        capture_stderr=False,
    )


def scale_deployment(
    name: str,
    replicas: int,
    namespace: str,
    *,
    kubeconfig: str | None = None,
) -> None:
    """Scale a Deployment to the given replica count."""
    run_oc(
        ["scale", f"deployment/{name}", "-n", namespace, f"--replicas={replicas}"],
        json_output=False,
        kubeconfig=kubeconfig,
        capture_stderr=False,
    )


def delete_resource(
    kind: str,
    name: str,
    namespace: str,
    *,
    kubeconfig: str | None = None,
    ignore_not_found: bool = True,
) -> None:
    """Delete a named resource."""
    extra = ["--ignore-not-found"] if ignore_not_found else []
    run_oc(
        ["delete", kind, name, "-n", namespace, *extra],
        json_output=False,
        kubeconfig=kubeconfig,
        capture_stderr=False,
    )


def get_events(
    namespace: str,
    *,
    kubeconfig: str | None = None,
) -> list[dict[str, Any]]:
    """Return all events in a namespace as a list of dicts."""
    result = run_oc(["get", "events", "-n", namespace], kubeconfig=kubeconfig)
    return result.get("items", [])


def get_nodes(*, kubeconfig: str | None = None) -> list[dict[str, Any]]:
    """Return all nodes as a list of dicts."""
    result = run_oc(["get", "nodes"], kubeconfig=kubeconfig)
    return result.get("items", [])


def get_node_count(*, kubeconfig: str | None = None) -> int:
    """Return the number of nodes currently in Ready state."""
    nodes = get_nodes(kubeconfig=kubeconfig)
    count = 0
    for node in nodes:
        for cond in node.get("status", {}).get("conditions", []):
            if cond.get("type") == "Ready" and cond.get("status") == "True":
                count += 1
                break
    return count


def get_node_names(*, kubeconfig: str | None = None) -> set[str]:
    """Return a set of Ready node names."""
    nodes = get_nodes(kubeconfig=kubeconfig)
    names: set[str] = set()
    for node in nodes:
        for cond in node.get("status", {}).get("conditions", []):
            if cond.get("type") == "Ready" and cond.get("status") == "True":
                names.add(node["metadata"]["name"])
                break
    return names


def get_ready_node_count_for_label(
    key: str,
    value: str,
    *,
    kubeconfig: str | None = None,
) -> int:
    """Count nodes in Ready state matching ``key=value``."""
    result = run_oc(
        ["get", "nodes", "-l", f"{key}={value}"],
        kubeconfig=kubeconfig,
    )
    count = 0
    for node in result.get("items", []):
        for cond in node.get("status", {}).get("conditions", []):
            if cond.get("type") == "Ready" and cond.get("status") == "True":
                count += 1
                break
    return count


def get_nodes_for_label(
    key: str,
    value: str,
    *,
    kubeconfig: str | None = None,
) -> list[dict[str, Any]]:
    """Return Node API objects matching ``key=value`` (any readiness)."""
    result = run_oc(
        ["get", "nodes", "-l", f"{key}={value}"],
        kubeconfig=kubeconfig,
    )
    return list(result.get("items", []))


def get_cluster_cpu_requests_on_nodes_millicores(
    node_names: set[str],
    *,
    kubeconfig: str | None = None,
) -> int:
    """
    Sum CPU requests (containers + initContainers) for non-terminal pods
    bound to ``spec.nodeName`` in ``node_names`` (all namespaces).
    """
    if not node_names:
        return 0
    terminal = frozenset({"Succeeded", "Failed"})
    total = 0
    for pod in get_pods_all_namespaces(kubeconfig=kubeconfig):
        phase = pod.get("status", {}).get("phase", "")
        if phase in terminal:
            continue
        spec = pod.get("spec") or {}
        node_name = spec.get("nodeName")
        if not node_name or node_name not in node_names:
            continue
        containers = spec.get("containers") or []
        inits = spec.get("initContainers") or []
        total += _container_cpu_requests_millicores(containers)
        total += _container_cpu_requests_millicores(inits)
    return total


def get_cluster_cpu_memory_requests_on_nodes(
    node_names: set[str],
    *,
    kubeconfig: str | None = None,
) -> tuple[int, int]:
    """
    Sum CPU (millicores) and memory (mebibytes) **requests** for non-terminal
    pods bound to ``spec.nodeName`` in ``node_names`` (all namespaces).
    """
    if not node_names:
        return 0, 0
    terminal = frozenset({"Succeeded", "Failed"})
    cpu_total = 0
    mem_total = 0
    for pod in get_pods_all_namespaces(kubeconfig=kubeconfig):
        phase = pod.get("status", {}).get("phase", "")
        if phase in terminal:
            continue
        spec = pod.get("spec") or {}
        node_name = spec.get("nodeName")
        if not node_name or node_name not in node_names:
            continue
        containers = spec.get("containers") or []
        inits = spec.get("initContainers") or []
        cpu_total += _container_cpu_requests_millicores(containers)
        cpu_total += _container_cpu_requests_millicores(inits)
        mem_total += _container_memory_requests_mebibytes(containers)
        mem_total += _container_memory_requests_mebibytes(inits)
    return cpu_total, mem_total


def measure_cpu_slack_for_node_label(
    key: str,
    value: str,
    *,
    kubeconfig: str | None = None,
) -> tuple[float, int, int]:
    """
    Return ``(slack_cores, allocatable_millicores, requested_millicores)`` for
    **only** Ready nodes matching ``key=value``.

    Requested CPU is the sum over non-terminal pods scheduled on those nodes.
    Use this for benchmark pools (e.g. ``pool-type=standard``, ``karpenter.sh/nodepool=...``)
    so preflight slack ignores capacity on other node groups.
    """
    nodes = get_nodes_for_label(key, value, kubeconfig=kubeconfig)
    ready_names: set[str] = set()
    alloc_mc = 0
    for node in nodes:
        if not _node_is_ready(node):
            continue
        meta = node.get("metadata") or {}
        name = meta.get("name")
        if not name:
            continue
        ready_names.add(name)
        alloc = (node.get("status") or {}).get("allocatable") or {}
        cpu = alloc.get("cpu")
        if cpu:
            alloc_mc += _parse_cpu_quantity_to_millicores(str(cpu))
    req_mc = get_cluster_cpu_requests_on_nodes_millicores(ready_names, kubeconfig=kubeconfig)
    slack_cores = (alloc_mc - req_mc) / 1000.0
    return slack_cores, alloc_mc, req_mc


def measure_cpu_memory_slack_for_node_label(
    key: str,
    value: str,
    *,
    kubeconfig: str | None = None,
) -> tuple[float, float, int, int, int, int, int]:
    """
    Return CPU/memory slack for Ready nodes matching ``key=value`` (pool aggregate).

    Each slack is allocatable minus sum of pod requests on those nodes.
    Also returns ``alloc_mc``, ``alloc_mi``, ``req_mc``, ``req_mi``,
    ``ready_node_count``.
    """
    nodes = get_nodes_for_label(key, value, kubeconfig=kubeconfig)
    ready_names: set[str] = set()
    alloc_mc = 0
    alloc_mi = 0
    for node in nodes:
        if not _node_is_ready(node):
            continue
        meta = node.get("metadata") or {}
        name = meta.get("name")
        if not name:
            continue
        ready_names.add(name)
        alloc = (node.get("status") or {}).get("allocatable") or {}
        cpu = alloc.get("cpu")
        if cpu:
            alloc_mc += _parse_cpu_quantity_to_millicores(str(cpu))
        mem = alloc.get("memory")
        if mem:
            alloc_mi += _parse_memory_quantity_to_mebibytes(str(mem))
    req_mc, req_mi = get_cluster_cpu_memory_requests_on_nodes(ready_names, kubeconfig=kubeconfig)
    slack_cores = (alloc_mc - req_mc) / 1000.0
    slack_mib = float(alloc_mi - req_mi)
    return slack_cores, slack_mib, alloc_mc, alloc_mi, req_mc, req_mi, len(ready_names)


def _node_is_ready(node: dict[str, Any]) -> bool:
    for cond in node.get("status", {}).get("conditions", []):
        if cond.get("type") == "Ready" and cond.get("status") == "True":
            return True
    return False


def _parse_cpu_quantity_to_millicores(quantity: str | None) -> int:
    """
    Parse a Kubernetes CPU quantity string to integer millicores.

    Accepts forms like ``500m``, ``1``, ``0.5``, ``2500m``. Nanocores (…n)
    are converted to millicores by integer division.
    """
    if not quantity:
        return 0
    q = quantity.strip()
    if q.endswith("m"):
        return int(q[:-1])
    if q.endswith("n"):
        return int(float(q[:-1]) / 1_000_000)
    # Whole or fractional cores (e.g. "1", "0.25")
    return int(float(q) * 1000)


def _container_cpu_requests_millicores(containers: list[dict[str, Any]]) -> int:
    total = 0
    for c in containers:
        req = (c.get("resources") or {}).get("requests") or {}
        cpu = req.get("cpu")
        if cpu:
            total += _parse_cpu_quantity_to_millicores(str(cpu))
    return total


def _parse_memory_quantity_to_mebibytes(quantity: str | None) -> int:
    """
    Parse a Kubernetes memory quantity string to integer **mebibytes** (Mi).

    Handles ``128Mi``, ``2Gi``, ``2569748480Ki``-style values commonly seen on
    Node ``allocatable`` and pod ``requests``.
    """
    if not quantity:
        return 0
    q = quantity.strip()
    if q.endswith("Ki"):
        return max(1, int(q[:-2]) // 1024)
    if q.endswith("Mi"):
        return int(q[:-2])
    if q.endswith("Gi"):
        return int(float(q[:-2]) * 1024)
    if q.endswith("Ti"):
        return int(float(q[:-2]) * 1024 * 1024)
    if q.endswith("K"):
        return max(1, int(q[:-1]) // 1024)
    if q.endswith("M"):
        return int(q[:-1])
    if q.endswith("G"):
        return int(float(q[:-1]) * 1000)
    try:
        as_bytes = int(q)
        return max(1, as_bytes // (1024 * 1024))
    except ValueError:
        return 0


def _container_memory_requests_mebibytes(containers: list[dict[str, Any]]) -> int:
    total = 0
    for c in containers:
        req = (c.get("resources") or {}).get("requests") or {}
        mem = req.get("memory")
        if mem:
            total += _parse_memory_quantity_to_mebibytes(str(mem))
    return total


def get_cluster_cpu_memory_requests_on_nodes_excluding_namespaces(
    node_names: set[str],
    exclude_namespaces: set[str],
    *,
    kubeconfig: str | None = None,
) -> tuple[int, int]:
    """
    Sum CPU (millicores) and memory (mebibytes) **requests** for non-terminal pods
    scheduled on ``node_names``, skipping pods in ``exclude_namespaces``.
    """
    if not node_names:
        return 0, 0
    terminal = frozenset({"Succeeded", "Failed"})
    cpu_total = 0
    mem_total = 0
    for pod in get_pods_all_namespaces(kubeconfig=kubeconfig):
        phase = pod.get("status", {}).get("phase", "")
        if phase in terminal:
            continue
        ns = pod.get("metadata", {}).get("namespace", "")
        if ns in exclude_namespaces:
            continue
        spec = pod.get("spec") or {}
        node_name = spec.get("nodeName")
        if not node_name or node_name not in node_names:
            continue
        containers = spec.get("containers") or []
        inits = spec.get("initContainers") or []
        cpu_total += _container_cpu_requests_millicores(containers)
        cpu_total += _container_cpu_requests_millicores(inits)
        mem_total += _container_memory_requests_mebibytes(containers)
        mem_total += _container_memory_requests_mebibytes(inits)
    return cpu_total, mem_total


def get_pool_allocatable_cpu_memory_for_label(
    key: str,
    value: str,
    *,
    kubeconfig: str | None = None,
) -> tuple[int, int, int]:
    """
    For **Ready** nodes matching ``key=value``, return
    ``(allocatable_cpu_millicores, allocatable_memory_mebibytes, ready_node_count)``.
    """
    nodes = get_nodes_for_label(key, value, kubeconfig=kubeconfig)
    alloc_mc = 0
    alloc_mi = 0
    ready_count = 0
    for node in nodes:
        if not _node_is_ready(node):
            continue
        ready_count += 1
        alloc = (node.get("status") or {}).get("allocatable") or {}
        if alloc.get("cpu"):
            alloc_mc += _parse_cpu_quantity_to_millicores(str(alloc["cpu"]))
        if alloc.get("memory"):
            alloc_mi += _parse_memory_quantity_to_mebibytes(str(alloc["memory"]))
    return alloc_mc, alloc_mi, ready_count


def get_machinesets(namespace: str, *, kubeconfig: str | None = None) -> list[dict[str, Any]]:
    """Return MachineSet objects in a namespace (e.g. openshift-machine-api)."""
    result = run_oc(["get", "machineset", "-n", namespace], kubeconfig=kubeconfig)
    return result.get("items", [])


def get_machineset_replica_counts(
    namespace: str,
    *,
    kubeconfig: str | None = None,
) -> dict[str, dict[str, int]]:
    """
    Return replica fields per MachineSet name.

    Keys per MachineSet: ``desired`` (spec.replicas), ``ready`` (status.readyReplicas),
    ``available`` (status.availableReplicas). Missing status fields default to 0.
    """
    out: dict[str, dict[str, int]] = {}
    for ms in get_machinesets(namespace, kubeconfig=kubeconfig):
        name = ms.get("metadata", {}).get("name", "")
        if not name:
            continue
        spec = ms.get("spec") or {}
        status = ms.get("status") or {}
        desired = spec.get("replicas")
        if desired is None:
            desired = 0
        out[name] = {
            "desired": int(desired),
            "ready": int(status.get("readyReplicas") or 0),
            "available": int(status.get("availableReplicas") or 0),
        }
    return out


def get_cluster_cpu_allocatable_millicores(*, kubeconfig: str | None = None) -> int:
    """Sum status.allocatable cpu across all Ready worker nodes (all Ready nodes)."""
    total = 0
    for node in get_nodes(kubeconfig=kubeconfig):
        if not _node_is_ready(node):
            continue
        alloc = (node.get("status") or {}).get("allocatable") or {}
        cpu = alloc.get("cpu")
        if cpu:
            total += _parse_cpu_quantity_to_millicores(str(cpu))
    return total


def get_cluster_cpu_requests_millicores(
    namespaces: list[str],
    *,
    kubeconfig: str | None = None,
) -> int:
    """
    Sum CPU requests (containers + initContainers) for non-terminal pods
    in the given namespaces.

    Phases ``Succeeded`` and ``Failed`` are skipped. Used for coarse cluster
    CPU slack estimates (allocatable minus sum(requests)).
    """
    terminal = frozenset({"Succeeded", "Failed"})
    total = 0
    for ns in namespaces:
        for pod in get_pods(ns, kubeconfig=kubeconfig):
            phase = pod.get("status", {}).get("phase", "")
            if phase in terminal:
                continue
            spec = pod.get("spec") or {}
            containers = spec.get("containers") or []
            inits = spec.get("initContainers") or []
            total += _container_cpu_requests_millicores(containers)
            total += _container_cpu_requests_millicores(inits)
    return total


def get_pods_all_namespaces(*, kubeconfig: str | None = None) -> list[dict[str, Any]]:
    """Return all pods in all namespaces as a list of dicts."""
    result = run_oc(["get", "pods", "--all-namespaces"], kubeconfig=kubeconfig)
    return result.get("items", [])


def get_cluster_cpu_requests_all_namespaces(*, kubeconfig: str | None = None) -> int:
    """
    Sum CPU requests (containers + initContainers) for non-terminal pods
    cluster-wide. Same phase rules as ``get_cluster_cpu_requests_millicores``.
    """
    terminal = frozenset({"Succeeded", "Failed"})
    total = 0
    for pod in get_pods_all_namespaces(kubeconfig=kubeconfig):
        phase = pod.get("status", {}).get("phase", "")
        if phase in terminal:
            continue
        spec = pod.get("spec") or {}
        containers = spec.get("containers") or []
        inits = spec.get("initContainers") or []
        total += _container_cpu_requests_millicores(containers)
        total += _container_cpu_requests_millicores(inits)
    return total


def get_pods(
    namespace: str,
    label_selector: str | None = None,
    *,
    kubeconfig: str | None = None,
) -> list[dict[str, Any]]:
    """Return pods in a namespace, optionally filtered by label selector."""
    args = ["get", "pods", "-n", namespace]
    if label_selector:
        args += ["-l", label_selector]
    result = run_oc(args, kubeconfig=kubeconfig)
    return result.get("items", [])


def get_hpa(
    name: str,
    namespace: str,
    *,
    kubeconfig: str | None = None,
) -> dict[str, Any]:
    """Return a HorizontalPodAutoscaler object."""
    return run_oc(  # type: ignore[return-value]
        ["get", "hpa", name, "-n", namespace],
        kubeconfig=kubeconfig,
    )


def hpa_replica_counts(
    name: str,
    namespace: str,
    *,
    kubeconfig: str | None = None,
) -> tuple[int | None, int | None]:
    """Return ``(currentReplicas, desiredReplicas)`` from an autoscaling/v2 HPA status."""
    hpa = get_hpa(name, namespace, kubeconfig=kubeconfig)
    st = hpa.get("status") or {}
    cur = st.get("currentReplicas")
    des = st.get("desiredReplicas")
    cur_i = int(cur) if cur is not None else None
    des_i = int(des) if des is not None else None
    return cur_i, des_i


def patch_deployment_container_command(
    deployment: str,
    namespace: str,
    container_index: int,
    command: list[str],
    *,
    kubeconfig: str | None = None,
) -> None:
    """JSON-patch ``spec.template.spec.containers[i].command`` on a Deployment."""
    import json

    patch_payload = json.dumps(
        [
            {
                "op": "replace",
                "path": f"/spec/template/spec/containers/{container_index}/command",
                "value": command,
            }
        ]
    )
    run_oc(
        [
            "patch",
            "deployment",
            deployment,
            "-n",
            namespace,
            "--type=json",
            "-p",
            patch_payload,
        ],
        json_output=False,
        kubeconfig=kubeconfig,
        capture_stderr=False,
    )


def wait_deployment_rollout(
    deployment: str,
    namespace: str,
    *,
    timeout_s: int,
    kubeconfig: str | None = None,
) -> None:
    """Block until ``kubectl rollout status`` succeeds or times out."""
    run_oc(
        [
            "rollout",
            "status",
            f"deployment/{deployment}",
            "-n",
            namespace,
            f"--timeout={timeout_s}s",
        ],
        json_output=False,
        kubeconfig=kubeconfig,
        capture_stderr=False,
    )


def get_vpa(
    name: str,
    namespace: str,
    *,
    kubeconfig: str | None = None,
) -> dict[str, Any]:
    """Return a VerticalPodAutoscaler object."""
    return run_oc(  # type: ignore[return-value]
        ["get", "vpa", name, "-n", namespace],
        kubeconfig=kubeconfig,
    )


def wait_for_deployment_ready(
    name: str,
    namespace: str,
    *,
    timeout_s: int = 300,
    kubeconfig: str | None = None,
) -> None:
    """Block until a Deployment's pods are all Ready, or raise PollTimeout."""
    run_oc(
        [
            "wait",
            f"deployment/{name}",
            "-n", namespace,
            "--for=condition=Available",
            f"--timeout={timeout_s}s",
        ],
        json_output=False,
        kubeconfig=kubeconfig,
        capture_stderr=False,
    )


def ensure_namespace(name: str, *, kubeconfig: str | None = None) -> None:
    """Create namespace if it doesn't already exist (idempotent)."""
    run_oc(
        ["create", "namespace", name, "--dry-run=client", "-o", "yaml"],
        json_output=False,
        kubeconfig=kubeconfig,
    )
    # The above just validates; apply to actually create
    import pathlib
    import tempfile

    ns_yaml = f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {name}\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(ns_yaml)
        tmp = f.name
    try:
        apply_manifest(tmp, kubeconfig=kubeconfig)
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)


# ── Polling helpers ───────────────────────────────────────────────────────────


def poll_until(
    condition_fn: Callable[[], Any],
    *,
    timeout_s: int,
    interval_s: int = 10,
    label: str = "condition",
) -> Any:
    """
    Call condition_fn() every interval_s until it returns a truthy value or timeout.

    Returns the truthy value returned by condition_fn.
    Raises PollTimeout if timeout_s elapses without a truthy result.

    condition_fn may raise OcError; those are printed as warnings and polling continues.
    """
    deadline = time.monotonic() + timeout_s
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            result = condition_fn()
            if result:
                return result
        except OcError as exc:
            print(f"[poll] {label} — oc error (attempt {attempt}): {exc}", file=sys.stderr)

        remaining = deadline - time.monotonic()
        wait = min(interval_s, max(0, remaining))
        if wait > 0:
            time.sleep(wait)

    raise PollTimeout(
        f"Timed out after {timeout_s}s waiting for: {label}"
    )


def wait_for_event(
    namespace: str,
    reason: str | list[str],
    *,
    timeout_s: int = 1200,
    interval_s: int = 10,
    kubeconfig: str | None = None,
    object_name: str | None = None,
    not_before_ms: int | None = None,
) -> dict[str, Any]:
    """
    Poll events in namespace until one matching the given reason(s) appears.

    `reason` may be a single string or a list of strings — the first event
    whose reason matches any entry in the list is returned.  This handles
    CAS emitting either ``TriggeredScaleUp`` or ``ScaledUpGroup`` depending
    on the OpenShift / CAS version.

    Returns the matching event dict.
    Optionally filter by involvedObject.name == object_name.

    `not_before_ms`: if set, only accept events whose lastTimestamp / eventTime
    is at or after this epoch millisecond value. Use this to avoid stale events
    from earlier phases matching immediately (e.g. CAS scale-up events from
    Phase 1 matching during Phase 2 wave polling).
    """
    import datetime as _dt

    reasons: frozenset[str] = (
        frozenset([reason]) if isinstance(reason, str) else frozenset(reason)
    )

    def _event_ts_ms(ev: dict[str, Any]) -> int | None:
        """Return the event's most-recent timestamp in epoch milliseconds, or None."""
        for field in ("lastTimestamp", "eventTime", "firstTimestamp"):
            raw = ev.get(field)
            if raw:
                try:
                    dt = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    return int(dt.timestamp() * 1000)
                except (ValueError, AttributeError):
                    pass
        return None

    def _check() -> dict[str, Any] | None:
        events = get_events(namespace, kubeconfig=kubeconfig)
        for ev in events:
            if ev.get("reason") not in reasons:
                continue
            if object_name and ev.get("involvedObject", {}).get("name") != object_name:
                continue
            if not_before_ms is not None:
                ts = _event_ts_ms(ev)
                if ts is not None and ts < not_before_ms:
                    continue
            return ev
        return None

    label = "|".join(sorted(reasons))
    print(f"[poll] waiting for event reason={label!r} in ns={namespace!r} ...", file=sys.stderr)
    return poll_until(  # type: ignore[return-value]
        _check,
        timeout_s=timeout_s,
        interval_s=interval_s,
        label=f"event reason={label} in {namespace}",
    )


def wait_for_new_ready_node(
    baseline_names: set[str],
    *,
    timeout_s: int = 1800,
    interval_s: int = 20,
    kubeconfig: str | None = None,
) -> str:
    """
    Poll until a node appears in Ready state whose name is not in baseline_names.

    Returns the new node's name.
    """

    def _check() -> str | None:
        current = get_node_names(kubeconfig=kubeconfig)
        new = current - baseline_names
        return next(iter(new)) if new else None

    print(f"[poll] waiting for new Ready node (baseline: {len(baseline_names)} nodes) ...", file=sys.stderr)
    return poll_until(  # type: ignore[return-value]
        _check,
        timeout_s=timeout_s,
        interval_s=interval_s,
        label="new Ready node",
    )


def wait_for_all_pods_running(
    namespace: str,
    label_selector: str,
    expected_count: int | None = None,
    *,
    timeout_s: int = 1200,
    interval_s: int = 15,
    kubeconfig: str | None = None,
) -> list[dict[str, Any]]:
    """
    Wait until all pods matching label_selector in namespace are Running.

    If expected_count is given, also require at least that many pods.
    Returns the list of Running pod dicts.
    """

    def _check() -> list[dict[str, Any]] | None:
        pods = get_pods(namespace, label_selector, kubeconfig=kubeconfig)
        running = [p for p in pods if p.get("status", {}).get("phase") == "Running"]
        # Pods in terminal/failed states (OutOfcpu, OOMKilled, Error, etc.) are excluded
        # from the "all running" check so transient scheduling failures don't block progress.
        failed_phases = {"Failed", "Succeeded", "Unknown"}
        active = [
            p for p in pods
            if p.get("status", {}).get("phase") not in failed_phases
        ]
        if expected_count is not None and len(running) < expected_count:
            return None
        if not running:
            return None
        # All active (non-failed) pods must be Running
        if len(running) == len(active):
            return running
        return None

    print(
        f"[poll] waiting for pods ({label_selector}) in ns={namespace!r} to be Running ...",
        file=sys.stderr,
    )
    return poll_until(  # type: ignore[return-value]
        _check,
        timeout_s=timeout_s,
        interval_s=interval_s,
        label=f"pods Running ({label_selector}) in {namespace}",
    )


def delete_object(
    kind: str,
    name: str,
    namespace: str,
    *,
    ignore_not_found: bool = True,
    kubeconfig: str | None = None,
) -> None:
    """Delete a namespaced Kubernetes object by kind and name."""
    args = ["delete", kind, name, "-n", namespace]
    if ignore_not_found:
        args += ["--ignore-not-found"]
    run_oc(args, json_output=False, kubeconfig=kubeconfig)


def watch_node_arrivals(
    baseline_names: set[str],
    expected_count: int,
    *,
    timeout_s: int = 2400,
    interval_s: int = 15,
    kubeconfig: str | None = None,
    on_arrival: Callable[[str, int], None] | None = None,
) -> list[tuple[str, int]]:
    """
    Poll until at least expected_count new Ready nodes (beyond baseline) appear.

    Returns a list of (node_name, arrival_timestamp_ms) tuples sorted by arrival time.
    on_arrival(name, timestamp_ms) is called immediately when each new node is detected,
    enabling per-node milestone recording without waiting for the full set.

    Raises PollTimeout if expected_count is not reached within timeout_s.
    """
    seen: dict[str, int] = {}
    deadline = time.monotonic() + timeout_s
    print(
        f"[poll] watching for {expected_count} new Ready nodes "
        f"(baseline: {len(baseline_names)}) ...",
        file=sys.stderr,
    )
    while time.monotonic() < deadline:
        current_names = get_node_names(kubeconfig=kubeconfig)
        ts = int(time.time() * 1000)
        for name in sorted(current_names - baseline_names):
            if name not in seen:
                seen[name] = ts
                print(f"[poll] new Ready node #{len(seen)}: {name}", file=sys.stderr)
                if on_arrival is not None:
                    on_arrival(name, ts)
        if len(seen) >= expected_count:
            return sorted(seen.items(), key=lambda kv: kv[1])
        time.sleep(interval_s)
    raise PollTimeout(
        f"Only {len(seen)}/{expected_count} new nodes became Ready within {timeout_s}s"
    )


def wait_for_all_pods_ready(
    namespace: str,
    label_selector: str,
    expected_count: int | None = None,
    *,
    timeout_s: int = 600,
    interval_s: int = 10,
    kubeconfig: str | None = None,
) -> list[dict[str, Any]]:
    """
    Wait until all pods matching label_selector in namespace are Ready.

    A pod is Ready when its phase is Running AND the Ready condition is True.
    This is the point where the pod is actually serving traffic — distinct from
    phase=Running which only means containers have started.

    If expected_count is given, also require at least that many Ready pods.
    Returns the list of Ready pod dicts.
    """

    def _is_ready(pod: dict[str, Any]) -> bool:
        if pod.get("status", {}).get("phase") != "Running":
            return False
        for cond in pod.get("status", {}).get("conditions", []):
            if cond.get("type") == "Ready" and cond.get("status") == "True":
                return True
        return False

    def _check() -> list[dict[str, Any]] | None:
        pods = get_pods(namespace, label_selector, kubeconfig=kubeconfig)
        ready = [p for p in pods if _is_ready(p)]
        if expected_count is not None and len(ready) < expected_count:
            return None
        if not ready:
            return None
        if len(ready) == len(pods):
            return ready
        return None

    print(
        f"[poll] waiting for pods ({label_selector}) in ns={namespace!r} to be Ready ...",
        file=sys.stderr,
    )
    return poll_until(  # type: ignore[return-value]
        _check,
        timeout_s=timeout_s,
        interval_s=interval_s,
        label=f"pods Ready ({label_selector}) in {namespace}",
    )


def wait_for_node_count_at_most(
    max_count: int,
    *,
    timeout_s: int = 2400,
    interval_s: int = 30,
    kubeconfig: str | None = None,
) -> int:
    """Wait until the number of Ready nodes drops to max_count or fewer. Returns final count."""

    def _check() -> int | None:
        count = get_node_count(kubeconfig=kubeconfig)
        return count if count <= max_count else None

    print(f"[poll] waiting for node count ≤ {max_count} ...", file=sys.stderr)
    return poll_until(  # type: ignore[return-value]
        _check,
        timeout_s=timeout_s,
        interval_s=interval_s,
        label=f"node count ≤ {max_count}",
    )


# ── Karpenter / AutoNode helpers ──────────────────────────────────────────────


def get_nodeclaims(
    *,
    nodepool_name: str | None = None,
    kubeconfig: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return Karpenter NodeClaim objects cluster-wide (NodeClaims are not namespaced).

    If nodepool_name is given, filter to NodeClaims whose
    karpenter.sh/nodepool label matches that name.
    """
    result = run_oc(["get", "nodeclaim"], kubeconfig=kubeconfig)
    items: list[dict[str, Any]] = result.get("items", [])
    if nodepool_name:
        items = [
            nc for nc in items
            if nc.get("metadata", {}).get("labels", {}).get("karpenter.sh/nodepool") == nodepool_name
        ]
    return items


def get_nodeclaim_count(
    *,
    nodepool_name: str | None = None,
    kubeconfig: str | None = None,
) -> int:
    """Return the number of NodeClaims (optionally scoped to a NodePool)."""
    return len(get_nodeclaims(nodepool_name=nodepool_name, kubeconfig=kubeconfig))


def wait_for_new_nodeclaim(
    baseline_count: int,
    *,
    nodepool_name: str | None = None,
    timeout_s: int = 300,
    interval_s: int = 5,
    kubeconfig: str | None = None,
) -> dict[str, Any]:
    """
    Wait until a new NodeClaim appears beyond baseline_count.

    Returns the most-recently created NodeClaim dict.
    Raises PollTimeout if timeout_s elapses without a new NodeClaim.
    """

    def _check() -> dict[str, Any] | None:
        ncs = get_nodeclaims(nodepool_name=nodepool_name, kubeconfig=kubeconfig)
        if len(ncs) <= baseline_count:
            return None
        # Return the most recently created NodeClaim
        return sorted(
            ncs,
            key=lambda nc: nc.get("metadata", {}).get("creationTimestamp", ""),
            reverse=True,
        )[0]

    pool_hint = f" (pool={nodepool_name})" if nodepool_name else ""
    print(
        f"[poll] waiting for new NodeClaim{pool_hint} (baseline: {baseline_count}) ...",
        file=sys.stderr,
    )
    return poll_until(  # type: ignore[return-value]
        _check,
        timeout_s=timeout_s,
        interval_s=interval_s,
        label=f"new NodeClaim{pool_hint}",
    )


def wait_for_nodeclaim_count_at_most(
    max_count: int,
    *,
    nodepool_name: str | None = None,
    timeout_s: int = 1200,
    interval_s: int = 15,
    kubeconfig: str | None = None,
) -> int:
    """
    Wait until the NodeClaim count (optionally scoped to a NodePool) drops to
    max_count or fewer.  Returns the final count.
    """

    def _check() -> int | None:
        count = get_nodeclaim_count(nodepool_name=nodepool_name, kubeconfig=kubeconfig)
        return count if count <= max_count else None

    pool_hint = f" (pool={nodepool_name})" if nodepool_name else ""
    print(f"[poll] waiting for NodeClaim count{pool_hint} ≤ {max_count} ...", file=sys.stderr)
    return poll_until(  # type: ignore[return-value]
        _check,
        timeout_s=timeout_s,
        interval_s=interval_s,
        label=f"NodeClaim count{pool_hint} ≤ {max_count}",
    )


def wait_for_nodepool_ready(
    name: str,
    *,
    timeout_s: int = 120,
    interval_s: int = 5,
    kubeconfig: str | None = None,
) -> None:
    """
    Wait until a Karpenter NodePool has READY=True.

    Checks the .status.conditions list for a condition with type=Ready and
    status=True.  Raises PollTimeout if not reached within timeout_s.
    """

    def _check() -> bool | None:
        try:
            result = run_oc(["get", "nodepool", name], kubeconfig=kubeconfig)
            for cond in result.get("status", {}).get("conditions", []):
                if cond.get("type") == "Ready" and cond.get("status") == "True":
                    return True
        except OcError:
            pass
        return None

    print(f"[poll] waiting for NodePool {name!r} to be Ready ...", file=sys.stderr)
    poll_until(
        _check,
        timeout_s=timeout_s,
        interval_s=interval_s,
        label=f"NodePool {name!r} Ready",
    )
