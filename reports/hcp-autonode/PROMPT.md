# PROMPT.md — Recreate or Update the AutoNode Benchmark Slide Deck

Paste the prompt below into a Cursor Agent chat to regenerate or update
`reports/hcp-autonode/slides.md` from a given benchmark run.

Replace every `← SET THIS` line before pasting.

---

```
You are updating the ROSA HCP AutoNode benchmark slide deck.

## Deck location (do not move these files)

Output directory: `reports/hcp-autonode/`
Slides file:      `reports/hcp-autonode/slides.md`
Components:       `reports/hcp-autonode/components/`
Styles:           `reports/hcp-autonode/styles/`
Assets:           `reports/hcp-autonode/public/`

The supporting files (components, styles, package.json, Makefile) are already
in place — do not overwrite them unless something is broken.

## Template authoring rules

Read these two files before touching a single slide:

1. `references/mobb-deck-template/AGENTS.md` — layout rules, Mermaid
   constraints, component API, known pitfalls, self-review checklist.
2. `references/mobb-deck-template/slides.md` — 15 example slide formats.
   Use as a pattern library only — do not edit it.

## Run to base the deck on                     ← SET THIS

RUN_ID: 20260508T031735-hcp-autonode

(Change this to the run you want to present. The RUN_ID appears in every
report filename under `reports/` and in the `results/<RUN_ID>/` directory.)

## Source data — read all of these for the run above

### Benchmark reports (HTML)
- `reports/<RUN_ID>-10-hcp-autonode-autonode-scale.html`  — Test 10: Karpenter
  scale-up and consolidation. Contains every milestone timestamp in ms.
- `reports/<RUN_ID>-01-hcp-autonode-cluster-install.html` — Cluster install
  timing (if present for this run).
- `reports/index.html` — links to all runs; useful for finding related reports.

### Canvas reports (rich narrative with computed stats)
- Canvases live in the Cursor canvas store. Search for canvas files whose
  name contains "autonode". The two key ones are:
  - `hcp-autonode-install-benchmark.canvas.tsx` — install milestones,
    403 recovery notes, AutoNode IAM setup steps.
  - `autonode-karpenter-scaling-benchmark.canvas.tsx` — all wave and rollback
    timings, pod-packing discovery, bar charts, CAS comparison.
  These files are the source of truth for computed averages and annotations.

### Repository context
- `README.md` — benchmark harness overview and test numbering.
- `autonode.env` — cluster config used for the run (instance type, region,
  replicas, AutoNode shard, etc.).
- `manifests/autonode/nodepool.yaml` — NodePool spec used in Test 10.
- `manifests/workloads/autonode-app.yaml` — workload spec (CPU request,
  image, replica count at baseline).
- `scripts/run-test-10-autonode-scale.py` — the test driver; read it to
  understand exactly what each milestone measures.
- `clusters/hcp-autonode/create.sh` — AutoNode setup steps (IAM, tags,
  rosa edit --autonode=enabled) for context on the install section.

## What the deck covers (current structure — preserve unless told otherwise)

The deck tells the AutoNode story in 6 sections:

1. **What Is AutoNode** — CAS vs Karpenter concept comparison
2. **Setting Up AutoNode** — prerequisites beyond standard HCP
3. **Cluster Install Timing** — milestone timeline + clean-run estimate
4. **Karpenter Scale-Up Benchmark** — test design, NodeClaim decision stat,
   wave results table, pod-packing discovery
5. **Karpenter Consolidation Benchmark** — rollback results, state diagram
6. **Karpenter vs CAS** — head-to-head table, 4.8× stat slide
7. **Findings and Recommendations** — key findings, four recommendations,
   roadmap, closing

When updating for a new run, replace every timing number in the slides with
the values from the new run's HTML report and canvas. Keep the section
structure and narrative unless the new results tell a materially different
story — if they do, explain the change in a speaker note.

## Key numbers to update for each new run

From `reports/<RUN_ID>-10-hcp-autonode-autonode-scale.html`, extract:

| Milestone key | Slide it appears on |
|---|---|
| `initial.pending_to_nodeclaim` | "Karpenter Scheduling Decision" stat slide |
| `initial.nodeclaim_to_node_ready` | same slide (sub-text) |
| `initial.pending_to_pods_running` | "End-to-End Scale-Up" comparison slide |
| `wave_1.*`, `wave_2.*`, `wave_3.*` | "Scale-Up Wave Results" table |
| `rollback_3.*`, `rollback_2.*`, `rollback_1.*` | "Consolidation" table |
| avg of nodeclaim_to_node_ready across waves | "Karpenter vs CAS" table row 2 |
| avg of scale_to_consolidated across consolidating rollbacks | same table row 4 |

Also update the `RhTimeline` milestones on the install slide if a new
cluster-install report is present for this run.

## Authoring rules (summary)

- Frontmatter: keep `theme: default`, `highlighter: shiki`, Red Hat fonts.
- Every slide needs a speaker note (HTML comment block).
- Mermaid blocks must be in plain slide Markdown — NOT inside Vue component
  slots (`<RhTwoColumn>`, etc.).
- Keep bullets to 4–5 items; split rather than scroll.
- `<RhTwoColumn>`, `<RhTable>`, `<RhTimeline>`, `<RhSpectrum>` are available.
- Do NOT use `max-h-[Xvh]` on images — use `.rh-image-slide` wrapper instead.
- Timeline label text should use `var(--rh-text)` not `var(--rh-muted)` —
  the component in `components/RhTimeline.vue` was already patched for this.

## Deliverable

Updated `reports/hcp-autonode/slides.md` with all timings reflecting the
specified RUN_ID. Then run:

  cd reports/hcp-autonode && npm run build

Fix any build errors before declaring the update done.
```

---

## Tips

**Updating numbers only** — if the deck structure is fine and you just want
fresh timings from a new run, tell the agent:
> "Update the slide deck in `reports/hcp-autonode/` for run ID `<NEW_RUN_ID>`.
> Replace all timing numbers from the old run with the new run's milestones.
> Keep the narrative and structure unchanged."

**Restructuring after a redesigned test** — if the wave design changed
(e.g. you switched to 1500m CPU requests), also say:
> "The pod-packing discovery slide may need updating — 1500m requests mean
> 2 pods/node on fresh Karpenter nodes instead of 3. Revise the discovery
> callout and the wave results accordingly."

**Adding a new section** — follow the format in
`references/mobb-deck-template/AGENTS.md` → "Adding a new slide format".
Identify the closest existing format in the template's `slides.md`, then
add the new slide after the existing examples.

**Exporting to PDF** — once the build passes:
```bash
cd reports/hcp-autonode
npx playwright install chromium   # first time only
make export                        # writes slides-export.pdf
```
