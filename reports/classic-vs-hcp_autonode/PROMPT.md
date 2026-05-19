# PROMPT.md — Recreate or Update the ROSA Classic vs HCP with AutoNode Slide Deck

Use this file as the **source of truth** for how `slides.md` is tied to benchmark data.
Paste the **agent prompt block** at the bottom into a Cursor chat when you want to refresh numbers or narrative from new runs.

---

## Deck location (do not move these files)

| Item | Path |
|------|------|
| Slides | `reports/classic-vs-hcp_autonode/slides.md` |
| Deck TODO / deltas | `reports/classic-vs-hcp_autonode/TODO.md` |
| Components / styles | `reports/classic-vs-hcp_autonode/components/`, `styles/`, `public/` |
| Template (pattern only) | `references/mobb-deck-template/` (may be gitignored — use local checkout) |

Supporting build files (`package.json`, `Makefile`) are already in the deck directory.
**Validate:** `cd reports/classic-vs-hcp_autonode && npm run build`

---

## Slide anchors — find slide *N* in `slides.md` (no index file)

`slides.md` uses HTML markers on each logical slide:

```html
<!-- SLIDE N — Short human title -->
```

**Agent rule:** Grep/search for `<!-- SLIDE ` + **N**. **Slide *N*** = from that marker through the **line before** the next `<!-- SLIDE` marker (exclusive), or **EOF** for the final slide.

- Keep **`N` unique and sequential** in presenter order (`/1`, `/2`, … in Slidev). Duplicate markers (e.g. two “slide 12”) or gaps make “slide 15” ambiguous.
- After insert/reorder slides, **renumber anchors** — there is no generated index to fall back on.
- Slidev itself still separates slides with **`---`**; anchors are editorial navigation only — they must stay aligned with presentation order.

---

## Reality: multiple `RUN_ID`s (not a single “combined” report prefix)

This deck compares **ROSA Classic (CAS)** and **ROSA HCP + AutoNode** using **different clusters and runs**. Report filenames **never** use a shared `classic-vs-hcp_autonode` middle segment — they follow:

```text
reports/<RUN_ID>-<NN>-<cluster-kind>-<slug>.html
```

Examples:

- `reports/20260511T041449-classic-06-classic-hpa.html`
- `reports/20260511T030113-hcp-autonode-10-hcp-autonode-autonode-scale.html`

**Baseline pairing used for the current deck (May 2026):**

| Role | `RUN_ID` | Notes |
|------|-----------|--------|
| **HCP + AutoNode** (primary) | `20260511T030113-hcp-autonode` | Tests **03–13**, **05b** narrative from canvases/HTML |
| **Classic** (primary suite) | `20260511T041449-classic` | Tests **01–09**, **11–13**, **07** VPA |
| **Classic — CAS progressive waves** | `20260511T225318-classic` | **Test 14** only — pairs with AutoNode **Test 10** shape on slide 16 |
| **Classic — HPA→CAS cascade** | `20260510T193023-classic` | **Test 08** — **cold** node path (~9m 54s total); avoid `20260511T041449-classic` Test 08 (~46s) which is **pre-warmed / anomalous** |
| **Machine pools (Test 02)** | Classic `20260507T024839-classic`, HCP `20260507T232347-hcp` | Paired benchmarks — **not** the same RUN_ID as the main May 11 suite |

When you regenerate the deck for a **new** campaign, replace these RUN_IDs everywhere they appear in `slides.md`, footers, and `RhTable` rows — then reconcile **Test 14** / **Test 10** so wave rows stay comparable.

---

## Raw data locations

1. **`reports/<RUN_ID>-*.html`** — exported milestone tables (grep for `03-autoscale-up`, `elapsed_human`, metric keys).
2. **`results/<RUN_ID>/events.jsonl`** — canonical durations (`elapsed_ms`, labels like `14-cas-scale.wave_1.*`).
3. **Cursor canvases** — `.canvas.tsx` under the Cursor project canvases folder (machine-readable summaries). Naming patterns:
   - `comparison-classic-vs-hcp-autonode-*.canvas.tsx`
   - `03-autoscale-up-hcp-autonode-<RUN_ID>.canvas.tsx`
   - `test-14-cas-scale-run5.canvas.tsx` (or latest Test 14 canvas)
   - `07-vpa-advise-classic-<RUN_ID>.canvas.tsx`
   - Per-test: `06-hpa-*`, `08-hpa-triggers-cas-*`, `09-overprovisioning-*`, `11-planned-surge-*`, `12-sudden-spike-*`, `13-parallel-nodes-*`
