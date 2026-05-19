## Coding Rules

- `.cursor/rules/local/rosa-benchmark-invocation.mdc` — benchmark **`benchmark-*`** skills + **mandatory deliverables**: tests **01** → **`reports/`** HTML; **02–09** → **Canvas** (and suite HTML for **`benchmark-run-all`**); tests **10–13** → **Canvas** per test + suite HTML (see **`benchmark-advanced-autoscaling`**); do not stop at partial **`make`** steps unless the user explicitly accepts no report; **hands-off** recoveries (skill-documented retries such as HCP **`NO_REFRESH`** destroy) — run them, do not ask the user for flags

See `.agents/rules/keel/` for detailed coding standards. Key rules:
- `.agents/rules/keel/agent-behavior.md` — Universal behavioral safety rules for AI agents interacting with live systems (always apply)
- `.agents/rules/keel/base.md` — Global coding standards that apply to all files and languages (always apply)
- `.agents/rules/keel/scaffolding.md` — Interactive guidance for essential project scaffolding files (always apply)
- `.agents/rules/keel/kubernetes.md` — Kubernetes manifest and workload conventions (manifests/*.yaml, k8s/*.yaml, deploy/*.yaml, templates/*.yaml, base/*.yaml, overlays/*.yaml)
- `.agents/rules/keel/markdown.md` — Markdown writing conventions for .md files (*.md)
- `.agents/rules/keel/python.md` — Python coding conventions and best practices (*.py, Pipfile, pyproject.toml, requirements*.txt)
- `.agents/rules/keel/yaml.md` — YAML formatting and structure conventions (*.yaml, *.yml)