<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { useIsSlideActive } from '@slidev/client'

type StepType  = 'waiting' | 'action'
type StepState = 'inactive' | 'active' | 'done'

interface Step { label: string; sub: string; type: StepType }

const AN_STEPS: Step[] = [
  { label: 'Pending',    sub: 'pod unschedulable',  type: 'waiting' },
  { label: 'NodeClaim',  sub: 'AutoNode reacts ~1s', type: 'action'  },
  { label: 'Launching',  sub: 'EC2 Fleet API',       type: 'action'  },
  { label: 'Booting',    sub: 'instance running',    type: 'action'  },
  { label: 'Ready',      sub: 'HCP bootstrap ~4m',   type: 'action'  },
  { label: 'Running',    sub: 'pod scheduled',       type: 'action'  },
]

const CAS_STEPS: Step[] = [
  { label: 'Pending',          sub: 'pod unschedulable',  type: 'waiting' },
  { label: 'FailedScheduling', sub: 'scheduler gives up', type: 'waiting' },
  { label: 'Polling',          sub: 'CAS loop 10–30s',    type: 'waiting' },
  { label: 'MachineSet',       sub: 'replica +1',         type: 'action'  },
  { label: 'Booting',          sub: 'EC2 RunInstances',   type: 'action'  },
  { label: 'Ready',            sub: 'three-boot ~6m',     type: 'action'  },
  { label: 'Running',          sub: 'pod scheduled',      type: 'action'  },
]

const STEP_MS  = 1400   // dwell per step
const RESET_MS = 2800   // pause at end before looping

const anActive  = ref(-1)
const casActive = ref(-1)
const paused    = ref(false)

let stepTimer:  ReturnType<typeof setInterval> | null = null
let resetTimer: ReturnType<typeof setTimeout>  | null = null

function stepState(i: number, active: number): StepState {
  if (active < 0)  return 'inactive'
  if (i < active)  return 'done'
  if (i === active) return 'active'
  return 'inactive'
}

function stopAll() {
  if (stepTimer)  { clearInterval(stepTimer);  stepTimer  = null }
  if (resetTimer) { clearTimeout(resetTimer);  resetTimer = null }
}

function startAnim() {
  stopAll()
  anActive.value  = 0
  casActive.value = 0
  stepTimer = setInterval(() => {
    if (anActive.value  < AN_STEPS.length)  anActive.value++
    if (casActive.value < CAS_STEPS.length) casActive.value++
    if (anActive.value >= AN_STEPS.length && casActive.value >= CAS_STEPS.length) {
      clearInterval(stepTimer!); stepTimer = null
      resetTimer = setTimeout(() => {
        anActive.value  = -1
        casActive.value = -1
        if (!paused.value) startAnim()
      }, RESET_MS)
    }
  }, STEP_MS)
}

function toggle() {
  paused.value = !paused.value
  if (paused.value) stopAll()
  else startAnim()
}

const isActive = useIsSlideActive()

watch(isActive, (active) => {
  if (active) {
    paused.value = false
    startAnim()
  } else {
    stopAll()
    anActive.value  = -1
    casActive.value = -1
    paused.value    = false
  }
}, { immediate: true })

onUnmounted(() => stopAll())
</script>

<template>
  <div class="sp-root" @click="toggle">

    <!-- AutoNode pipeline -->
    <div class="sp-row">
      <div class="sp-row-label an">AUTONODE (HCP)</div>
      <div class="sp-steps">
        <template v-for="(step, i) in AN_STEPS" :key="i">
          <div class="sp-step" :class="[step.type, stepState(i, anActive)]">
            <span class="sp-label">{{ step.label }}</span>
            <span class="sp-sub">{{ step.sub }}</span>
          </div>
          <div v-if="i < AN_STEPS.length - 1" class="sp-arrow" :class="{ lit: anActive > i }">›</div>
        </template>
      </div>
    </div>

    <!-- CAS pipeline -->
    <div class="sp-row">
      <div class="sp-row-label cas">CAS (CLASSIC)</div>
      <div class="sp-steps">
        <template v-for="(step, i) in CAS_STEPS" :key="i">
          <div class="sp-step" :class="[step.type, stepState(i, casActive)]">
            <span class="sp-label">{{ step.label }}</span>
            <span class="sp-sub">{{ step.sub }}</span>
          </div>
          <div v-if="i < CAS_STEPS.length - 1" class="sp-arrow" :class="{ lit: casActive > i }">›</div>
        </template>
      </div>
    </div>

    <!-- Pause hint -->
    <div class="sp-hint">{{ paused ? '▶ click to resume' : '⏸ click to pause' }}</div>

  </div>
