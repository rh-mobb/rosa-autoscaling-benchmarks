<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useIsSlideActive } from '@slidev/client'

type PodType = 'app' | 'balloon' | 'empty' | 'evicting' | 'provisioning'

interface Pod { type: PodType; label: string }
interface NodeDef { id: string; status: 'ready' | 'provisioning'; visible: boolean; pods: [Pod, Pod, Pod, Pod] }
interface Phase { label: string; sublabel: string; nodes: NodeDef[] }

const a = (): Pod => ({ type: 'app', label: 'APP' })
const b = (): Pod => ({ type: 'balloon', label: 'BALLOON' })
const e = (): Pod => ({ type: 'empty', label: '' })
const ev = (): Pod => ({ type: 'evicting', label: 'EVICTED' })
const pr = (): Pod => ({ type: 'provisioning', label: '···' })

const PHASES: Phase[] = [
  {
    label: 'At Rest',
    sublabel: 'Balloons hold warm capacity  -  zero CPU consumed, full slot reserved',
    nodes: [
      { id: 'node-1', status: 'ready', visible: true,  pods: [a(), a(), a(), b()] },
      { id: 'node-2', status: 'ready', visible: true,  pods: [a(), a(), a(), b()] },
      { id: 'node-3', status: 'ready', visible: true,  pods: [a(), a(), a(), b()] },
      { id: 'node-4', status: 'ready', visible: true,  pods: [a(), a(), b(), e()] },
      { id: 'node-5', status: 'ready', visible: false, pods: [e(), e(), e(), e()] },
    ],
  },
  {
    label: 'Spike  -  HPA fires',
    sublabel: 'Scheduler evicts low-priority balloons to place new app pods instantly',
    nodes: [
      { id: 'node-1', status: 'ready', visible: true,  pods: [a(), a(), a(), ev()] },
      { id: 'node-2', status: 'ready', visible: true,  pods: [a(), a(), a(), ev()] },
      { id: 'node-3', status: 'ready', visible: true,  pods: [a(), a(), a(), ev()] },
      { id: 'node-4', status: 'ready', visible: true,  pods: [a(), a(), ev(), a()] },
      { id: 'node-5', status: 'ready', visible: false, pods: [e(), e(), e(), e()] },
    ],
  },
  {
    label: 'Provisioning Headroom  -  5–7 minutes',
    sublabel: 'App pods already running · autoscaler restores balloon capacity in background',
    nodes: [
      { id: 'node-1', status: 'ready',        visible: true, pods: [a(), a(), a(), a()] },
      { id: 'node-2', status: 'ready',        visible: true, pods: [a(), a(), a(), a()] },
      { id: 'node-3', status: 'ready',        visible: true, pods: [a(), a(), a(), a()] },
      { id: 'node-4', status: 'ready',        visible: true, pods: [a(), a(), a(), a()] },
      { id: 'node-5', status: 'provisioning', visible: true, pods: [pr(), pr(), pr(), pr()] },
    ],
  },
  {
    label: 'Headroom Restored',
    sublabel: 'New node ready · balloons rescheduled · cluster back to steady state',
    nodes: [
      { id: 'node-1', status: 'ready', visible: true, pods: [a(), a(), a(), a()] },
      { id: 'node-2', status: 'ready', visible: true, pods: [a(), a(), a(), a()] },
      { id: 'node-3', status: 'ready', visible: true, pods: [a(), a(), a(), a()] },
      { id: 'node-4', status: 'ready', visible: true, pods: [a(), a(), a(), a()] },
      { id: 'node-5', status: 'ready', visible: true, pods: [b(), b(), b(), b()] },
    ],
  },
]

const PHASE_MS = 4000
const TICK_MS  = 60

const phaseIndex = ref(0)
const progress   = ref(0)
const paused     = ref(false)
const currentPhase = computed(() => PHASES[phaseIndex.value])

let phaseTimer: ReturnType<typeof setInterval> | null = null
let progressTimer: ReturnType<typeof setInterval> | null = null