4. **`docs/retrospectives/<RUN_ID>*.md`** — qualitative notes, anomalies, AMI cache context.
5. **`reports/index.html` + `index-data.json`** — discover what HTML exists for a date prefix.

---

## What the deck covers (current structure)

High level (matches `slides.md` slide order and Section **4–9** dividers):

1. **Title** (`slide 1`).
2. **Agenda** (`slide 2`) — section roadmap (matches numbered dividers later).
3. **Topology** — Classic vs hosted control plane (`slide 3`).
4. **Taxonomy** — fleet vs workload planes, CAS vs AutoNode, HPA vs VPA, balloons (`slides 4–7`).
5. **Benchmark checklist** — paired scenarios (`slide 8`).
6. **Section 4 — Cluster lifecycle** (`slide 9` divider): install timelines, comparison table, machine pools (**Test 02**).
7. **Section 5 — Node benchmarks** (`slide 13` divider): methodology, scale-up/down (**slide 16** two-column wave table — **Test 10** vs **Test 14**), bin-pack, consolidation, instance fit (**05b** storyline).
   - CAS Test 14 run 5: row 1 cold provision; rows 2–3 often **no new EC2**; row 4 full CAS chain. **CAS EC2→Ready** average only over waves that launched EC2 (recompute from `events.jsonl`).
   - Scale-down: AutoNode **Test 04** vs Classic **Test 04** narrative.
   - Immediately after (no divider): **HPA benchmark** (`slide 21`, Test **06** — seconds with spare capacity), **HPA→autoscaler** (`slide 22`, cold-path Classic for EC2-heavy feel), **balloons** (`slide 23`). **VPA** stays on taxonomy slide **6** + Test **07** HTML — no timed slide.
8. **Section 7 — Advanced labs** (`slide 24` divider): tests **11–12** — planned surge, sudden spike. (**Test 13** / parallel nodes: benchmark harness only — not shown in slides.)
9. **Section 8 — Comparison** (`slide 27` divider): head-to-head table (`slide 28`) + structural advantages slide (`slide 29`) — **must align** with slide 16 / Test 04 rows after updates.
10. **Section 9 — Findings & close** (`slide 30` divider onwards).

**Note:** AutoNode prereq steps live in `clusters/classic-vs-hcp_autonode/create.sh` docs — not standalone slides.

**Terminology:** Prefer **AutoNode** in narrative; **Karpenter** only where explaining implementation (title/subtitle may still say Karpenter for search clarity).

---

## Repository coupling (agents)

Per **`AGENTS.md`**:

- **Tests 10 & 14** are **linked**: wave counts, CPU requests on manifests, milestone naming, timeouts — change **both** test scripts/skills when altering progressive scale benchmarks.

---

## Key slides ↔ data sources (checklist for updates)

| Slide topic | Primary source |
|-------------|----------------|
| Install Classic | `reports/<classic>-01-*-cluster-install.html` |
| Install HCP | Canvas `hcp-install-timing-*`, suite HTML, or events |
| Machine pools | Canvas `hcp-vs-classic-benchmark-01-02.canvas.tsx` or `benchmark-02-machine-pool*.canvas.tsx` + paired RUN_IDs |
| Scale-up waves | AutoNode: `*-10-*-autonode-scale.html` + canvas `test-10-autonode-scale-<RUN>.canvas.tsx`; CAS: Test **14** canvas (`test-14-cas-scale-run5.canvas.tsx`) + `results/<classic-test14>/events.jsonl` |
| Scale-down | AutoNode `*-04-*-autoscale-down.html`; Classic `*-04-*` |
| 05b vs pool (CAS) | **Test 05b** timing on HCP canvas/HTML + Classic **NotTriggerScaleUp** framing (no standalone Test **05** slide) |
| 06–09 (other tests) | HTML for **both** cluster RUN_IDs where comparison slides exist |
| Slide **23** balloons | Classic Test **09** `*-09-classic-overprovisioning.html` (e.g. `20260511T225318-...`); HCP Test **09b** `*-09b-*-karpenter-overprovisioning.html` (e.g. `20260511T030113-hcp-autonode-09b-...`). Row **‡** (“first new workers”) = `after_workload_running.timestamp_ms` → first `sustained_peak.samples[]` with non-empty **`nodes_added_vs_prev`** (60 s poll granularity) |
| 08 Classic cold path | Prefer **`20260510T193023-classic`** until superseded |
| 11–12 | Per-test canvases for each RUN_ID (**13** supplementary — deck omits parallel-nodes slide) |
| Head-to-foot summary | Recompute after changing slide 16 / Test 04 |

