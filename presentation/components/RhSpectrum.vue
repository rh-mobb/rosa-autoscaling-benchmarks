<script setup>
/**
 * RhSpectrum  -  horizontal maturity / spectrum scale.
 *
 * Props:
 *   stages       Array of { label: string, icon?: string, active?: boolean }
 *                The active stage is highlighted in var(--rh-red).
 *   leftLabel    Label for the left end of the scale (default: "← basic")
 *   rightLabel   Label for the right end of the scale (default: "advanced →")
 *
 * Example usage in slides.md:
 *
 *   <RhSpectrum
 *     :stages="[
 *       { label: 'Code\nAutocomplete', icon: '⌨️' },
 *       { label: 'Chat\nAssistant',    icon: '💬' },
 *       { label: 'Agent\nwith Tools',  icon: '🔧' },
 *       { label: 'Joint Engineering\nPartner', icon: '🤝', active: true },
 *     ]"
 *     left-label="← vibe coding"
 *     right-label="joint engineering →"
 *   />
 */
defineProps({
  stages: { type: Array, required: true },
  leftLabel: { type: String, default: '← basic' },
  rightLabel: { type: String, default: 'advanced →' },
})
</script>

<template>
  <div class="flex items-stretch gap-0 mt-6 rounded overflow-hidden border border-[var(--rh-border)]">
    <div
      v-for="(s, i) in stages"
      :key="i"
      :class="[
        'flex-1 flex flex-col items-center justify-center py-4 px-2 text-center text-xs',
        s.active
          ? 'bg-[var(--rh-red)] text-white font-bold'
          : 'bg-[var(--rh-surface)] text-[var(--rh-muted)]',
      ]"
    >
      <div v-if="s.icon" class="text-2xl mb-2">{{ s.icon }}</div>
      <div class="whitespace-pre-line leading-tight font-['Red_Hat_Display']">{{ s.label }}</div>
    </div>
  </div>
  <div class="flex justify-between text-[10px] text-[var(--rh-muted)] mt-1 px-1">
    <span>{{ leftLabel }}</span>
    <span>{{ rightLabel }}</span>
  </div>
</template>