function stopTimers() {
  if (phaseTimer)    { clearInterval(phaseTimer);    phaseTimer    = null }
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
}

function startTimers() {
  stopTimers()
  phaseTimer = setInterval(() => {
    phaseIndex.value = (phaseIndex.value + 1) % PHASES.length
    progress.value = 0
  }, PHASE_MS)
  progressTimer = setInterval(() => {
    progress.value = Math.min(100, progress.value + (TICK_MS / PHASE_MS) * 100)
  }, TICK_MS)
}

function togglePause() {
  if (paused.value) {
    paused.value   = false
    progress.value = 0
    startTimers()
  } else {
    paused.value = true
    stopTimers()
  }
}

function selectPhase(i: number, event: MouseEvent) {
  event.stopPropagation()
  phaseIndex.value = i
  paused.value     = true
  progress.value   = 100
  stopTimers()
}

const isActive = useIsSlideActive()

watch(isActive, (active) => {
  if (active) {
    paused.value      = false
    phaseIndex.value  = 0
    progress.value    = 0
    startTimers()
  } else {
    stopTimers()
    phaseIndex.value  = 0
    progress.value    = 0
    paused.value      = false
  }
}, { immediate: true })

onUnmounted(() => stopTimers())
</script>

<template>
  <div class="bp-root" @click="togglePause" style="cursor: pointer">
    <!-- Phase header -->
    <div class="bp-header">
      <div class="bp-dots">
        <span
          v-for="(_, i) in PHASES"
          :key="i"
          class="bp-dot"
          :class="{ active: i === phaseIndex, paused: paused && i === phaseIndex }"
          @click="selectPhase(i, $event)"
        />
      </div>
      <div class="bp-label-main">{{ currentPhase.label }}</div>
      <div class="bp-label-sub">
        {{ currentPhase.sublabel }}
        <span class="bp-resume-hint">{{ paused ? '▶ click to resume' : '⏸ click to pause' }}</span>
      </div>
    </div>

    <!-- Progress bar -->
    <div class="bp-track"><div class="bp-bar" :class="{ paused: paused }" :style="{ width: progress + '%' }" /></div>

    <!-- Nodes -->
    <div class="bp-nodes">
      <div
        v-for="node in currentPhase.nodes"
        :key="node.id"
        class="bp-node"
        :class="{
          'node-hidden':       !node.visible,
          'node-provisioning':  node.status === 'provisioning',
        }"
      >
        <div class="bp-node-hdr">
          <span class="bp-node-id">{{ node.id }}</span>
          <span class="bp-badge" :class="node.status">{{ node.status }}</span>
        </div>
        <div class="bp-pods">
          <div v-for="(pod, pi) in node.pods" :key="pi" class="bp-pod" :class="pod.type">
            {{ pod.label }}
          </div>
        </div>
      </div>
    </div>

    <!-- Legend -->
    <div class="bp-legend">
      <span class="leg app">APP</span>
      <span class="leg balloon">BALLOON</span>
      <span class="leg evicting">EVICTED</span>
      <span class="leg provisioning">PROVISIONING</span>
      <span class="leg empty">EMPTY</span>
    </div>
  </div>
</template>

<style scoped>
/* ── Root ─────────────────────────────────────────────── */
.bp-root {
  font-family: 'JetBrains Mono', monospace;
  padding: 6px 0 4px;
}

/* ── Header ───────────────────────────────────────────── */
.bp-header { text-align: center; margin-bottom: 8px; }

