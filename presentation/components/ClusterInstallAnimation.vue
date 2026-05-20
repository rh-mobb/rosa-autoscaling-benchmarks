<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useIsSlideActive } from '@slidev/client'

type NodeState = 'idle' | 'provisioning' | 'ready'

interface Frame {
  c_cp:      NodeState  // Classic: control-plane nodes
  c_infra:   NodeState  // Classic: infra nodes
  c_workers: NodeState  // Classic: worker nodes
  c_label:   string
  h_workers:  NodeState // HCP: worker nodes
  h_autonode: boolean   // HCP: AutoNode CRDs visible
  h_label:    string
  dwell: number
}

// HCP control plane is always shown as "ready" — it is pre-provisioned by Red Hat.
// Classic must go through 3 sequential provisioning stages, making it unmissably slower.
const SCRIPT: Frame[] = [
  { c_cp:'idle',         c_infra:'idle',         c_workers:'idle',         c_label:'',
    h_workers:'idle',    h_autonode:false, h_label:'',                    dwell: 800  },

  { c_cp:'provisioning', c_infra:'idle',         c_workers:'idle',         c_label:'T+0 — provisioning...',
    h_workers:'provisioning', h_autonode:false, h_label:'T+0 — workers starting...',   dwell: 2500 },

  { c_cp:'provisioning', c_infra:'idle',         c_workers:'idle',         c_label:'~T+10m',
    h_workers:'provisioning', h_autonode:false, h_label:'~T+10m',           dwell: 2000 },

  // HCP workers ready at T+13m. Classic has only just finished its control plane.
  { c_cp:'ready',        c_infra:'provisioning', c_workers:'idle',         c_label:'~T+20m',
    h_workers:'ready',   h_autonode:false, h_label:'~T+13m — cluster ready!', dwell: 2000 },

  // HCP adds AutoNode (+2m). Classic is still working through infra.
  { c_cp:'ready',        c_infra:'provisioning', c_workers:'idle',         c_label:'~T+30m',
    h_workers:'ready',   h_autonode:true,  h_label:'~T+15m — AutoNode ready!', dwell: 2000 },

  // HCP complete. Classic finally finishes infra, starts workers.
  { c_cp:'ready',        c_infra:'ready',        c_workers:'provisioning', c_label:'~T+40m',
    h_workers:'ready',   h_autonode:true,  h_label:'T+15m - done',         dwell: 2500 },

  { c_cp:'ready',        c_infra:'ready',        c_workers:'ready',        c_label:'~T+52m',
    h_workers:'ready',   h_autonode:true,  h_label:'T+15m - done',         dwell: 2000 },

  { c_cp:'ready',        c_infra:'ready',        c_workers:'ready',        c_label:'T+53m - done',
    h_workers:'ready',   h_autonode:true,  h_label:'T+15m - done',         dwell: 2500 },
]

// HCP finishes at frame 3; Classic finishes at frame 7.
// Visible gap: frames 4-7 = 2000+2500+2000+2500 = 9000 ms where HCP is done and Classic is not.

const RESET_MS = 3000

const frameIdx = ref(-1)
const paused   = ref(false)

const f = computed<Frame>(() =>
  frameIdx.value < 0
    ? SCRIPT[0]
    : SCRIPT[Math.min(frameIdx.value, SCRIPT.length - 1)]
)

let stepTimer:  ReturnType<typeof setTimeout> | null = null
let resetTimer: ReturnType<typeof setTimeout> | null = null

function stopAll() {
  if (stepTimer)  { clearTimeout(stepTimer);  stepTimer  = null }
  if (resetTimer) { clearTimeout(resetTimer); resetTimer = null }
}

function scheduleFrame(index: number) {
  if (index >= SCRIPT.length) {
    resetTimer = setTimeout(() => {
      frameIdx.value = -1
      if (!paused.value) startAnim()
    }, RESET_MS)
    return
  }
  frameIdx.value = index
  stepTimer = setTimeout(() => {
    stepTimer = null
    scheduleFrame(index + 1)
  }, SCRIPT[index].dwell)
}

function startAnim() {
  stopAll()
  scheduleFrame(0)
}

function toggle() {
  paused.value = !paused.value
  if (paused.value) stopAll()
  else startAnim()
}

const isActive = useIsSlideActive()
watch(isActive, (active) => {
  if (active) {
    paused.value   = false
    frameIdx.value = -1
    startAnim()
  } else {
    stopAll()
    frameIdx.value = -1
    paused.value   = false
  }
}, { immediate: true })

