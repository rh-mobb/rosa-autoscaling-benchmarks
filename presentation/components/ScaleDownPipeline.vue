<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useIsSlideActive } from '@slidev/client'

type StepType  = 'waiting' | 'action' | 'retry'
type StepState = 'inactive' | 'active' | 'done'

interface Step { label: string; sub: string; type: StepType }

// AutoNode steps  -  includes a "No Action" retry step at index 2
const AN_STEPS: Step[] = [
  { label: 'Watching',   sub: 'workload scaled down',    type: 'waiting' },
  { label: 'Evaluating', sub: 'can pods repack?',        type: 'action'  },
  { label: 'No Action',  sub: '↩ not yet  -  retry',      type: 'retry'   },
  { label: 'Packing',    sub: 'cordon + evict pods',     type: 'action'  },
  { label: 'Draining',   sub: 'pods rescheduled',        type: 'action'  },
  { label: 'Terminated', sub: 'EC2 gone (~30s total)',   type: 'action'  },
]

// CAS steps  -  long cooldown chain, no branching
const CAS_STEPS: Step[] = [
  { label: 'Monitoring', sub: 'workload removed',        type: 'waiting' },
  { label: 'Threshold',  sub: 'below util threshold',    type: 'waiting' },
  { label: 'Cooldown',   sub: 'delay-after-add ~10 min', type: 'waiting' },
  { label: 'Draining',   sub: 'pods evicted',            type: 'action'  },
  { label: 'Terminated', sub: 'EC2 gone (~10 min total)',type: 'action'  },
]

// Script — each frame specifies the active step for each row and how long to dwell.
// AutoNode (an) completes at frame 8 while CAS (cas) is still stuck in Cooldown,
// then CAS finishes ~4 seconds later, making the timing asymmetry unmissable.
const SCRIPT: Array<{ an: number; cas: number; dwell: number }> = [
  { an: 0, cas: 0, dwell: 1000 },  // Watching / Monitoring
  { an: 1, cas: 1, dwell: 1200 },  // Evaluating / Threshold check
  { an: 2, cas: 1, dwell: 1000 },  // No Action loop 1 / still at Threshold
  { an: 1, cas: 2, dwell: 1000 },  // Re-evaluate / Cooldown starts
  { an: 2, cas: 2, dwell: 1200 },  // No Action loop 2 / still Cooling
  { an: 1, cas: 2, dwell:  800 },  // Re-evaluate (success) / still Cooling
  { an: 3, cas: 2, dwell: 1000 },  // Packing / STILL COOLING
  { an: 4, cas: 2, dwell: 1000 },  // Draining / STILL COOLING
  { an: 5, cas: 2, dwell: 2000 },  // AutoNode TERMINATED / CAS still waiting (pause to let it land)
  { an: 5, cas: 3, dwell: 1200 },  // (done) / CAS finally Draining
  { an: 5, cas: 4, dwell:  800 },  // (done) / CAS Terminated
]

// AutoNode finishes at frame 8; CAS finishes at frame 10.
// Gap: frame 8 dwell (2000) + frame 9 (1200) + frame 10 (800) = 4000 ms.

const RESET_MS = 2800

const frameIdx  = ref(-1)
const paused    = ref(false)

const anActive  = computed(() =>
  frameIdx.value < 0 ? -1 : SCRIPT[Math.min(frameIdx.value, SCRIPT.length - 1)].an
)
const casActive = computed(() =>
  frameIdx.value < 0 ? -1 : SCRIPT[Math.min(frameIdx.value, SCRIPT.length - 1)].cas
)

let stepTimer:  ReturnType<typeof setTimeout> | null = null
let resetTimer: ReturnType<typeof setTimeout> | null = null

function stepState(i: number, active: number): StepState {
  if (active < 0)   return 'inactive'
  if (i < active)   return 'done'
  if (i === active) return 'active'
  return 'inactive'
}

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
          <div v-if="i < AN_STEPS.length - 1" class="sp-arrow"
               :class="{ lit: anActive > i, back: i === 2 && anActive === 1 }">
            {{ i === 1 && anActive > 1 && anActive < 3 ? '↩' : '›' }}
          </div>
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

/* ── Waiting ───────────────────────────────────────────── */
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

/* ── Retry (loop-back indicator) ───────────────────────── */
.retry.inactive { border-color: #222; background: #111; }
.retry.active   {
  border-color: #f87171;
  background: rgba(248,113,113,.1);
  animation: pulse-step 0.8s ease-in-out infinite;
}
.retry.active .sp-label { color: #f87171; }
.retry.active .sp-sub   { color: #f8717199; }
.retry.done   { border-color: #222; background: #111; }
.retry.done .sp-label   { color: #444; }
.retry.done .sp-sub     { color: #333; }

/* ── Action ────────────────────────────────────────────── */
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
  transition: color 0.4s ease;
}
.sp-arrow.lit  { color: #555; }
.sp-arrow.back { color: #f87171; }

/* ── Pause hint ────────────────────────────────────────── */
.sp-hint {
  text-align: center;
  font-size: 0.5em;
  color: #444;
  margin-top: 2px;
  letter-spacing: 0.04em;
}
</style>