.bp-dots { display: flex; gap: 5px; justify-content: center; margin-bottom: 5px; }
.bp-dot  { width: 6px; height: 6px; border-radius: 50%; background: #3a3a3a; transition: background 0.4s; cursor: pointer; }
.bp-dot:hover { background: #666; }
.bp-dot.active { background: #f59e0b; }
.bp-dot.paused { box-shadow: 0 0 0 2px #f59e0b; }

.bp-label-main { font-size: 0.82em; font-weight: 700; color: #e2e2e2; letter-spacing: 0.07em; text-transform: uppercase; }
.bp-label-sub  { font-size: 0.62em; color: #777; margin-top: 2px; }
.bp-resume-hint { color: #555; font-size: 0.7em; margin-left: 0.5em; }

/* ── Progress bar ─────────────────────────────────────── */
.bp-track { height: 2px; background: #242424; border-radius: 1px; margin: 6px 0 14px; overflow: hidden; }
.bp-bar   { height: 100%; background: #f59e0b; border-radius: 1px; transition: width 0.06s linear; }
.bp-bar.paused { background: #555; }

/* ── Nodes row ────────────────────────────────────────── */
.bp-nodes {
  display: flex;
  gap: 8px;
  justify-content: center;
}

.bp-node {
  background: #1c1f24;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 8px;
  width: 118px;
  flex-shrink: 0;
  transition: opacity 0.45s ease, transform 0.45s ease, border-color 0.4s;
}

.bp-node.node-hidden {
  opacity: 0;
  transform: scale(0.88) translateX(12px);
  pointer-events: none;
}

.bp-node.node-provisioning {
  border-color: #6366f1;
  border-style: dashed;
  animation: pulse-node 1.3s ease-in-out infinite;
}
@keyframes pulse-node { 0%,100% { opacity: 0.55; } 50% { opacity: 1; } }

/* ── Node header ──────────────────────────────────────── */
.bp-node-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 7px;
}
.bp-node-id { font-size: 0.6em; color: #bbb; }

.bp-badge          { font-size: 0.5em; padding: 1px 5px; border-radius: 3px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }
.bp-badge.ready        { background: rgba(34,197,94,.1);  color: #22c55e; }
.bp-badge.provisioning { background: rgba(99,102,241,.1); color: #818cf8; animation: pulse-text 1.3s ease-in-out infinite; }
@keyframes pulse-text { 0%,100% { opacity: 0.45; } 50% { opacity: 1; } }

/* ── Pod grid ─────────────────────────────────────────── */
.bp-pods { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }

.bp-pod {
  border-radius: 4px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.5em;
  font-weight: 700;
  letter-spacing: 0.04em;
  transition: background 0.4s ease, border-color 0.4s ease, color 0.4s ease;
}

.bp-pod.app         { background: rgba(34,197,94,.1);   border: 1px solid #22c55e; color: #22c55e; }
.bp-pod.balloon     { background: rgba(245,158,11,.1);  border: 1px solid #f59e0b; color: #f59e0b; }
.bp-pod.empty       { background: transparent;          border: 1px dashed #383838; color: transparent; }
.bp-pod.evicting    { background: rgba(239,68,68,.12);  border: 1px solid #ef4444; color: #ef4444; animation: blink 0.7s ease-in-out infinite; }
.bp-pod.provisioning{ background: rgba(99,102,241,.1);  border: 1px dashed #6366f1; color: #818cf8; animation: pulse-text 1.3s ease-in-out infinite; }

@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.2; } }

/* ── Legend ───────────────────────────────────────────── */
.bp-legend { display: flex; gap: 12px; justify-content: center; margin-top: 12px; flex-wrap: wrap; }
.leg { font-size: 0.52em; font-weight: 700; letter-spacing: 0.06em; padding: 2px 7px; border-radius: 3px; }
.leg.app         { background: rgba(34,197,94,.1);   border: 1px solid #22c55e; color: #22c55e; }
.leg.balloon     { background: rgba(245,158,11,.1);  border: 1px solid #f59e0b; color: #f59e0b; }
.leg.evicting    { background: rgba(239,68,68,.12);  border: 1px solid #ef4444; color: #ef4444; }
.leg.provisioning{ background: rgba(99,102,241,.1);  border: 1px dashed #6366f1; color: #818cf8; }
.leg.empty       { background: transparent;          border: 1px dashed #383838; color: #555; }
</style>
