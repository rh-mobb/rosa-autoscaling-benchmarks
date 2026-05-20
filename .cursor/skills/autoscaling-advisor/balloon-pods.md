# R3/R4 — Balloon Pod Implementation Guide

Balloon pods (preemptible pause pods) hold pre-warmed capacity on already-provisioned
nodes. When a real workload pod is scheduled and needs the CPU/memory a balloon occupies,
Kubernetes preempts the balloon instantly (<1 s). The now-pending balloon triggers the
autoscaler to provision a replacement node — keeping the headroom buffer self-healing.

## Mechanism by autoscaler

| Autoscaler | What balloons do |
|---|---|
| CAS | Occupy space on current nodes. Real pods preempt them instantly; balloons go pending; CAS sees pending pods and provisions new node. Workload never waits for provisioning. |
| Karpenter | Prevent Karpenter consolidation from reclaiming lightly-used nodes. Real pods preempt them instantly; pending balloons trigger Karpenter to provision a replacement node. Same zero-wait effect. |

Both autoscalers: the **real workload pod runs immediately** on existing capacity. The balloon
replacement is provisioned in the background.

## Complete YAML template

```yaml
# 1. PriorityClass — negative value ensures balloons are always lowest priority
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: balloon
value: -10                          # any negative integer; avoids displacing system pods
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: "Placeholder pods to hold pre-warmed node capacity"
---
# 2. Balloon Deployment — adjust replicas, cpu/memory, and tolerations to match your pool
apiVersion: apps/v1
kind: Deployment
metadata:
  name: balloon
  namespace: NAMESPACE
spec:
  replicas: REPLICAS                # see sizing below
  selector:
    matchLabels:
      app: balloon
  template:
    metadata:
      labels:
        app: balloon
    spec:
      priorityClassName: balloon
      terminationGracePeriodSeconds: 0   # pause has no SIGTERM handler; skip the 30s drain wait
      containers:
        - name: pause
          image: registry.k8s.io/pause:3.9
          resources:
            requests:
              cpu: CPU_REQUEST      # e.g. 1000m to occupy one node's spare capacity
              memory: MEM_REQUEST   # e.g. 1Gi to occupy one node's spare memory
            # No limits — limits don't affect scheduling and balloon pods should never use real CPU
      # Include toleration if the target node pool has a taint
      tolerations:
        - key: workload
          value: otel-demo
          effect: NoSchedule
          operator: Equal
      # Pin balloons to the dedicated pool so they hold the right nodes
      nodeSelector:
        workload: otel-demo
```

## Sizing formula (R4)

```
REPLICAS = ceil(provision_s / 60 * pods_per_minute_at_burst)

provision_s           — NodeClaim Launched→Ready latency (Karpenter NodeClaim events)
                        or CAS TriggeredScaleUp→node Ready latency
                        Typical values: Karpenter ~260 s, CAS ~240–360 s

pods_per_minute_at_burst — new pods HPA would schedule per minute at peak
                           ≈ (maxReplicas - minReplicas) / scale_duration_min
                           or: observed HPA step size × steps per minute at peak

Example: provision_s=260, 5 new pods/min at burst
  REPLICAS = ceil(260/60 * 5) = ceil(21.7) = 22 pods
  Each pod requests 500m CPU → 22 × 500m = 11 CPU reserved = ~3 m5.large nodes

Practical minimum: size for at least 1 full node's worth of capacity.
  balloon cpu_request × replicas ≥ node_allocatable_cpu
```

## Common mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| `value: 0` on PriorityClass | Risks preempting Kubernetes system pods | Use any negative integer |
| Missing `terminationGracePeriodSeconds: 0` | Pod hangs 30 s during eviction; delays preemption | Add `terminationGracePeriodSeconds: 0` |
| Missing toleration for node pool taint | Balloons don't schedule on dedicated nodes; pre-warmed capacity is on wrong pool | Match taint key/value/effect |
| Setting `resources.limits` | Limits don't affect scheduling; omit them to keep the pod spec honest | Remove limits block |
| Same PriorityClass as low-priority workloads | Balloons may not get preempted correctly | Keep balloon priority strictly negative, below all user workloads |
| Static replicas on a growing cluster | Too few balloons on large cluster → headroom shrinks to zero | Add CPA (see below) |

