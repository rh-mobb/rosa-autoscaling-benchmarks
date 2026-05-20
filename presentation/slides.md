---
theme: default
title: "ROSA Classic vs HCP with AutoNode: Autoscaling Benchmarks"
info: |
  Benchmark deck: ROSA Classic (CAS) vs ROSA HCP with AutoNode.
  Cluster lifecycle, workload scale-up/down, controllers, shaping capacity, proactive patterns,
  and consolidated comparison · May 2026.
  Paul Czarkowski · Senior Principal Cloud Specialist · Red Hat · May 2026
highlighter: shiki
lineNumbers: false
fonts:
  sans: Red Hat Text
  serif: Red Hat Display
  mono: JetBrains Mono
---

<!-- SLIDE 1  -  Title -->

# ROSA Classic vs HCP with AutoNode

## Real autoscaling benchmarks from live clusters

CAS and AutoNode head-to-head

<div class="mt-8 text-[var(--rh-muted)]">
Paul Czarkowski · Senior Principal Cloud Specialist · Red Hat · May 2026
</div>

<!--
Speaker note: We ran paired scripted benchmarks on ROSA Classic (CAS) and ROSA HCP with AutoNode. Today: the numbers, the surprises, what they mean for how you design ROSA autoscaling.
-->

---

<!-- SLIDE 2  -  Agenda -->

# Agenda

1. **Architecture**  -  Classic vs HCP topology; CAS vs AutoNode
2. **Cost Structure**  -  Infrastructure savings, Spot + ARM levers, real-world burst
3. **Autoscaling Taxonomy**  -  Fleet vs workload planes; HPA, VPA, balloon pods
4. **Cluster Lifecycle**  -  Install timing; machine pool provisioning
5. **Node Scaling Benchmarks**  -  Progressive waves, bin-pack, scale-down, instance fit
6. **Workload Scaling**  -  HPA response; HPA→autoscaler cascade; overprovisioning
7. **Advanced Autoscaling Patterns**  -  Planned surge; sudden spike
8. **Head-to-Head Results**  -  Benchmark comparison table
9. **Findings & Recommendations**

<!--
Speaker note: Items 1–3 are taxonomy and framing; timed benchmark work starts at item 4. Item 6 (Workload Scaling) has no dedicated section divider  -  it follows directly after the node scaling slides.
-->

---

<!-- SLIDE 3  -  ROSA Classic vs ROSA HCP architecture -->

# ROSA Classic vs ROSA HCP

<RhTwoColumn>
  <template #left>

  ### ROSA Classic
  - **Managed control plane** in customers account
  - Worker nodes in **customer AWS account**
  - Autoscaling via **Cluster Autoscaler** (CAS)
  - CAS scales **MachineSets**  -  Machine API calls `ec2:RunInstances` directly

  </template>
  <template #right>

  ### ROSA HCP (Hosted Control Plane)
  - **Dedicated control plane** in Red Hat's account
  - Worker nodes in **customer AWS account**
  - Autoscaling via **Cluster Autoscaler** (default) or **AutoNode** (opt-in)
  - AutoNode uses **NodeClaims**  -  bin-packs per workload burst
  - Lighter worker bootstrap: fewer system pods, faster node readiness

  </template>
</RhTwoColumn>

> *Same AWS metal. Same region. Same instance type. Different orchestration layer.*

<!--
Speaker note: The key architectural difference: on Classic, CAS talks to Machine API
which calls EC2. On HCP with AutoNode, the AutoNode controller in the hosted control plane issues
NodeClaims and talks to EC2 Fleet directly. The hardware path is the same  -  the
decision loop is fundamentally different.
-->

---

<!-- SLIDE 4  -  Cost structure: Classic vs HCP -->

# Cost Structure: Classic vs HCP

<div class="text-xs text-center text-[var(--rh-muted)] mb-4">
15 × m5.xlarge worker nodes · multi-AZ · us-east-1 · 1-year contract pricing
</div>

<RhTable
  :headers="['Component', 'ROSA Classic', 'ROSA HCP + AutoNode']"
  :rows="[
    ['ROSA service fee  -  15 × m5.xlarge (4 vCPU each)', '$15,000 / yr', '$15,000 / yr'],
    ['ROSA HCP cluster fee ($0.25 / hr × 8,760 hrs)', ' - ', '$2,190 / yr'],
    ['Control plane EC2  -  3 × m5.2xlarge + EBS', '$6,948 / yr', '<em>Hosted by Red Hat</em>'],
    ['Infra nodes EC2  -  3 × r5.xlarge + EBS', '$4,755 / yr', '<em>Not required</em>'],
    ['Worker nodes EC2  -  15 × m5.xlarge + EBS', '$19,170 / yr', '$19,170 / yr'],
    ['<strong>Total (estimated)</strong>', '<strong>~$45,873 / yr</strong>', '<strong>~$36,360 / yr</strong>'],
  ]"
/>

<div class="mt-4 flex items-center justify-center gap-4">
  <span class="text-3xl font-bold" style="color: var(--rh-red); font-family: 'Red Hat Display', sans-serif">~$9,500 / yr saved</span>
  <span class="text-base text-[var(--rh-muted)]">HCP replaces 6 EC2 nodes with a flat $0.25 / hr cluster fee</span>
</div>


<!--
Speaker note: Two distinct fee structures. Classic: no per-cluster ROSA fee, but you fund 6 supporting EC2 nodes (3 control plane m5.2xlarge + 3 infra r5.xlarge). HCP: $0.25/hr flat cluster charge, then workers only  -  Red Hat absorbs the control plane EC2 cost on their side. For 15 workers the cross-over is clearly HCP-favourable (~21% cheaper). The infra-nodes caveat matters at scale: a Classic cluster under sustained load is often further apart because ops teams add a second set of infra nodes to stop monitoring and ingress pods from starving application workloads.
-->

---

<!-- SLIDE 5  -  Two dimensions: cluster vs workload -->

# Two Dimensions of Autoscaling

<div class="text-lg mb-6 space-y-3">

**Cluster Autoscaling** *Fleet Capacity*

Is there enough **schedulable** CPU and memory available for new **Pods**.

- Cluster Auto Scaler (current)
- **AutoNode**  -  event-driven, opt-in (**new**)

**Pod Autoscaling**  *Application Performance*

How many **replicas** and how much CPU/memory **per Pod** ?

- **Cluster AutoScaler** and **AutoNode**  -  **cluster** plane (fleet capacity).
- **HPA** and **VPA**  -  **workload** plane (Pod count and sizing).
</div>

HPA often reacts in **seconds**; adding nodes is commonly **minutes**  -  balloons / overprovisioning **reserve slack on the cluster** so workloads don’t stall in **Pending**.

<!--
Speaker note: Every benchmark belongs in one or both buckets. Use this frame when reading the numbered scenario list next.
-->