</template>

<style scoped>
/* ── Root ──────────────────────────────────────────────── */
.sp-root {
  font-family: 'JetBrains Mono', monospace;
  cursor: pointer;
  padding: 4px 0 2px;
  user-select: none;
}

/* ── Pipeline row ──────────────────────────────────────── */
.sp-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.sp-row-label {
  font-size: 0.58em;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  width: 88px;
  flex-shrink: 0;
  text-align: right;
  padding-right: 6px;
  border-right: 2px solid #333;
}
.sp-row-label.an  { color: #60a5fa; border-color: #60a5fa33; }
.sp-row-label.cas { color: #a78bfa; border-color: #a78bfa33; }

.sp-steps {
  display: flex;
  align-items: center;
  gap: 0;
  flex: 1;
}

/* ── Step box ──────────────────────────────────────────── */
.sp-step {
  flex: 1;
  min-width: 0;
  border-radius: 5px;
  padding: 5px 4px 4px;
  text-align: center;
  border: 1px solid #2a2a2a;
  background: #111;
  transition: background 0.5s ease, border-color 0.5s ease, opacity 0.5s ease;
}

.sp-label {
  display: block;
  font-size: 0.55em;
  font-weight: 700;
  letter-spacing: 0.03em;
  color: #444;
  transition: color 0.5s ease;
  line-height: 1.3;
  word-break: break-word;
}

.sp-sub {
  display: block;
  font-size: 0.44em;
  color: #333;
  margin-top: 1px;
  transition: color 0.5s ease;
  line-height: 1.2;
}

/* ── Waiting: inactive → active → done ────────────────── */
.waiting.inactive { border-color: #222; background: #111; }
.waiting.active   {
  border-color: #f59e0b;
  background: rgba(245,158,11,.1);
  animation: pulse-step 1.2s ease-in-out infinite;
}
.waiting.active .sp-label { color: #f59e0b; }
.waiting.active .sp-sub   { color: #f59e0b99; }
.waiting.done   { border-color: #78350f; background: rgba(245,158,11,.06); }
.waiting.done .sp-label   { color: #d97706; }
.waiting.done .sp-sub     { color: #78350f; }

/* ── Action: inactive → active → done ─────────────────── */
.action.inactive { border-color: #222; background: #111; }
.action.active   {
  border-color: #22c55e;
  background: rgba(34,197,94,.1);
  animation: pulse-step 1.2s ease-in-out infinite;
}
.action.active .sp-label { color: #22c55e; }
.action.active .sp-sub   { color: #22c55e99; }
.action.done   { border-color: #14532d; background: rgba(34,197,94,.07); }
.action.done .sp-label   { color: #16a34a; }
.action.done .sp-sub     { color: #14532d; }

@keyframes pulse-step { 0%,100% { opacity: 1; } 50% { opacity: 0.65; } }

/* ── Arrow ─────────────────────────────────────────────── */
.sp-arrow {
  flex-shrink: 0;
  font-size: 1.1em;
  padding: 0 2px;
  color: #2a2a2a;
  transition: color 0.5s ease;
}
.sp-arrow.lit { color: #555; }

/* ── Pause hint ────────────────────────────────────────── */
.sp-hint {
  text-align: center;
  font-size: 0.5em;
  color: #444;
  margin-top: 2px;
  letter-spacing: 0.04em;
}
</style>