---

## R12 — Cluster Proportional Autoscaler (CPA)

Static balloon replicas become stale as the cluster grows or shrinks. CPA reads the live
node or core count and continuously updates the balloon Deployment's `replicas` via a
**ladder ConfigMap**. The balloon Deployment and PriorityClass stay exactly as above —
CPA only manages the replica count.

### How it works

```
Cluster adds 4 nodes → CPA reads node count → looks up ladder → patches balloon replicas
Cluster removes 2 nodes → CPA decrements balloon replicas → excess balloons terminate
```

CPA runs as a Deployment in the same namespace as the balloon, or in `kube-system`.
It uses the `--target` flag to identify the Deployment to scale and the `--configmap`
flag to read the ladder.

### Full YAML — CPA + ladder ConfigMap

```yaml
# 1. Ladder ConfigMap — one balloon replica per 2 nodes, minimum 2, maximum 10
apiVersion: v1
kind: ConfigMap
metadata:
  name: balloon-cpa-config
  namespace: NAMESPACE       # same namespace as the balloon Deployment
data:
  ladder: |
    {
      "nodesToReplicas": [
        [  0,  2 ],           # 0–1 nodes  → 2 balloons (floor)
        [  2,  2 ],           # 2–3 nodes  → 2 balloons
        [  4,  3 ],           # 4–5 nodes  → 3 balloons
        [  6,  4 ],           # 6–7 nodes  → 4 balloons
        [  8,  5 ],           # 8–9 nodes  → 5 balloons
        [ 10,  6 ],           # 10–11 nodes → 6 balloons
        [ 20, 10 ]            # 20+ nodes  → 10 balloons (cap)
      ]
    }
---
# 2. RBAC — CPA needs to read nodes and patch the target Deployment
apiVersion: v1
kind: ServiceAccount
metadata:
  name: balloon-cpa
  namespace: NAMESPACE
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: balloon-cpa
rules:
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "deployments/scale"]
    verbs: ["get", "update", "patch"]
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: balloon-cpa
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: balloon-cpa
subjects:
  - kind: ServiceAccount
    name: balloon-cpa
    namespace: NAMESPACE
---
# 3. CPA Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: balloon-cpa
  namespace: NAMESPACE
spec:
  replicas: 1
  selector:
    matchLabels:
      app: balloon-cpa
  template:
    metadata:
      labels:
        app: balloon-cpa
    spec:
      serviceAccountName: balloon-cpa
      containers:
        - name: cpa
          image: registry.k8s.io/cpa/cluster-proportional-autoscaler:1.9.0
          command:
            - /cluster-proportional-autoscaler
            - --namespace=NAMESPACE
            - --configmap=balloon-cpa-config
            - --target=Deployment/balloon
            - --logtostderr=true
            - --v=2
          resources:
            requests:
              cpu: 20m
              memory: 32Mi
            limits:
              cpu: 100m
              memory: 64Mi
```

### Tuning the ladder

The ladder maps **node count → replica count**. Start with:
- **Floor**: enough balloons to hold ~1 node's worth of capacity on a minimal cluster
- **Slope**: ~1 extra balloon per 2 nodes added (adjust based on your burst profile)
- **Cap**: maximum you'd ever want pre-warmed (prevents runaway costs at large scale)

Alternatively use `coresToReplicas` instead of `nodesToReplicas` for finer granularity
on heterogeneous clusters where node size varies significantly.

### Verify CPA is working

```bash
# Watch CPA logs for scaling decisions
oc logs -n NAMESPACE -l app=balloon-cpa -f

# Confirm balloon replica count changes as nodes are added/removed
oc get deployment balloon -n NAMESPACE -w
```