---

<!-- SLIDE 6  -  Cluster plane: CAS vs AutoNode -->

# Cluster Scaling  -  CAS vs AutoNode
5 to 7 minutes to add capacity
<RhTwoColumn>
  <template #left>

  ### Cluster Autoscaler (CAS)
  - adds/removes **workers** via **MachineSets** for schedulable capacity
  - **Uniform pools**  -  one instance type per MachineSet (**m5.xlarge** baseline here)
  - Controllers polling **capacity pressure** (**~10–30s** class reaction before scale‑out kicks in)
  **Where:** ROSA **Classic**. ROSA **HCP** when AutoNode is **off**.

  </template>
  <template #right>

  ### AutoNode
  - **NodeClaims** → EC2 (**Fleet**) for schedulable capacity
  - **Per‑burst sizing**  -  can pick SKU/family that fits pending workloads (vs locked pool SKU)
  - **Event‑driven** path from Pods **Pending** (sub‑second reaction to signal)
  **Where:** ROSA **HCP** **opt‑in**. **Not available** on Classic.

  </template>
</RhTwoColumn>

<br><br><br>
> Neither replaces **HPA/VPA**  -  they **bring nodes**, not replicas.

<!--
Speaker note: For CAS scale‑down cooldown, AutoNode consolidation, and pooling behaviour, see progressive scale‑up / scale‑down (Section **5**) and consolidated table (Section **8**)  -  slides **4–5** are the cluster plane taxonomy.
-->

---

<!-- SLIDE 7  -  Additional capacity levers: Spot & ARM -->

# Additional Capacity Levers  -  Spot & ARM

<RhTable
  :headers="['', 'ROSA Classic (CAS)', 'ROSA HCP + AutoNode']"
  :rows="[
    ['<strong>Spot instances</strong>', 'Separate MachineSet per instance type × AZ; manual fallback logic', 'NodePool <code>capacity-type: spot,on-demand</code>  -  automatic on-demand fallback'],
    ['<strong>ARM (Graviton)</strong>', 'Separate ARM MachineSet; workloads must target the right pool', 'NodePool <code>arch: arm64</code> or mixed  -  AutoNode selects per workload'],
    ['<strong>Spot + ARM combined</strong>', 'One MachineSet per (type × arch × AZ)  -  combinatorial growth', 'Single NodePool  -  AutoNode picks the optimal combination at scheduling time'],
    ['<strong>Spot interruption drain</strong>', 'Node Termination Handler (NTH) required separately', 'Native graceful drain on 2-min EC2 interruption notice'],
  ]"
/>

<div class="mt-5 text-sm max-w-4xl mx-auto pl-4 border-l-4 text-[var(--rh-muted)]" style="border-color: var(--rh-yellow);">

<strong style="color: var(--rh-text)">Takeaway  - </strong> Both cluster types <em>support</em> Spot and ARM. The difference is operational: CAS requires a separate MachineSet for every instance family × architecture × AZ permutation. AutoNode collapses this into a single NodePool  -  and resolves the optimal combination at scheduling time.

</div>

<!--
Speaker note: The capability gap is not about support  -  it's about operational surface. A typical "Spot with ARM fallback to on-demand x86 across 3 AZs" CAS setup needs 6+ MachineSets + NTH DaemonSet + priority ordering. AutoNode: one NodePool with requirements listing both arch values and both capacity types. Spot interruption handling is also built in  -  no extra operator to install.
-->

---

<!-- SLIDE 8  -  Cost impact: Spot & ARM workers -->

# Cost Impact  -  Spot & ARM Workers

<div class="text-xs text-center text-[var(--rh-muted)] mb-3">
ROSA HCP + AutoNode · 15 workers · us-east-1 · Spot = typical market rate (~70% off on-demand)
</div>

<RhTable
  :headers="['Worker strategy', 'vs on-demand x86', 'Worker EC2 / yr', 'Total HCP cluster / yr']"
  :rows="[
    ['On-demand x86  -  m5.xlarge <em>(baseline)</em>', ' - ', '$25,230', '~$46,740'],
    ['On-demand ARM  -  m7g.xlarge', '−15%', '~$21,440', '~$42,950'],
    ['Spot x86  -  m5.xlarge', '−70%', '~$7,570', '~$29,080'],
    ['Spot ARM  -  m7g.xlarge', '−73%', '~$6,430', '~$27,940'],
  ]"
/>

<div class="mt-4 grid grid-cols-2 gap-6 max-w-4xl mx-auto">
  <div class="text-center">
    <div class="text-3xl font-bold" style="color: var(--rh-red); font-family: 'Red Hat Display', sans-serif">up to ~$18,800 / yr</div>
    <div class="text-sm text-[var(--rh-muted)] mt-1">saved on worker EC2 alone<br>(Spot ARM vs on-demand x86)</div>
  </div>
  <div class="text-center">
    <div class="text-3xl font-bold" style="color: var(--rh-red); font-family: 'Red Hat Display', sans-serif">~50% cheaper</div>
    <div class="text-sm text-[var(--rh-muted)] mt-1">HCP Spot ARM vs Classic on-demand x86<br>(~$27,940 vs ~$56,350)</div>
  </div>
</div>

<div class="mt-4 text-xs max-w-4xl mx-auto pl-4 border-l-4 text-[var(--rh-muted)]" style="border-color: var(--rh-yellow);">
<strong style="color: var(--rh-text)">⚠ Not a typical production baseline  - </strong> running <em>all</em> workers on Spot accepts the risk of simultaneous interruptions across the fleet. This model fits <strong>dev / test / batch clusters</strong> where a brief outage is tolerable and cost savings dominate. For production, keep steady-state nodes on reserved on-demand and reserve Spot for burst capacity  -  see next slide.
</div>

<!--
Speaker note: Flag the Spot-all-workers scenario explicitly  -  it's compelling for dev/test/batch but a bad fit for most production SLOs. Spot interruptions are rare but not negligible, and a large Spot fleet can see correlated reclamation during peak AWS demand. The next slide shows the more realistic production model: reserved steady state + Spot burst, where AutoNode earns its keep by selecting the cheapest available capacity only for the overflow.
-->

---

<!-- SLIDE 9  -  Real-world burst cost: reserved steady state + autoscaled overflow -->

# Real-World Burst Cost
Reserved Base + Autoscaled Overflow

<div class="text-xs text-center text-[var(--rh-muted)] mb-3">
15 reserved on-demand workers (steady state) · burst = 10 days/month (2,880 hrs/yr per node) · us-east-1
</div>

