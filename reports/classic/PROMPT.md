# PROMPT.md — ROSA Classic Benchmark Slide Deck

This file documents how to **recreate this slide deck from scratch** or **update it with new benchmark data** for a different run ID.

---

## Quick start — update data for a new run

Paste the prompt below into Cursor Agent, replacing `<RUN_ID>` with the new run identifier (e.g. `20260508T025316-classic`):

```
Update the ROSA Classic benchmark slide deck at `reports/classic/slides.md` with
data from run ID <RUN_ID>.

## Where to find the data

1. **Checkpoint summary** — all per-test elapsed times:
   ```
   python3 scripts/checkpoint.py status --run-id <RUN_ID>
   ```

2. **Suite HTML report** — full findings, timing table, key findings, recommendations,
   and anomalies:
   `reports/<RUN_ID>-classic-suite-01-through-09.html`

3. **Individual test HTML reports** — detailed per-test milestones:
   `reports/<RUN_ID>-classic-01-classic-cluster-install.html`
   `reports/<RUN_ID>-classic-03-classic-autoscale-up.html`
   … (pattern: `<RUN_ID>-classic-<NN>-classic-<test-name>.html`)

4. **Cluster config** — classic.env (cluster name, region, instance type, OCP version)

## What to update in slides.md

For each test whose timing changed, find the corresponding slide and update:

| Slide area | What to change |
|------------|----------------|
| Slide 7 — install stat callout | `63 min 39 s` → new total install time |
| Slide 8 — RhTimeline milestones | The `date:` values (elapsed times at each milestone) |
| Slide 10 — machine pool table | Per-pool provisioning times |
| Slides 12–13 — CAS results | Scale-up and scale-down elapsed times and key events |
| Slide 18 — HPA result line | `5m 16s` → new HPA response time |
| Slide 22 — HPA→CAS stat callout | `11 min 3 s` → new HPA+CAS cascade time |
| Slide 25 — overprovisioning stat | `4.1×` speedup and `11 min 3 s → 2 min 41 s` times |
| Slide 26 — before/after comparison | Test 08 and Test 09 totals |
| Slide 29 — all-tests table | Every row in the RhTable |
| Slide 30 — key findings | Bullet text referencing specific numbers |
| Slide 31 — recommendations | Update any cost calculations (instance pricing) |
| Title slide / meta text | Run ID, date |

Also update the run ID and date wherever they appear (search for `20260508T025316-classic`
and `May 2026`).

## Authoring rules (summary)

- Read `references/mobb-deck-template/AGENTS.md` before touching any slide.
- Mermaid blocks must be in **plain slide Markdown** — NOT inside Vue component slots.
- All Mermaid diagrams in `layout: two-cols` must use `flowchart LR`, not `TD`
  (TD diagrams overflow the right column — see the fix already applied in this deck).
- The `RhTimeline` date labels use `var(--rh-text)` (fixed in `components/RhTimeline.vue`
  in this deck — do not revert to `var(--rh-border)`).
- Every slide must have a speaker note.
- After editing, run `npm run build` in `reports/classic/` and fix any errors.
```

---

## Full recreation prompt — build from scratch for a new run

Use this when you want to generate a completely fresh deck for any Classic benchmark run:

```
You are building a technical presentation slide deck using the mobb-deck-template
Slidev framework. The talk covers a complete ROSA Classic autoscaling benchmark run.

## Reference material (read-only — do not modify)

The template lives at `references/mobb-deck-template/`. Read these two files first:

1. `references/mobb-deck-template/AGENTS.md` — authoring rules, Mermaid constraints,
   component API, known pitfalls, and the mandatory review checklist.
2. `references/mobb-deck-template/slides.md` — 15 example slide formats. Pattern
   library only — do not edit it.

## Output location

Output directory: `reports/classic/`
Slides file:      `reports/classic/slides.md`
Components:       `reports/classic/components/`
Styles:           `reports/classic/styles/`
Assets:           `reports/classic/public/`

Copy `references/mobb-deck-template/package.json` and
`references/mobb-deck-template/Makefile` to the output directory.
Copy `references/mobb-deck-template/styles/` and
`references/mobb-deck-template/components/` to the output directory.

**After copying `components/RhTimeline.vue`, patch the date label color:**
Change `color: 'var(--rh-border)'` → `color: 'var(--rh-text)'` and
`class="text-[9px]"` → `class="text-[11px] font-semibold"` on the date `<div>`.
This makes milestone times readable on the dark background.

## Benchmark run to present

Run ID: <RUN_ID>   ← replace this

## Data sources — read all of these before writing a single slide

1. **README.md** — what the benchmark harness is, what each test number measures
2. **Checkpoint summary** (run this command, capture the output):
   ```
   python3 scripts/checkpoint.py status --run-id <RUN_ID>
   ```
3. **Suite HTML report:**
   `reports/<RUN_ID>-classic-suite-01-through-09.html`
   Contains: all timing data, key findings, anomalies, recommendations.
4. **Cluster config:** `classic.env` — cluster name, region, OCP version, instance type
5. **Individual test reports** (for milestone-level detail):
   `reports/<RUN_ID>-classic-01-classic-cluster-install.html`
   `reports/<RUN_ID>-classic-03-classic-autoscale-up.html`
   `reports/<RUN_ID>-classic-04-classic-autoscale-down.html`
   `reports/<RUN_ID>-classic-09-classic-overprovisioning.html`

## Talk brief

Audience: Technical internal Red Hat employees familiar with Kubernetes and OpenShift.
Tone: Engineering deep-dive — real numbers, honest anomalies, actionable takeaways.
Length: ~30 minutes (25–32 slides).
Core thesis: EC2 provisioning time is the dominant latency in every CAS-triggered
  autoscaling path — and the overprovisioning pattern eliminates it from the hot path
  entirely.

## Required slide structure

Follow this section order. Use the benchmark data to fill in all times and findings:

1. **Title** — "ROSA Classic Autoscaling: Speed, Scale & the Hidden Bottleneck"
2. **Agenda** — two-column: why it matters (left) + section list (right)
3. **Section 1** — Cluster config, tooling, how timings were captured
4. Cluster config table (RhTable)
5. Measurement methodology (bullets)
6. **Section 2** — Test 01: How long does `make create-classic` take?
7. Install time stat callout (big number, layout: center)
8. Install milestone timeline (RhTimeline — 5 milestones)
9. **Section 3** — Test 02: Machine pool provisioning
10. Machine pool table (RhTable — one row per type tested)
11. **Section 4** — Tests 03 & 04: CAS scale-up and scale-down
12. CAS scale-up flow (layout: two-cols, Mermaid **flowchart LR** on right)
13. Scale-up vs scale-down results (RhTwoColumn)
14. CAS event name discovery note (bullets — `ScaledUpGroup` vs `TriggeredScaleUp`)
15. **Section 5** — Test 05: The unschedulable case
16. `NotTriggerScaleUp` explanation (RhTwoColumn)
17. **Section 6** — Tests 06 & 07: HPA and VPA
18. HPA response flow (layout: two-cols, Mermaid **flowchart LR** on right)
19. VPA advise + coexistence pattern (RhTwoColumn)
20. **Section 7** — Test 08: HPA triggers CAS (saturated cluster)
21. HPA → CAS cascade flow (layout: two-cols, Mermaid **flowchart LR** on right)
22. HPA+CAS total time stat callout (big number, layout: center)
23. **Section 8** — Test 09: Overprovisioning
24. Overprovisioning mechanism (layout: two-cols, Mermaid **flowchart LR** on right)
25. Speedup stat callout — X× faster (big number, layout: center)
26. Before/after comparison (RhTwoColumn)
27. Autoscaling maturity spectrum (RhSpectrum)
28. **Section 9** — Findings & Recommendations
29. All-tests summary table (RhTable)
30. Key findings (bullets — 5 max, each tied to a specific number from the run)
31. Recommendations (bullets — 5 max, actionable, mention next benchmark)
32. **Closing CTA** (layout: center — the headline and the three-line punchline)

## Critical Mermaid rules for this deck

- All Mermaid diagrams in `layout: two-cols` slides **must** use `flowchart LR`.
  `flowchart TD` overflows the right column. The existing CSS handles LR scaling.
- Do NOT put Mermaid inside `<RhTwoColumn>` slots — use `layout: two-cols` instead.
- Quote edge labels containing parentheses or special characters.
- Do not use `fill:` / `color:` style statements in Mermaid.

## Deliverable

A complete `slides.md` ready to run with `make dev`. After writing, run:

```
cd reports/classic && npm install && npm run build
```

Fix any errors before declaring the deck ready.
```

---

## Deck structure reference

The current deck (`slides.md`) has 32 slides organized as 9 sections:

| Slides | Content | Key component |
|--------|---------|---------------|
| 1–2 | Title, Agenda | — |
| 3–5 | Section 1: Setup — cluster config, methodology | RhTable |
| 6–8 | Section 2: Test 01 — install timing | Stat callout, RhTimeline |
| 9–10 | Section 3: Test 02 — machine pool provisioning | RhTable |
| 11–14 | Section 4: Tests 03–04 — CAS scale-up/down | two-cols + Mermaid LR, RhTwoColumn |
| 15–16 | Section 5: Test 05 — unschedulable workload | RhTwoColumn |
| 17–19 | Section 6: Tests 06–07 — HPA and VPA | two-cols + Mermaid LR, RhTwoColumn |
| 20–22 | Section 7: Test 08 — HPA triggers CAS | two-cols + Mermaid LR, stat callout |
| 23–27 | Section 8: Test 09 — overprovisioning | two-cols + Mermaid LR, stat callout, RhTwoColumn, RhSpectrum |
| 28–32 | Section 9: Findings, recommendations, closing | RhTable, bullets, CTA |

---

## Known fixes already applied in this deck

These are **not** in the upstream `references/mobb-deck-template/` — they live only
in `reports/classic/components/` and `reports/classic/styles/`. Preserve them when
updating:

| File | Fix | Why |
|------|-----|-----|
| `components/RhTimeline.vue` | Date label: `color: var(--rh-text)`, `text-[11px] font-semibold` | `var(--rh-border)` (#383838) is invisible on the dark bg (#1A1A1A) |
| All `two-cols` + Mermaid slides | `flowchart LR` instead of `flowchart TD` | TD diagrams are too tall and clip at the bottom of the right column |

---

## Running the deck locally

```bash
cd reports/classic
make dev          # starts dev server at http://localhost:3030
make build        # build to dist/
make export       # export to PDF (requires playwright)
```