onUnmounted(() => stopAll())
</script>

<template>
  <div class="ci-root" @click="toggle">
    <div class="ci-panels">

      <!-- ── CLASSIC ───────────────────────────────────────── -->
      <div class="ci-panel-box classic-box">
        <div class="ci-panel">
          <div class="ci-panel-header">
            <span class="ci-panel-name classic">ROSA CLASSIC</span>
            <span class="ci-timer" :class="{ done: f.c_label.includes('done') }">
              {{ f.c_label || '···' }}
            </span>
          </div>

          <div class="ci-group cp-group">
            <div class="ci-group-label">CONTROL PLANE</div>
            <div class="ci-nodes">
              <div v-for="n in 3" :key="n" class="ci-node" :class="f.c_cp">
                <span class="ci-node-lbl">master-{{ n }}</span>
                <div class="ci-pods">
                  <span class="pod cp" /><span class="pod cp" /><span class="pod sys" />
                </div>
              </div>
            </div>
          </div>

          <div class="ci-group infra-group">
            <div class="ci-group-label">INFRA</div>
            <div class="ci-nodes">
              <div v-for="n in 3" :key="n" class="ci-node" :class="f.c_infra">
                <span class="ci-node-lbl">infra-{{ n }}</span>
                <div class="ci-pods">
                  <span class="pod infra" /><span class="pod infra" /><span class="pod sys" />
                </div>
              </div>
            </div>
          </div>

          <div class="ci-group worker-group">
            <div class="ci-group-label">WORKERS</div>
            <div class="ci-nodes">
              <div v-for="n in 3" :key="n" class="ci-node" :class="f.c_workers">
                <span class="ci-node-lbl">worker-{{ n }}</span>
                <div class="ci-pods">
                  <span class="pod app" /><span class="pod app" /><span class="pod ops" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── HCP ───────────────────────────────────────────── -->
      <div class="ci-panel-box hcp-box">
        <div class="ci-panel">
          <div class="ci-panel-header">
            <span class="ci-panel-name hcp">ROSA HCP + AUTONODE</span>
            <span class="ci-timer" :class="{ done: f.h_label.includes('done') }">
              {{ f.h_label || '···' }}
            </span>
          </div>

          <div class="ci-group cp-group">
            <div class="ci-group-label">HOSTED CONTROL PLANE <span class="rh-badge">Red Hat ☁</span></div>
            <div class="ci-cloud">
              <span class="ci-cloud-chip"><span class="pod cp sm" /> api-server</span>
              <span class="ci-cloud-chip"><span class="pod cp sm" /> etcd</span>
              <span class="ci-cloud-chip"><span class="pod cp sm" /> scheduler</span>
              <span class="ci-cloud-chip"><span class="pod sys sm" /> controllers</span>
            </div>
          </div>

          <div class="ci-group worker-group">
            <div class="ci-group-label">WORKERS</div>
            <div class="ci-nodes">
              <div v-for="n in 3" :key="n" class="ci-node" :class="f.h_workers">
                <span class="ci-node-lbl">worker-{{ n }}</span>
                <div class="ci-pods">
                  <span class="pod app" /><span class="pod ops" /><span class="pod ops" />
                </div>
              </div>
            </div>
          </div>

          <div class="ci-group autonode-group">
            <div class="ci-group-label">AUTONODE (KARPENTER)</div>
            <div class="ci-nodes">
              <div class="ci-node wide" :class="f.h_autonode ? 'ready' : 'idle'">
                <span class="ci-node-lbl">NodePool / EC2NodeClass</span>
                <div class="ci-pods">
                  <span class="pod karp" /><span class="pod karp" /><span class="pod karp" /><span class="pod karp" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

    </div>

    <div class="ci-hint">{{ paused ? '▶ click to resume' : '⏸ click to pause' }}</div>
  </div>
</template>

<style scoped>
/* ── Root ──────────────────────────────────────────────── */
.ci-root {
  font-family: 'JetBrains Mono', monospace;
  cursor: pointer;
  user-select: none;
  padding: 2px 0;
}

/* ── Two-column panel layout ───────────────────────────── */
.ci-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