<RhTwoColumn>
  <template #left>

  ### CAS (Classic)  -  min 3 nodes

  <RhTable
    :headers="['Burst strategy', 'Floor / yr', '5 nodes / yr', '10 nodes / yr']"
    :rows="[
      ['On-demand x86', '$0 †', '$3,380', '$6,760'],
      ['On-demand ARM', '+$5,406', '$8,366', '$11,326'],
      ['Spot x86', '+$2,646', '$4,096', '$5,546'],
      ['<strong>Spot ARM</strong>', '<strong>+$2,409</strong>', '<strong>$3,729</strong>', '<strong>$5,049</strong>'],
    ]"
  />

  <div class="text-xs text-[var(--rh-muted)] mt-2">† on-demand x86 reuses existing worker pool  -  no new MachineSet needed</div>

  </template>
  <template #right>

  ### AutoNode  -  scales from zero

  <RhTable
    :headers="['Burst strategy', '5 nodes / yr', '10 nodes / yr']"
    :rows="[
      ['On-demand x86', '$3,380', '$6,760'],
      ['On-demand ARM', '$2,960', '$5,920'],
      ['Spot x86', '$1,450', '$2,900'],
      ['<strong>Spot ARM</strong>', '<strong>$1,320</strong>', '<strong>$2,640</strong>'],
    ]"
  />

  </template>
</RhTwoColumn>

<div class="mt-3 text-xs text-center text-[var(--rh-muted)]">
All costs include ROSA on-demand service fee · CAS floor = 3 × always-on nodes (8,760 hrs/yr) · steady-state reserved costs identical for both and excluded
</div>

<!--
Speaker note: The standing floor is not a configuration choice  -  ROSA Classic cannot scale MachineSets to zero (scale-to-zero is a ROSA HCP-only capability). Every MachineSet type on Classic requires at least 1 node per AZ to be running at all times, so any burst pool beyond the existing on-demand x86 workers carries a permanent 3-node overhead 24/7. AutoNode (HCP) scales from 0; AutoNode provisions the first node of any type only when a pod actually needs it. For Spot ARM burst: AutoNode costs $1,320/yr (5 nodes) vs CAS $3,729/yr  -  a 2.8× difference driven entirely by the 3-node standing floor ($2,409/yr). That gap is fixed regardless of burst size. Add the ~$9,500 HCP infrastructure saving and the combined AutoNode advantage reaches ~$11,900–$14,000/yr vs Classic CAS.
-->

---

<!-- SLIDE 10  -  Workload plane: HPA vs VPA -->

# Workload Scaling  -  HPA vs VPA
HPA and VPA do not play nicely together, recommend VPA in **advise-only** mode.

<RhTwoColumn>
  <template #left>

  ### Horizontal Pod Autoscaler (HPA)
  - Changes **ReplicaSet / Deployment replicas**
  - **Signals**  -  CPU, memory; **custom** / **external** metrics when adapters expose APIs
  - Needs **schedulable space**  -  if cluster is tight, Pods stay **Pending**

  </template>
  <template #right>

  ### Vertical Pod Autoscaler (VPA)
  - CPU/memory **requests** (sometimes limits), **not** replica count
  - Recommendations from **historic** usage (**advise** mode in these runs avoids eviction churn)
  - **`auto`** can evict Pods to resize  -  **avoid** pairing with Pods **HPA** scales wildly

  </template>
</RhTwoColumn>
<br><br><br>

> Cannot provision Pods if there's no capacity, almost always paired with Cluster Autoscaling.

<!--
Speaker note: HPA answers “how wide”; VPA answers “how chunky per replica”. Both reshape demand the cluster plane must satisfy.
-->

---

<!-- SLIDE 11  -  Elasticity between planes: balloon pods -->

# Elasticity Between Planes  -  Balloon Pods

<div class="text-sm text-[var(--rh-muted)] text-center mb-4">

Low‑priority **pause Pods** reserve CPU/memory slots ahead of bursts  -  the scheduler preempts them instantly when real workloads arrive, bridging <strong>seconds‑scale HPA decisions</strong> and <strong>minute‑scale node provisioning</strong>.

</div>

<BalloonPodsAnimation />

<div class="mt-4 max-w-4xl mx-auto text-sm pl-4 border-l-4" style="border-color: var(--rh-red); color: var(--rh-muted);">

<strong style="color: var(--rh-text)">Insight -</strong> The trick is to have <em>just enough</em> balloon capacity to keep your app healthy for the <strong>5-7 minutes</strong> it takes a new node to provision - no more, no less. Too few balloons and the spike kills you before the node arrives; too many and you are paying for idle reserved capacity 24/7.

</div>

<!--
Speaker note: Bridge to benchmarks: cascade test without slack vs balloon / proactive patterns (planned surge, sudden spike phase 2, overprovisioning).

Karpenter / AutoNode design note (if asked): The pattern is identical in principle, but the balloon Deployment needs one extra rule for Karpenter that CAS does not require  -  strict podAntiAffinity (one pod per node). Without it, Karpenter's bin-packing can land all 5 balloon replicas on a single node, giving you 1 node of headroom instead of 5. After eviction, Karpenter's consolidation loop then sees room to pack the pending balloons back onto existing nodes and never re-provisions the headroom node. The anti-affinity rule defeats both: (a) forces Karpenter to provision N separate headroom nodes upfront, and (b) prevents consolidation from sweeping them away  -  Karpenter cannot find another node that satisfies the constraint, so it marks the node non-consolidatable and moves on. The karpenter.sh/do-not-disrupt annotation is intentionally absent on the balloon pods; you want them to be preemptable so real workloads land instantly and the evicted pod going Pending is what re-triggers provisioning. CAS does not need anti-affinity because it reacts to any unschedulable pod, not to spreading.

Production hardening (if asked): in a production cluster you can add belt-and-suspenders by splitting headroom into its own NodePool with consolidationPolicy: WhenEmpty. Karpenter will never consider a node for consolidation if any pod is running on it, so the balloons are protected at the policy level regardless of scheduling rules. The application NodePool keeps WhenEmptyOrUnderutilized for cost efficiency. The benchmarks use a single pool with anti-affinity because multi-pool tracking adds complexity to the measurement scripts; the protection is equivalent for the benchmark scenario.
-->

---

<!-- SLIDE 12  -  Benchmarks overview -->

# What We Benchmarked

<div class="text-sm text-[var(--rh-muted)] max-w-5xl mx-auto mb-6">

<strong>Paired runs</strong>  -  same scripted workloads, <strong>m5.xlarge</strong> workers baseline, <strong>us-east‑1</strong>, stopwatch milestones. <strong>ROSA Classic (CAS)</strong> vs <strong>ROSA HCP + AutoNode</strong>.

</div>

<RhTwoColumn>
  <template #left>

  ### Cluster & Capacity
  1. **Cluster install**
  2. **Machine pools** creation
  3. **Scale‑up** - basic cluster scale up
  4. **Scale‑down**  -  basic cluster scale down
  5. **Instance fit**  -  workload larger than instances

  </template>
  <template #right>

  ### Workload, Balloons, Advanced
  6. **HPA**  -  breach → new replicas Ready
  7. **HPA → autoscaler**  -  minutes when the cluster is tight
  8. **Balloon pods**  -  headroom + HPA burst
  9. **Advanced**  -  planned surge, sudden spike, parallel node provisioning
  </template>
