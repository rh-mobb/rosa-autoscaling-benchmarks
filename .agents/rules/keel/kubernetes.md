---
description: "Kubernetes manifest and workload conventions"
globs: ["**/manifests/**/*.yaml", "**/k8s/**/*.yaml", "**/deploy/**/*.yaml", "**/templates/**/*.yaml", "**/base/**/*.yaml", "**/overlays/**/*.yaml"]
alwaysApply: false
---

# Kubernetes Standards

Standards for writing Kubernetes manifests and managing workloads.

## Manifest Structure

- Set `apiVersion`, `kind`, and `metadata` at the top of every manifest
- Use one resource per file — name the file after the resource kind: `deployment.yaml`, `service.yaml`
- Group related resources in a dedicated directory (`manifests/`, `k8s/`, or `deploy/`)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  labels:
    app.kubernetes.io/name: my-app
    app.kubernetes.io/instance: my-app
    app.kubernetes.io/version: "1.0.0"
    app.kubernetes.io/managed-by: kubectl
```

## Labels and Annotations

- Always apply the standard `app.kubernetes.io/` labels: `name`, `instance`, `version`, `managed-by`
- Use labels for selection and grouping; use annotations for non-identifying metadata
- Keep label values under 63 characters and valid per Kubernetes naming rules
- Define a consistent labeling scheme and apply it to all resources in a project

## Resource Management

- Always define resource requests and limits for containers
- Set `requests` to typical usage; set `limits` to peak expected usage
- Use `LimitRange` and `ResourceQuota` in shared namespaces
- Configure health checks (`livenessProbe`, `readinessProbe`, `startupProbe`) for all containers

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi
```

## Security

- Never run containers as root — set `runAsNonRoot: true` in `securityContext`
- Drop all capabilities and add back only what's needed
- Set `readOnlyRootFilesystem: true` where possible
- Use `NetworkPolicy` to restrict pod-to-pod communication
- Store secrets in external secret managers (Vault, AWS Secrets Manager) — never in plain manifests

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  readOnlyRootFilesystem: true
```

## Networking

- Use `Service` resources to abstract pod access — never rely on pod IPs directly
- Prefer `ClusterIP` for internal services; use `Ingress` or `Gateway` for external access
- Define explicit `port` names in services and deployments for clarity

## Namespaces

- Use namespaces to isolate workloads by team, environment, or application
- Never deploy application workloads into `default` or `kube-system`
- Apply `ResourceQuota` and `LimitRange` per namespace in shared clusters

## Configuration

- Use `ConfigMap` for non-sensitive configuration; use `Secret` for sensitive data
- Mount config as volumes rather than environment variables when files are expected
- Use `immutable: true` on ConfigMaps and Secrets that should not change after creation

## Tooling

- Validate manifests against schemas with `kubeconform` (or `kubeval`)
- Lint manifests with `kube-linter` for best-practice violations
- Use `kubectl diff` to preview changes before applying
- Use `kubectl --dry-run=client -o yaml` to validate generated manifests without applying

## Agent Behavior

Behavioral guidance for AI agents managing Kubernetes resources, whether via `kubectl`, MCP tools, or client libraries.

- Verify the target cluster and context before performing any operations (e.g., `kubectl config current-context`)
- Always scope operations to an explicit namespace — never rely on the default namespace (e.g., `--namespace <ns>`)
- Never operate on `kube-system`, `kube-public`, or other system namespaces without explicit user instruction
- Preview changes before applying — use diff capabilities (e.g., `kubectl diff`) to show what will change
- Prefer declarative apply over imperative create/replace (e.g., `kubectl apply` over `kubectl create`)
- Confirm resource state after mutations — read back the resource to verify the change took effect (e.g., `kubectl get`)
- When deleting, retrieve and display the resource details first (e.g., `kubectl get <resource>`), then ask for user confirmation before executing
- After modifying manifests, run `kubeconform` (if available) to validate schema correctness before applying