---

## Template authoring rules

Before large edits:

1. `references/mobb-deck-template/AGENTS.md` — layout, Mermaid (no diagrams inside Vue slots), components, optional **`<!-- SLIDE N — … -->`** anchors (*Optional slide anchors* section).
2. `references/mobb-deck-template/slides.md` — format patterns only.

Deck conventions:

- **`<!-- SLIDE N — … -->`** at the top of each logical slide — agents locate “slide N” from that marker to the next marker (see **Slide anchors** above).
- Speaker notes on every slide (HTML comment).
- Mermaid in bare markdown only (not inside `<RhTwoColumn>`).
- Available components: `<RhTwoColumn>`, `<RhTable>`, `<RhTimeline>`, `<RhSpectrum>`.

---

## Agent prompt block (paste into Cursor)

Replace every `← SET` before sending.

```
You are updating the ROSA Classic vs HCP + AutoNode slide deck.

Paths:
- Slides: reports/classic-vs-hcp_autonode/slides.md — find slide *N* via `<!-- SLIDE N —` comments (through line before next `<!-- SLIDE`).
- Read PROMPT.md in that folder for RUN_ID rules, slide anchors, and slide↔data mapping.

RUN_IDs for this refresh:
- HCP_AUTONODE_RUN ← SET (e.g. 20260511T030113-hcp-autonode)
- CLASSIC_SUITE_RUN ← SET (e.g. 20260511T041449-classic)
- CLASSIC_TEST14_RUN ← SET (e.g. 20260511T225318-classic) — CAS progressive waves vs AutoNode Test 10
- CLASSIC_TEST08_RUN ← SET — MUST be cold-path HPA→CAS cascade if presenting EC2-heavy totals (e.g. 20260510T193023-classic unless user supplies a newer cold run)
- MACHINE_POOL_CLASSIC_RUN ← SET (e.g. 20260507T024839-classic)
- MACHINE_POOL_HCP_RUN ← SET (e.g. 20260507T232347-hcp)

Tasks:
1. Pull timings from reports/<RUN>-*.html, results/<RUN>/events.jsonl, and matching canvases (*.canvas.tsx).
2. Update slides.md numbers and RUN_ID footers; preserve narrative unless results contradict it.
3. Slide 16: keep AutoNode Test 10 vs CAS Test 14 alignment; CAS **Nodes** column = **standard `pool-type` Ready workers after each wave** (from events / `oc` for the RUN_ID — **flat** across waves labeled `scale_fits_existing_capacity`; **first increment with `*_cas_triggered_to_node_ready` adds +1**). CAS EC2→Ready = mean only over waves that timed new EC2 (`cas_triggered_to_node_ready`); slack rows leave EC2 blank and Total = `.scale_to_pods_ready` only.
4. Do not invent unified HTML filenames — reports always include cluster kind in the slug.
5. Run: cd reports/classic-vs-hcp_autonode && npm run build — fix errors before finishing.

Do NOT edit references/mobb-deck-template unless fixing template bugs.
Optional: refresh reports/classic-vs-hcp_autonode/TODO.md with follow-ups after the user reviews diffs.
```

---

## Tips

**Numbers-only refresh:** Point the agent at `PROMPT.md` + new RUN_ID list; ask to preserve headings and speaker-note intent.

**After harness changes:** If Test 10 or 14 wave logic changes, update **both** tests per `AGENTS.md`, then regenerate slide 16 and Section 8 (comparison slides).

**PDF export:**

```bash
cd reports/classic-vs-hcp_autonode
npx playwright install chromium   # first time only
make export                         # slides-export.pdf
```