</RhTwoColumn>

<!--
Speaker note: Left column covers the cluster plane (install, pools, scale-up/down, instance fit).
Right column covers workload scaling - HPA with spare capacity, HPA cascading into the autoscaler
when capacity is exhausted, balloon pods absorbing a burst, and advanced surge/spike patterns.
VPA is covered in the autoscaling taxonomy section as an advise-only tool, not a timed benchmark.
-->
---
layout: section
class: section-header
---

<!-- SLIDE 13  -  Cluster Lifecycle -->

# Cluster Lifecycle
## Install timing · Machine pool provisioning

<!--
Speaker note: From zero to schedulable  -  Classic vs HCP + AutoNode. Skipped in deck: detailed AutoNode prereqs (IAM, subnet/SG discovery tags, `rosa edit cluster --autonode=enabled`); scripted in `clusters/classic-vs-hcp_autonode/create.sh`, typically &lt;2 min atop HCP Ready  -  see next timelines.
-->

---

<!-- SLIDE 14  -  Cluster install animation -->

# Cluster Install  -  Classic vs HCP

<ClusterInstallAnimation />

<div class="mt-3 max-w-5xl mx-auto text-sm pl-4 border-l-4" style="border-color: var(--rh-red); color: var(--rh-muted);">

<strong style="color: var(--rh-text)">Insight -</strong> HCP's control plane runs in <strong>Red Hat's infrastructure</strong> and is ready in moments - your longest wait is EC2 spinning up worker nodes (~13 min). Classic must provision its entire control plane, infra nodes, <em>and</em> workers in your account, stacking the waits to ~53 min.

</div>

<!--
Speaker note: The key visual is the Hosted Control Plane box on the right - it is already lit before
the animation even starts. Red Hat runs that in their account; you pay nothing for it and wait
nothing for it. Classic's three-stage provisioning (control plane -> infra -> workers) is the
bottleneck. The 3.5x speedup matters most for teams iterating on cluster config, running ephemeral
benchmark clusters, or needing fast disaster recovery.
-->


---

<!-- SLIDE 15  -  Classic vs HCP install comparison -->

# Cluster Install: Classic vs HCP

<RhTable
  :headers="['Milestone', 'ROSA Classic', 'ROSA HCP + AutoNode', 'Speedup']"
  :rows="[
    ['OCM cluster Ready', '52m', '13m', '4×'],
    ['oc login OK + workers Ready', '52m', '13m', '4×'],
    ['ClusterOperators Available', '53m', '13m', '4×'],
    ['AutoNode enabled + CRDs Ready', 'N/A', '15m', ' - '],
    ['Total (usable cluster)', '53m', '15m', '3.5×'],
  ]"
/>

<div class="text-center mt-6">
  <span class="text-4xl font-bold" style="color: var(--rh-red); font-family: 'Red Hat Display', sans-serif">3.5× faster</span>
  <span class="text-xl ml-4 text-[var(--rh-muted)]">to a fully operational cluster</span>
</div>

<!--
Speaker note: HCP's control plane is already running in Red Hat's account  -
you only wait for your workers to bootstrap (~13 min) and the AutoNode setup (~2 min).
Classic must provision the entire control plane from scratch, which takes ~52 min.
The 3.5× speedup matters most for teams that iterate on cluster config, run ephemeral
benchmark clusters, or need fast disaster recovery.
-->

---

<!-- SLIDE 16  -  Machine pool provisioning -->

# Machine Pool Provisioning: Classic vs HCP

<RhTable
  :headers="['Instance type', 'ROSA Classic', 'ROSA HCP', 'Saved']"
  :rows="[
    ['Standard  -  m5.xlarge (4 vCPU / 16 GiB)',    '9m 48s',  '5m 17s', '~4m 30s'],
    ['Memory  -  r5.xlarge (4 vCPU / 32 GiB)',      '8m 32s',  '5m 16s', '~3m 15s'],
    ['Compute  -  c5.xlarge (4 vCPU / 8 GiB)',      '10m 10s', '5m 22s', '~4m 48s'],
    ['Bare metal  -  m5.metal (96 vCPU / 384 GiB)', '22m 44s', '18m',    '~4m 44s'],
  ]"
/>

<div class="text-center mt-6">
  <span class="text-4xl font-bold" style="color: var(--rh-red); font-family: 'Red Hat Display', sans-serif">~4 minutes</span>
  <span class="text-xl ml-4 text-[var(--rh-muted)]">saved regardless of instance type  -  HCP's lighter bootstrap path, not EC2 hardware differences.</span>
</div>

<!--
Speaker note: The multiplier looks different per row (1.3–1.9×) because the baselines vary,
but the absolute saving is ~4 minutes across all four types  -  including bare metal.
That consistency points to a fixed overhead in Classic's bootstrap path that HCP eliminates.
EC2 hardware init time is identical for both; HCP just does less work on top of it.
-->

---
layout: section
class: section-header
---

<!-- SLIDE 17  -  Node Scaling Benchmarks -->

# Node Scaling Benchmarks
## Classic vs HCP + AutoNode  -  live cluster results

<!--
Speaker note: Now the core of the talk: head-to-head benchmark results
for each major autoscaling scenario.
-->

---

<!-- SLIDE 18  -  Benchmark methodology -->

# How We Measured

<RhTwoColumn>
  <template #left>

  ### Common setup
  - Same instance type: **m5.xlarge** on-demand
  - Same region: **us-east-1**
  - Same workload: CPU-heavy pods, **1500m** request each
  - **No HPA** - we'll test those later
  - Wave design: +2 replicas per step (1 node)

  </template>
  <template #right>

  ### What we timed

  **Scale-up**
  1. Workload applied → autoscaler decision
  2. Decision → node Ready (EC2 + bootstrap)
  3. Node Ready → pods Running

  **Scale-down / consolidation**
  1. Workload removed → node cordoned
  2. Cordon → node gone from cluster

  </template>
</RhTwoColumn>

<div class="mt-4 text-sm text-center text-[var(--rh-muted)]">

<strong>AutoNode:</strong> "decision" = NodeClaim created &nbsp;·&nbsp; <strong>CAS:</strong> "decision" = <code>TriggeredScaleUp</code> event

</div>

<!--
Speaker note: The key design choice: no HPA. HPA adds its own latency  -
metric scrape interval, 15s evaluation cycle  -  which we measure separately
in the HPA slides later in the deck. Direct replica scaling gives clean autoscaler-only numbers.
1500m CPU requests ensure every +2 replica wave needs exactly 1 new node
on both cluster types, making scale-up waves directly comparable.
-->

