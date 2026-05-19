<script setup>
/**
 * RhTimeline — horizontal milestone timeline.
 *
 * Props:
 *   milestones  Array of { date: string, label: string, color?: string }
 *               color defaults to var(--rh-red) when omitted.
 *   legend      Optional array of { color: string, label: string } items
 *               shown as a colour-key below the timeline.
 *
 * Example usage in slides.md:
 *
 *   <RhTimeline
 *     :milestones="[
 *       { date: 'Jan 1',  label: 'Kickoff',        color: '#73BCF7' },
 *       { date: 'Feb 14', label: 'First milestone', color: '#EE0000' },
 *       { date: 'Mar 31', label: 'Launch',          color: '#5BA352' },
 *     ]"
 *     :legend="[
 *       { color: '#73BCF7', label: 'Phase 1' },
 *       { color: '#EE0000', label: 'Phase 2' },
 *       { color: '#5BA352', label: 'Phase 3' },
 *     ]"
 *   />
 */
defineProps({
  milestones: { type: Array, required: true },
  legend: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="relative mt-4">
    <div class="h-px bg-[var(--rh-border)] w-full absolute" style="top: 24px" />
    <div class="flex justify-between relative">
      <div
        v-for="m in milestones"
        :key="m.date"
        class="flex flex-col items-center"
        style="flex: 1"
      >
        <div
          class="w-3 h-3 rounded-full z-10 mt-[18px]"
          :style="{ background: m.color || 'var(--rh-red)' }"
        />
        <div
          class="text-[10px] text-center mt-2 leading-tight whitespace-pre-line"
          :style="{ color: 'var(--rh-muted)' }"
        >
          {{ m.label }}
        </div>
        <div class="text-[11px] mt-1 font-semibold" :style="{ color: 'var(--rh-text)' }">
          {{ m.date }}
        </div>
      </div>
    </div>
    <div v-if="legend.length" class="flex gap-4 mt-4 text-[10px]" :style="{ color: 'var(--rh-muted)' }">
      <span v-for="l in legend" :key="l.label">
        <span
          class="inline-block w-2 h-2 rounded-full mr-1"
          :style="{ background: l.color, verticalAlign: 'middle' }"
        />{{ l.label }}
      </span>
    </div>
  </div>
</template>