/* ── Cluster boundary boxes ────────────────────────────── */
.ci-panel-box {
  border-radius: 8px;
  padding: 10px 12px 8px;
  border: 1px solid;
}
.classic-box { border-color: #3a2f5a; background: rgba(167,139,250,.03); }
.hcp-box     { border-color: #1a3a5a; background: rgba(96,165,250,.03); }

/* ── Panel ─────────────────────────────────────────────── */
.ci-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ci-panel-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 2px;
}

.ci-panel-name {
  font-size: 0.55em;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.ci-panel-name.classic { color: #a78bfa; }
.ci-panel-name.hcp     { color: #60a5fa; }

.ci-timer {
  font-size: 0.5em;
  color: #555;
  transition: color 0.5s ease;
}
.ci-timer.done { color: #22c55e; }

/* ── Group ─────────────────────────────────────────────── */
.ci-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ci-group-label {
  font-size: 0.44em;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #333;
  text-transform: uppercase;
  padding-left: 2px;
}

.rh-badge {
  color: #f59e0b;
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
}

/* ── Node row ──────────────────────────────────────────── */
.ci-nodes {
  display: flex;
  gap: 5px;
}

/* ── Node box ──────────────────────────────────────────── */
.ci-node {
  flex: 1;
  border-radius: 5px;
  border: 1px solid #1e1e1e;
  background: #0d0d0d;
  padding: 5px 5px 4px;
  transition: background 0.6s ease, border-color 0.6s ease;
}
.ci-node.wide { flex: none; width: 100%; }

.ci-node-lbl {
  display: block;
  font-size: 0.42em;
  color: #2a2a2a;
  margin-bottom: 4px;
  transition: color 0.5s ease;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* provisioning state */
.ci-node.provisioning {
  border: 1px dashed #444;
  background: #111;
  animation: node-pulse 1.4s ease-in-out infinite;
}
.ci-node.provisioning .ci-node-lbl { color: #444; }

/* ready — colour comes from the group */
.cp-group .ci-node.ready     { border-color: #60a5fa; background: rgba(96,165,250,.07); }
.cp-group .ci-node.ready .ci-node-lbl { color: #60a5fa; }

.infra-group .ci-node.ready  { border-color: #a78bfa; background: rgba(167,139,250,.07); }
.infra-group .ci-node.ready .ci-node-lbl { color: #a78bfa; }

.worker-group .ci-node.ready { border-color: #22c55e; background: rgba(34,197,94,.07); }
.worker-group .ci-node.ready .ci-node-lbl { color: #22c55e; }

.autonode-group .ci-node.ready { border-color: #34d399; background: rgba(52,211,153,.07); }
.autonode-group .ci-node.ready .ci-node-lbl { color: #34d399; }

@keyframes node-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }

/* ── Pod dots ──────────────────────────────────────────── */
.ci-pods {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
}

.pod {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 2px;
  background: #1e1e1e;
  transition: background 0.6s ease;
}
.pod.sm { width: 5px; height: 5px; }

/* Pod colours — visible only when parent node is provisioning/ready */
.ci-node.provisioning .pod,
.ci-node.ready .pod { opacity: 1; }

.ci-node:not(.provisioning):not(.ready) .pod { background: #1e1e1e !important; }

.pod.cp    { background: #60a5fa; }
.pod.infra { background: #a78bfa; }
.pod.app   { background: #22c55e; }
.pod.ops   { background: #f59e0b; }
.pod.sys   { background: #94a3b8; }
.pod.karp  { background: #34d399; }

/* provisioning pods: dim */
.ci-node.provisioning .pod.cp    { background: #1d3a5a; }
.ci-node.provisioning .pod.infra { background: #2d1f4a; }
.ci-node.provisioning .pod.app   { background: #14321e; }
.ci-node.provisioning .pod.ops   { background: #3a2a10; }
.ci-node.provisioning .pod.sys   { background: #2a2f38; }
.ci-node.provisioning .pod.karp  { background: #0f3028; }

/* ── Hosted CP cloud strip ─────────────────────────────── */
.ci-cloud {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid #1e4a7a;
  background: rgba(96,165,250,.06);
}

.ci-cloud-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.42em;
  color: #60a5fa;
  background: rgba(96,165,250,.1);
  border: 1px solid #1e3a5a;
  border-radius: 3px;
  padding: 2px 5px;
}

/* ── Hint ──────────────────────────────────────────────── */
.ci-hint {
  text-align: center;
  font-size: 0.5em;
  color: #444;
  margin-top: 4px;
  letter-spacing: 0.04em;
}
</style>