---

<!-- SLIDE 19  -  Scale-up state diagrams -->

# How Scale-Up Works

<div class="text-xs text-center text-[var(--rh-muted)] mb-3">

<span style="color:#f59e0b">■</span> waiting &nbsp;&nbsp; <span style="color:#22c55e">■</span> action

</div>

<ScaleUpPipeline />

<div class="mt-4 max-w-4xl mx-auto text-sm pl-4 border-l-4" style="border-color: var(--rh-red); color: var(--rh-muted);">

<strong style="color: var(--rh-text)">Insight  - </strong> After bootstrap, EC2 is the heavy lift for both paths. Before that: <strong>AutoNode</strong> reacts to <strong><code>Pending</code></strong> pods immediately and picks a <strong>workload-shaped</strong> instance. <strong>CAS</strong> waits for <strong><code>FailedScheduling</code></strong> then a <strong>poll interval</strong>, then grows a <strong>uniform pool-shaped</strong> node  -  three <span style="color:#f59e0b">orange</span> waiting states before anything moves.

</div>

<!--
Speaker note: The fork is behavioural, not infra. Same AWS provisioning story once the decision is made;
AutoNode can rightsize capacity to the pods in flight; CAS grows MachineSet replicas  -
granularity is the pool, not a single burst workload. Pending → NodeClaim fires in roughly a second on our runs;
CAS’s loop idle time is where decision latency (e.g. 34 s–2 m) comes from.
-->

---

<!-- SLIDE 20  -  Combined scale-up results -->


# Scale-Up Results  -  CAS vs AutoNode

<RhTwoColumn>
  <template #left>

  ### CAS (Classic)

  | Wave | EC2→Ready | Pods&nbsp;Up | Total | Nodes |
  |---|---|---|---|---|
  | **0** |  -  |  -  |  -  | **3** |
  | **1** |  -  | **2 min** | **2 min** | **3** |
  | **2** |  -  | **2 min** | **2 min** | **3** |
  | **3** | **7 min** | **<1 min** | **8 min** | **4** |

  </template>
  <template #right>

  ### AutoNode (HCP)

  | Wave | EC2→Ready | Pods&nbsp;Up | Total | Nodes |
  |---|---|---|---|---|
  | **0** |  -  |  -  |  -  | **0** |
  | **1** | **4&nbsp;min** | **<1&nbsp;min** | **5&nbsp;min** | **1** |
  | **2** | **4&nbsp;min** | **<1&nbsp;min** | **5&nbsp;min** | **2** |
  | **3** | **5&nbsp;min** | **1&nbsp;min** | **6&nbsp;min** | **3** |

  </template>
</RhTwoColumn>

<div class="mt-6 text-sm text-center text-[var(--rh-muted)]">

<strong>Takeaway:</strong> <strong>EC2→Ready</strong> is still the bottleneck when CAS enlarges the pool  -  before that, <strong>behavior</strong> differs: <strong>new node each wave</strong> (AutoNode) vs <strong>scheduler absorbing slack</strong> on an unchanged worker footprint.

</div>

<!--
Speaker note:

**Decision latency (~10 s):** negligible next to EC2 bootstrap. CAS showed **~17 s** polling-to-trigger in this CAS run; AutoNode surfaced a NodeClaim **~8 s**  -  both are drowned out by **`~minutes`** of AMI + boot variance.

**Column recap:** *EC2→Ready* = CAS decision → **new standard-pool worker Ready** (blank when `scale_fits_existing_capacity`). *Pods Up* ≈ workload visible on-cluster. *Total* = `.scale_to_pods_ready` wall clock · *Nodes* = **standard `pool-type` Ready workers after each wave** (paired Test **14** CAS runs).

Wave **1–2**: fleet stayed **3 workers** despite higher replica counts (scheduler reused slack).

Wave **3**: first CAS-provisioned worker in Phase&nbsp;2 of that attempt → **4 workers**.

Wave **0** = steady baseline before scripted increments. AutoNode waves **1–3** are three scripted capacity steps (no extrapolated filler row).

-->

---

<!-- SLIDE 21  -  Bin-packing vs spreading trade-off -->

# Bin-Packing vs Spreading: A Design Choice

<div class="text-sm text-center text-[var(--rh-muted)] mb-5 max-w-3xl mx-auto">

Same workloads, same EC2 - <strong>different packing.</strong> Bin-pack (<strong>cost</strong>) vs spread (<strong>slack + HA</strong>).

</div>

| | AutoNode | CAS + scheduler |
|---|---|---|
| Primary goal | **Cost** (**pack**) | **Resilience** (**spread**) |
| Each increment | Usually **needs new EC2** | **Slack first**, then overflow |
| Peak nodes | **Higher** | **Lower** |
| Once load falls | Consolidate **≈ 30 s** | **~20 m+ idle** (**cooldowns**) |
| One node outage | **Bigger blast** | **Smaller blast** |

<!--
Speaker note: This is why the benchmark results look the way they do.
AutoNode triggered a new node on every +2 replica wave because it packed the
initial pods tightly  -  leaving almost no room. CAS absorbed early slack waves
because the OCP scheduler spread the initial pods across nodes, leaving ~1850m
free per worker.

The lifecycle comparison: during a load spike, AutoNode provisions more nodes
than CAS  -  but consolidateAfter: 30s means those nodes are reclaimed almost
immediately once load drops. CAS provisions fewer nodes during load, but
scale-down-unneeded-time (10m) + scale-down-delay-after-add (10m) means idle
nodes sit for 20+ minutes before CAS removes them. Over a day with multiple
load cycles, AutoNode's aggressive consolidation likely costs less.

Neither behaviour is wrong; they optimise for different goals.
For cost-sensitive stateless workloads: AutoNode wins on both provisioning speed
and long-term cost via consolidation.
For HA-critical workloads where node failure tolerance matters: CAS's spreading
is a feature, not a bug  -  and the 20-min idle cost may be an acceptable price.
-->

---

<!-- SLIDE 22  -  Scale-down state diagrams -->

# How Scale-Down Works

<ScaleDownPipeline />

<div class="mt-1 max-w-4xl mx-auto text-xs pl-3 border-l-2" style="border-color: #333; color: var(--rh-muted);">

AutoNode loops through <strong>Evaluating → No Action</strong> until pods can repack onto fewer nodes, then moves in one fast burst (cordon → evict → terminate). CAS sits in a long <strong>Cooldown</strong> waiting out policy timers before it acts at all.

</div>

<div class="mt-4 max-w-4xl mx-auto text-sm pl-4 border-l-4" style="border-color: var(--rh-red); color: var(--rh-muted);">

