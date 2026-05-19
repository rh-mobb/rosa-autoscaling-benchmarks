# Apply Keel Best Practices to This Project

You are applying best practices from Project Keel's AGENTS.md and rules to ensure this project has essential scaffolding and follows recommended standards. Your job is to audit the project, report what's missing, and guide the user through adding files — **never create files automatically without explicit user consent**.

## Step 1: Determine project context

- **Git repo?** — If the project root does not contain `.git`, note that this is not a git repository. Many scaffolding items (`.gitignore`, CONTRIBUTING, etc.) are git-specific. Ask whether the user intends to use git or if this is a non-git project.
- **Read AGENTS.md** — If present, use it for project-specific guidance and any `skip-auto-validation` or other overrides.
- **Detect languages** — Look for `package.json`, `go.mod`, `requirements.txt`, `Cargo.toml`, `*.tf`, etc. to adapt scaffolding (e.g., Makefile targets, CI steps, `.gitignore` patterns).
- **Detect existing tooling** — Check for `.github/workflows/`, `Makefile`, `Dockerfile`, `.editorconfig`, etc.

## Step 2: Run the audit checklist

Check for each item below. For each **missing** item, record it and prepare a brief explanation and offer to create it. Do **not** create anything yet — aggregate findings first.

### Essential (for git repos)

| File / Item | Purpose |
|-------------|---------|
| `.gitignore` | Ignore OS files (`.DS_Store`, `Thumbs.db`), IDE files (`.idea/`, `.vscode/`), env files (`.env`, `.env.*.local`), logs (`*.log`), build dirs (`tmp/`, `.cache/`). Merge language-specific patterns from the relevant rule (e.g., `node_modules/`, `__pycache__/`) into one `.gitignore`. |
| `LICENSE` | Declare the project's license. **Ask the user to choose** if missing — do not assume. |
| `CONTRIBUTING.md` | Guide contributors: how to report bugs, propose features, submit PRs, set up dev environment, code style, link to Code of Conduct. |
| `README.md` | Project name, description, prerequisites, installation, usage, links to CONTRIBUTING and LICENSE. |

### Recommended

| File / Item | Purpose |
|-------------|---------|
| `CODE_OF_CONDUCT.md` | Community expectations. Default: Contributor Covenant v2.1. Ask before creating; let the user customize contact info. |
| `Makefile` | Consistent dev interface: `help` (default), `build`, `test`, `lint`, `clean`. Adapt to detected language. |
| `.github/workflows/ci.yml` | CI on push/PR: lint, test, build. Adapt to language. Use pinned action versions. |
| `CHANGELOG.md` | [Keep a Changelog](https://keepachangelog.com/) format, Conventional Commits, `## [Unreleased]` section. |
| `SECURITY.md` | Supported versions, how to report vulnerabilities privately, expected response timeline. |
| `.editorconfig` | Consistent indentation, line endings, charset across editors. |
| `Dockerfile` + `.dockerignore` | Multi-stage build, non-root runtime. Offer only if the project appears containerizable. |

## Step 3: Resolve ambiguity before creating

Before creating any file, resolve choices with the user when there is ambiguity:

- **LICENSE** — Present options and ask the user to choose:
  - **MIT** — Permissive, simple, widely used; allows commercial use with minimal restrictions.
  - **Apache 2.0** — Permissive with explicit patent grant; preferred by many enterprises.
  - **GPL-3.0** — Copyleft; derivative works must also be GPL-licensed.
  - **BSD-3-Clause** — Permissive, similar to MIT with a non-endorsement clause.
  - **Other** — Let the user specify.
  Ask for **copyright year** and **copyright holder name** (e.g., "2025 Acme Inc.").

- **CODE_OF_CONDUCT.md** — Confirm use of Contributor Covenant v2.1 and how to handle contact (email, GitHub org, etc.).

- **CONTRIBUTING.md** — If no issue tracker exists, ask where bugs/features should be reported (GitHub Issues, Jira, etc.).

## Step 4: Present findings and get consent

1. Summarize what's **present** and what's **missing**.
2. Group missing items by priority (essential vs recommended).
3. For each missing item the user wants to add:
   - Resolve any ambiguity first (license, contact info, etc.).
   - Create the file using Keel scaffolding guidance (see Project Scaffolding rule) and language-specific rules.
   - Use correct copyright year and holder for LICENSE.

## Step 5: Adapt to the project

- Merge language-specific `.gitignore` patterns into a single `.gitignore` (see scaffolding.md and the matching language rule).
- Makefile targets should call real commands (e.g., `npm run build`, `go build`, `pytest`).
- CI workflow steps should match the project's actual lint/test/build commands.
- `.editorconfig` `indent_size` — use 2 for JS/TS/YAML, 4 for Python/Go by default; adjust if the project already has conventions.

## Important

- **Never create files without the user explicitly agreeing** to each file or batch of files.
- When the user says "add all" or "apply everything," still resolve license and copyright holder before creating LICENSE.
- If this is not a git repo, skip git-specific items (.gitignore, CONTRIBUTING, etc.) unless the user wants to prepare for future git adoption.
