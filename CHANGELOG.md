# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
where versioning applies.

## [Unreleased]

### Added

- Open-source scaffolding: MIT license, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `.editorconfig`, CI lint workflow, Dependabot (GitHub Actions), issue/PR templates.
- Expanded `.gitignore` (Python caches, Terraform, Node, Slidev `dist/`, `*.pdf` slide exports).

### Changed

- **Ruff:** ignore `RUF001`–`RUF003` so benchmark narrative can use typographic dashes and ×; remaining rules enforced repo-wide so `make lint` passes in CI.
- **README:** document tests **05b**, **09b**, and **10–16**; expand benchmark skills table; describe **`hcp-autonode`** layout vs legacy **`hcp-karpenter`** notes.