<strong style="color: var(--rh-text)">Insight  - </strong> AutoNode sheds nodes when workloads <strong>repack</strong> cleanly  -  short debounce (<strong><code>consolidateAfter</code></strong>; <strong>30 s</strong> here). CAS sheds on <strong>utilisation thresholds</strong> plus <strong>cooldown timers</strong> (often <strong>~10 min</strong>)  -  reclaim is driven by policy, not packing alone.

</div>

<!--
Speaker note: AutoNode’s loop is the key story  -  it checks whether pods can repack (Evaluating),
and if not yet, it backs off and watches again (No Action). Once the scheduler confirms the
remaining nodes can absorb everything, it moves fast: cordon → evict → terminate in seconds.
CAS has no repack check  -  it just waits out fixed timers (scale-down-unneeded-time,
scale-down-delay-after-add) before acting, which is why the benchmark shows ~10m regardless.
-->

---

<!-- SLIDE 23  -  Combined scale-down results -->

# Scale-Down Results  -  CAS vs AutoNode

<RhTwoColumn>
  <template #left>

  ### CAS (Classic)

  | Phase | Elapsed |
  |---|---|
  | Workload removed → node cordoned | 2s |
  | Cordon → node removed | 9m 54s |
  | **Total** | **9m 56s** |

  </template>
  <template #right>

  ### AutoNode (HCP)

  | Phase | Elapsed |
  |---|---|
  | **Workload deleted** (t₀) | **0 s** |
  | → **Ready node removed** | **1 m 54 s** |
  | **Total** | **1 m 54 s** |

  </template>
</RhTwoColumn>

<div class="mt-3 text-sm text-center text-[var(--rh-muted)]">

AutoNode: <strong>~1 m 54 s</strong> workload delete → <strong>Ready node gone</strong> · CAS: <strong>~10 min</strong> cooldown before cordon

</div>

<!--
Speaker note: Presenter shorthand  -  delete is **t₀**; **~1 m 54 s** bridges first reclaim signal and stable tally (sub‑second variance). Multi‑step consolidation after stacked waves behaves differently  -  call that out verbally if asked.
-->

---

<!-- SLIDE 24  -  Instance fit: pool SKU vs flexible NodePool -->

# Bigger Workload Needs a Bigger Worker

new workload - 28 cpu / 200 GiB
<RhTwoColumn>
  <template #left>

  ### CAS  -  **m5.xlarge** worker pool

  | Phase | Result |
  |---|---|
  | `FailedScheduling` | Won't fit on **m5.xlarge** |
  | CAS decision | **`NotTriggerScaleUp`** |
  | pod pending | indefinitely |

  A CAS machine pool has <strong>fixed</strong> instance type
  </template>
  <template #right>

  ### AutoNode  -  flexible NodePool

  | Phase | Result |
  |---|---|
  | `FailedScheduling` → NodeClaim | **1 s** |
  | NodeClaim →  **r5.16xlarge** | **4m 42s** |
  | Node Ready → pod Running | **1 s** |

  NodePool delegates <strong>instance choice</strong>

  </template>


</RhTwoColumn>

<div class="mt-4 text-sm text-center text-[var(--rh-muted)]">

Autonode prefers to provision a larger instance over starving the workload

</div>

<!--
Speaker note: “Stranding” narrative  -  workloads that exceeded the scripted pool SKU. Classic shows NotTriggerScaleUp; AutoNode provisions a permissive SKU.
              AutoNode scored allowed shapes and chose **memory-optimized `r5.16xlarge`** to satisfy the workload.
              Worth noting the CAS is often more conservative than the kube scheduler, so a workload that /was/ scheduled may become unschedulable via CAS.
-->

---

<!-- SLIDE 25  -  HPA benchmark (Test 06): seconds vs cluster minutes -->

# HPA  -  Seconds, Not Minutes *(when capacity exists)*

**spare schedulable workers** *(isolates HPA + scheduler  -  not node provisioning)*

<RhTwoColumn>
  <template #left>

  ### Classic CAS

  | Segment | Time |
  |---|---|
  | Metric breach → scale decision | **Sub‑second** |
  | Metric breach → pods **Ready** | **3.7 s** |

  </template>
  <template #right>

  ### HCP + AutoNode

  | Segment | Time |
  |---|---|
  | Metric breach → scale decision | **Sub‑second** |
  | Metric breach → pods **Ready** | **3.8 s** |

  </template>
</RhTwoColumn>

<div class="mt-5 text-sm text-center text-[var(--rh-muted)] max-w-4xl mx-auto">

**~4 s** breach → scaled replicas **Ready** on **both** clusters  -  HPA is **not** where the **minute‑scale** pain lives. That appears when new replicas sit **Pending** waiting on **CAS / AutoNode** (next slide).

</div>

<!--
Speaker note: Milestones `metric_breach_to_scale_decision` and `metric_breach_to_pods_ready` from paired HTML reports. HCP run shows a long **manifests→workload Ready** ramp (~5 m) before breach  -  ignore for this slide; focus on **post‑breach** parity. Contrast verbally with cascade totals (~10 m Classic vs ~5 m HCP).
-->

---

<!-- SLIDE 26  -  HPA → autoscaler cascade -->

# HPA → Autoscaler Cascade (No Spare Capacity)
When HPA asks for resources that don't exist ... yet.

<RhTwoColumn>
  <template #left>

  ### Classic (CAS)

  | Phase | Duration |
  |---|---|
  | HPA trigger → pods Pending | 59s |
  | Scheduler trigger → node Ready | **+7m 10s** |
  | Node Ready → pods Running | +1m 36s |
  | **HPA trigger → all Ready** | **9m 54s** |

  **Fully cold CAS node  -  long‑path provisioning.**
  </template>
  <template #right>

  ### HCP + AutoNode

  | Phase | Duration |
  |---|---|
  | HPA trigger → pods Pending | 3s |
  | Scheduler trigger → node Ready | **+4m 19s** |
  | Node Ready → pods Running | +24s |
  | **HPA trigger → all Ready** | **5m 0s** |

  </template>
</RhTwoColumn>

<div class="mt-4 text-sm text-center text-[var(--rh-muted)]">

<strong style="color: #dc2626; font-size: 1.5em;">2×</strong> faster end-to-end on HCP  -  bulk of difference is mostly EC2 spinup rather than Autonode vs CAS

</div>

<!--
Speaker note: First three **Phase** rows are **serial segments** after HPA trigger (they **chain** toward the total); **HPA trigger → all Ready** is **end‑to‑end from the same trigger** (≈ sum of segments; small rounding vs HTML).
-->

---

<!-- SLIDE 27  -  Overprovisioning / balloon pods -->

# Balloon Pods  -  Pre-reserved Capacity

<div class="text-xs text-[var(--rh-muted)] mb-3">

Workload + Balloon pods - 20m small surge

</div>

