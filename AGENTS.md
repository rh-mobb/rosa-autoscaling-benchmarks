# AGENTS.md

## External Repository Policy

**Never push to any external Git repository without explicit user confirmation.**

This includes `git push`, `gh pr create`, force-push, and any other operation that writes to a remote  -  regardless of whether the repo is under the same GitHub org or appears to be the user's own. Switching a remote from HTTPS to SSH to work around credential prompts and then pushing is also forbidden without confirmation.

Before any `git push` to a remote:
1. State exactly which repository, branch, and commit(s) would be pushed.
2. Ask the user explicitly: "Can I push this to `<remote>/<branch>`?"
3. Wait for a clear yes before proceeding.

This rule takes precedence over "hands-off" harness recovery paths. Even if a skill or benchmark flow documents an automated recovery step that involves pushing code, stop and confirm with the user first.

## Linked Tests  -  Tests 10 and 14 Are Coupled

Tests 10 (`run-test-10-autonode-scale.py`) and 14 (`run-test-14-cas-scale.py`) are
the Karpenter and CAS counterparts of the same progressive scale benchmark.

**Hard rule: any change to one of these files MUST be reflected in the other:**

- Wave counts and replica targets (`REPLICA_WAVES`, `ROLLBACK_STEPS`)
- CPU resource requests on the workload manifests (`autonode-app.yaml`, `cas-scale-app.yaml`)
- Milestone naming conventions (`<phase>.<step>` key naming)
- Timeout values used for equivalent phases (scale-up provision, scale-down)
- The comparable key stats in Phase 1 and Phase 3 (so the Canvas comparison table stays valid)

This coupling also applies to the skill files:
- `.cursor/skills/benchmark-autonode-scale/SKILL.md` ↔ `.cursor/skills/benchmark-cas-scale/SKILL.md`
- `.cursor/skills/benchmark-advanced-autoscaling/SKILL.md` documents both

If you modify test 10 (e.g. change replica sizes, add a wave, rename a milestone),
open test 14 in the same edit and apply the symmetric change before committing.

## Typography

**Never use em-dashes (`—`, U+2014) in any source file.**
Use a spaced hyphen (` - `) instead. Em-dashes are invisible to most linters, cause encoding issues in scripts that do string matching, and are inconsistent across editors and copy-paste contexts.

This applies to: `.md` files, `.vue` components, `.ts`/`.js` source, YAML, speaker notes, inline HTML in slides  -  everywhere.

## Common Corrections & Misconceptions

These are errors the agent has made more than once. Treat each entry as a hard rule.

### CAS does NOT use AWS Auto Scaling Groups on ROSA Classic

On ROSA Classic, Cluster Autoscaler scales **MachineSets** (OpenShift Machine API objects).
The Machine API controller then calls **EC2 `RunInstances` directly**  -  there is no Auto Scaling Group in the provisioning path.

Correct provisioning chain:
> CAS decision → MachineSet replica increment → Machine API creates Machine object → EC2 `RunInstances` → instance running → three-boot (Ignition → MCD → final boot) → Node Ready

Karpenter (HCP AutoNode) is different: it uses the **EC2 Fleet API** for batched, faster launches.
Never describe the Classic CAS path as "ASG-based" or "queue-based via ASG".

### Slide deck navigation (`presentation/`)

Long Slidev decks in this repo annotate each logical slide in `slides.md` with **`<!-- SLIDE N  -  descriptive title -->`**.

When the user asks to edit **slide *N***: search for that marker, then treat **slide body** as from that line through the **line before** the next `<!-- SLIDE` comment (or **end of file**). No separate slide index  -  the markers **are** the map. Renumber anchors when reordering slides so **`N`** stays unique and aligned with Slidev presenter order (`/1`, `/2`, …).

See **`presentation/PROMPT.md`** (section *Slide anchors*) for the canonical wording. Decks cloned from **`references/mobb-deck-template/`** SHOULD follow the same pattern for reusability across projects.

<!-- keel:start - DO NOT EDIT between these markers -->
## Rules

| Rule | Globs | Always Apply |
|------|-------|--------------|
| agent-behavior | `["**/*"]` | true |
| base | `["**/*"]` | true |
| scaffolding | `["**/*"]` | true |
| kubernetes | `["**/manifests/**/*.yaml", "**/k8s/**/*.yaml", "**/deploy/**/*.yaml", "**/templates/**/*.yaml", "**/base/**/*.yaml", "**/overlays/**/*.yaml"]` | false |
| markdown | `["**/*.md"]` | false |
| python | `["**/*.py", "**/Pipfile", "**/pyproject.toml", "**/requirements*.txt"]` | false |
| yaml | `["**/*.yaml", "**/*.yml"]` | false |

## Rule Details

### agent-behavior
- **Description:** Universal behavioral safety rules for AI agents interacting with live systems
- **Globs:** `["**/*"]`
- **File:** `.agents/rules/keel/agent-behavior.md`

### base
- **Description:** Global coding standards that apply to all files and languages
- **Globs:** `["**/*"]`
- **File:** `.agents/rules/keel/base.md`

### scaffolding
- **Description:** Interactive guidance for essential project scaffolding files
- **Globs:** `["**/*"]`
- **File:** `.agents/rules/keel/scaffolding.md`

### kubernetes
- **Description:** Kubernetes manifest and workload conventions
- **Globs:** `["**/manifests/**/*.yaml", "**/k8s/**/*.yaml", "**/deploy/**/*.yaml", "**/templates/**/*.yaml", "**/base/**/*.yaml", "**/overlays/**/*.yaml"]`
- **File:** `.agents/rules/keel/kubernetes.md`

### markdown
- **Description:** Markdown writing conventions for .md files
- **Globs:** `["**/*.md"]`
- **File:** `.agents/rules/keel/markdown.md`

### python
- **Description:** Python coding conventions and best practices
- **Globs:** `["**/*.py", "**/Pipfile", "**/pyproject.toml", "**/requirements*.txt"]`
- **File:** `.agents/rules/keel/python.md`

### yaml
- **Description:** YAML formatting and structure conventions
- **Globs:** `["**/*.yaml", "**/*.yml"]`
- **File:** `.agents/rules/keel/yaml.md`
<!-- keel:end -->
