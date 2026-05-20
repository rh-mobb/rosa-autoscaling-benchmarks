# Contributing

Thank you for helping improve this ROSA autoscaling benchmark harness.

## Before you start

- Read **`README.md`** for prerequisites (`rosa`, `oc`, `aws`, `terraform`, optional Python venv).
- Never commit **secrets**, **`classic.env` / `hcp.env`**, kubeconfigs under **`tmp/`**, or Terraform state. Follow **`.gitignore`**.
- Benchmark flows that touch live clusters should stay aligned with **`.cursor/rules/local/rosa-benchmark-oc-cli.mdc`** and **`AGENTS.md`** (skills, deliverables, destructive-action caution).

## Development setup

```bash
make init-env          # creates classic.env / hcp.env from examples if missing
make setup             # prerequisite checks (adjust env files first)
make venv              # optional local Python env
make lint              # shellcheck + ruff
```

Slidev deck (optional):

```bash
cd presentation && npm ci && npm run dev
```

## Pull requests

- Keep changes focused and reviewable.
- Prefer **[Conventional Commits](https://www.conventionalcommits.org/)** for commit messages (`feat:`, `fix:`, `docs:`, `chore:`, etc.).
- Run **`make lint`** locally before pushing when you touch **`scripts/*.py`** or **`clusters/**/*.sh`** / **`machine-pools/**/*.sh`**.
- **Ruff** is configured in **`pyproject.toml`**. Rules **`RUF001`–`RUF003`** (ambiguous Unicode in strings, docstrings, and comments) are ignored so benchmark prose can use en dashes and ×; everything else in the selected rule set still applies.
- Update **`CHANGELOG.md`** under **`[Unreleased]`** when the change is user-visible (new benchmark, breaking Makefile behavior, doc fixes worth calling out).

## Code of Conduct

This project follows the **[Contributor Covenant](./CODE_OF_CONDUCT.md)**. Participation requires respectful collaboration.