<RhTwoColumn>
  <template #left>

  ### Classic (CAS)

  | Step | Time |
  |---|---|
  | Steady State | 1s |
  | Burst | |
  | Workload Ready (HPA) | +1m 12s  |
  | First new workers Ready ‡ | +5m 54s |
  | Headroom restored † | +20m 13s |

  </template>
  <template #right>

  ### HCP + AutoNode

  | Step | Time |
  |---|---|
  | Steady State | **24s** |
  | Burst | |
  | Workload Ready (HPA) | **+36s** |
  | First new workers Ready ‡ | **+4m 58s** |
  | Headroom restored † | **+20m 25s** |

  </template>
</RhTwoColumn>

<div class="mt-4 text-sm text-[var(--rh-muted)] max-w-4xl mx-auto">

**Burst:** Increase in traffic causes HPA to schedule more pods, Balloon pods are descheduled, and cluster scales up to reschedule them, keeping spare capacity.

</div>

<!--
Speaker note: Increase in traffic causes HPA to schedule more pods, Balloon pods are descheduled, and cluster scales up to reschedule them, keeping spare capacity. The effective difference between Classic and HCP w/ Autonode is minimal at the headline numbers  -  ~1m 12s vs 36s to first pod Ready. The mechanism differs: CAS fires on any unschedulable pending pod, so standard balloon pods work without special spreading rules. Karpenter's balloon pods must use strict podAntiAffinity (one pod per node) so Karpenter provisions N separate headroom nodes instead of bin-packing all balloons onto one, and so the consolidation loop cannot later collapse those nodes together. The headroom restore time (~20 min) is similar for both clusters because both autoscalers impose a scale-down / consolidation delay before re-provisioning; Karpenter's consolidation math is simply running that same delay against the headroom nodes.
-->

---
layout: section
class: section-header
---

<!-- SLIDE 28  -  Advanced Autoscaling Patterns -->

# Advanced Autoscaling Patterns
## Planned surge · Sudden spike

<!--
Speaker note: Planned surge and sudden spike  -  patterns beyond raw scale‑up/down.
-->

---

<!-- SLIDE 29  -  Planned surge -->

# Planned Surge  -  Prepare or Pay

<div class="text-sm text-[var(--rh-muted)] mb-4 max-w-4xl mx-auto">

Same <strong>scripted surge</strong> (Test <strong>11</strong>)  -  the table <strong>isolates</strong> each lever (not phases in one run). Timings: <strong>time to absorb the spike</strong> (lower is better).

</div>

<RhTable
  :headers="['Strategy', 'Prep & economics', 'ROSA Classic', 'HCP + AutoNode']"
  :rows="[
    [
      'Balloon pods',
      'Standing <strong>scheduling slack</strong> (low-priority requests). <strong>Cost:</strong> while balloons run  -  you reserve quota / nodes for headroom.',
      '',
      '',
    ],
    [
      'Proactive scaling',
      '<strong>Slack:</strong> extra workers <strong>before</strong> load lands. <strong>Cost:</strong> idle / underused nodes during the warm-up window (and until scale-in).',
      '',
      '',
    ],
    [
      'Reactive scaling',
      'No prep  -  capacity grows <strong>when</strong> the scheduler needs it. <strong>Cost:</strong> little standing idle; <strong>pay in UX</strong>  -  Pending, slow absorption, errors until the fleet catches up.',
      '~7m',
      '~5m',
    ],
  ]"
/>

<div class="mt-6 text-sm text-[var(--rh-text)] max-w-4xl mx-auto leading-relaxed">

<strong style="color: var(--rh-text)">Insight  - </strong> You don’t run the table as a pick-one menu  -  you <strong>combine</strong> all three in production, each where it’s strongest: <strong>balloons</strong> buy smooth peaks, <strong>proactive</strong> scaling trims always-on headroom when the window is known, and <strong>reactive</strong> autoscaling is the elastic floor so capacity follows real load.

</div>


<!--
Speaker note: Test **11** isolates each lever. **Insight for the audience:** layer **balloons + proactive + reactive**  -  peaks, timed warm-up, elastic tail  -  not either/or.
-->

---

<!-- SLIDE 30  -  Sudden spike -->

# Sudden Spike  -  Balloon Pods as Insurance

<RhTwoColumn>
  <template #left>

  ### Classic (CAS)

  - HPA->CAS: **9m 48s** to pods Ready
  - HPA->**Balloon**->CAS: **31s**
  - **~95%** reduction

  </template>
  <template #right>

  ### HCP + AutoNode

  - HPA->AutoNode: **6m 34s**
  - HPA->**Balloon**->AutoNode: **1m 03s**
  - **~84%** reduction

  </template>
</RhTwoColumn>

<div class="mt-4 text-sm text-center text-[var(--rh-muted)]">

Autoscaler choice doesn’t remove the spike window  -  <strong>pre-reserved capacity</strong> does. Same pattern on CAS and Autonode.

</div>

---
layout: section
class: section-header
---

<!-- SLIDE 31  -  Head-to-Head Results -->

# Head-to-Head Results
## CAS vs AutoNode  -  the numbers

<!--
Speaker note: Let's put it all together. The head-to-head comparison
across every dimension we measured.
-->

---

<!-- SLIDE 32  -  Head-to-head table -->

# AutoNode vs Cluster Autoscaler

<RhTable
  :headers="['Operation', 'CAS  -  Classic', 'AutoNode  -  HCP', 'Speedup']"
  :rows="[
    ['Scheduling decision (FailedScheduling → action)', '34s', '8s', '~26×'],
    ['Node provision (EC2 launch → node Ready)', '6m 38s', '4m 30s', '~1.5×'],
    ['End-to-end (FailedScheduling → pods Running)', '7m 26s', '4m 41s', '~1.6×'],
    ['Scale-down / consolidation', '9m 56s', '1m 54s', '~5×'],
    ['Workload exceeds worker pool SKU', 'NotTriggerScaleUp  -  Pending', 'r5.16xlarge → Running (~4m 45s)', ' - '],
    ['Consolidation logic', 'Utilisation threshold only', 'Pack-first math + safety check', ' - '],
  ]"
/>

<div class="mt-4 text-sm text-[var(--rh-muted)] text-center">


</div>

<!--
Speaker note: Head-to-head mirrors earlier benchmark slides  -  same captures, no extra caveats on-slide.
-->

---
layout: center
class: text-center
---

<!-- SLIDE 33  -  Structural advantages (HCP + AutoNode) -->

# Autonode Structural Advantages

<div class="grid grid-cols-2 gap-x-14 gap-y-12 mt-12 max-w-5xl mx-auto text-left">

<div class="border-t-4 pt-5" style="border-color: var(--rh-red);">
  <div class="text-3xl font-bold tracking-tight" style="font-family: 'Red Hat Display', sans-serif; color: var(--rh-red);">Hosted control plane</div>
  <p class="text-lg text-[var(--rh-muted)] mt-3 leading-snug">Shorter installs · Quicker Worker nodes</p>
</div>

<div class="border-t-4 pt-5" style="border-color: var(--rh-yellow);">
  <div class="text-3xl font-bold tracking-tight" style="font-family: 'Red Hat Display', sans-serif; color: var(--rh-yellow);">Scale toward zero</div>
  <p class="text-lg text-[var(--rh-muted)] mt-3 leading-snug">Fewer empty workers - not a fixed pool size.</p>
</div>

<div class="border-t-4 pt-5" style="border-color: var(--rh-yellow);">
  <div class="text-3xl font-bold tracking-tight" style="font-family: 'Red Hat Display', sans-serif; color: var(--rh-yellow);">Fast reclaim</div>
  <p class="text-lg text-[var(--rh-muted)] mt-3 leading-snug"><strong class="text-[var(--rh-text)]">~5×</strong> scale-in vs CAS cooldown. Each idle node held ~9 min longer on CAS  -  across many scale cycles that idle time adds up to real money.</p>
</div>

<div class="border-t-4 pt-5" style="border-color: var(--rh-red);">
  <div class="text-3xl font-bold tracking-tight" style="font-family: 'Red Hat Display', sans-serif; color: var(--rh-red);">Spot · ARM · right-size SKU</div>
  <p class="text-lg text-[var(--rh-muted)] mt-3 leading-snug">Single NodePool picks on-demand, Spot, or Graviton at scheduling time. CAS requires a standing minimum fleet per pool type.</p>
</div>

</div>

<div class="mt-12 text-sm text-left max-w-4xl mx-auto leading-relaxed border-t border-[var(--rh-border)] pt-6 text-[var(--rh-text)]">

> These wins are **fleet lifecycle, reclaim speed, and long-run cost**  -  not **immediate pod placement** if you are already out of schedulable capacity.

</div>

<!--
Speaker note: Tiles = HCP infra + autoscaler behaviours + economics. The bottom-right tile covers three related levers  -  bin-packing (fewer nodes), right-sizing SKU (pick instance to fit workload), and Spot + ARM (pick cheapest purchasing option). All three flow from the same root capability: AutoNode chooses the optimal instance at scheduling time rather than being locked to a pre-declared pool. Spot + ARM via a single NodePool can reduce burst EC2 costs by ~73% vs on-demand x86; CAS needs a separate MachineSet per combination with a standing 3-node minimum per AZ. Footer bridges to Findings & Recommendations: slack first when latency is measured at the pod  -  not at the provisioning API.
-->

---
layout: section
class: section-header
---

<!-- SLIDE 34  -  Findings & Recommendations -->

# Findings & Recommendations

<!--
Speaker note: Let me close with what these numbers mean in practice.
-->

---
layout: center
class: text-center
---

<!-- SLIDE 35  -  Key finding -->

# Key finding

<div class="text-5xl md:text-6xl font-bold mt-12 leading-tight" style="color: var(--rh-red); font-family: 'Red Hat Display', sans-serif;">
Choreography beats pedigree.
</div>

<div class="text-xl md:text-2xl text-[var(--rh-muted)] mt-10 max-w-3xl mx-auto leading-snug">

How you line up **baseline nodes**, **reserved slack** (balloons / overprovisioning), and **HPA** matters more for burst UX than whether the cluster scaler is **CAS** or **AutoNode**.

</div>

<!--
Speaker note: This is the single closing thesis for the talk track. The rest of the deck is evidence; if they remember one line, it’s this. AutoNode vs CAS is a **refinement** once choreography is honest.
-->

---

<!-- SLIDE 36  -  Fix choreography first -->

# Fix Choreography First

- **Design workers, slack, and HPA together**  -  treat **baseline node count**, **balloon / overprovisioning slack**, and **HPA cadence & targets** as one system. Until those line up, you are still renting **minute-scale provisioning** surprises  -  CAS vs AutoNode only changes **how** nodes arrive once you are already behind.

- **Run balloons on whichever cluster type you operate**  -  our sudden-spike drills improved **≈ 95 % / ≈ 84 %** to pods Ready versus reactive-only; pedigree did not outperform cheap **paused slack**.
  - Use the **Cluster Proportional Autoscaler** (OperatorHub) to keep replica count proportional to cluster size  -  one balloon per N nodes, no manual tuning as the fleet grows.

- **Pre-position capacity for predictable peaks**  -  timed balloons, warmed workers, and planned-surge rehearsals matter more than debating autoscaler choice when the calendar is telling you traffic is incoming.

<!--
Speaker note: Choreography first  -  always. AutoNode vs CAS is a refinement once the slack math is honest. These three points apply equally on Classic and HCP; getting them right on Classic is more valuable than migrating to HCP with a poorly tuned system.
-->

---

<!-- SLIDE 37  -  Improve performance and reduce costs with AutoNode -->

# Then: Improve Performance and Reduce Costs

Once choreography is solid, HCP + AutoNode compounds the gains:

- **~3.5× faster cluster provisioning**  -  control plane hosted; workers ready in ~13 min vs ~53 min on Classic.
- **~5× faster scale-down**  -  `consolidateAfter: 30s` vs ~10 min CAS cooldown; idle nodes cost real money at scale.
- **Spot + ARM via a single NodePool**  -  up to **~73% worker EC2 savings** vs on-demand x86; CAS needs a standing 3-node minimum per pool type (platform constraint on Classic).
- **Scale to zero**  -  no standing floor per pool type; AutoNode provisions the first node of any family only when a pod needs it.
- **~$9,500 / yr infrastructure saving**  -  no control plane or infra EC2 in your account; the $0.25 / hr cluster fee is well below the cost of 6 replaced nodes.
- **SKU flexibility**  -  AutoNode selects the right instance for the workload burst; CAS is locked to the pool's declared type.

<!--
Speaker note: These are compounding wins  -  you get all of them together once you move to HCP + AutoNode. The cost story is particularly strong at scale: infrastructure saving + fast reclaim + Spot/ARM burst adds up to $11,500–$14,000/yr vs a Classic on-demand baseline for a 15-worker cluster with burst. Larger clusters widen that gap.
-->

---

<!-- SLIDE 38  -  Thanks -->

# Thank You

<div class="text-2xl mt-6 text-[var(--rh-muted)]">
Questions?
</div>

<div class="mt-10 text-sm" style="color: var(--rh-muted)">

Open metrics toolkit · HTML reports · visual canvases · retrospectives<br />

[github.com/rh-mobb/rosa-autoscaling-performance-and-recommendations](https://github.com/rh-mobb/rosa-autoscaling-performance-and-recommendations) ·
[pczarkow@redhat.com](mailto:pczarkow@redhat.com)

</div>

<!--
Speaker note: Scripts, reports, README  -  everything needed to rerun on your ROSA tenancy lives in GitHub above.
-->
