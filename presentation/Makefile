.PHONY: dev build export install pdf help

help:
	@echo "Targets:"
	@echo "  install   Install npm dependencies"
	@echo "  dev       Start live-reload dev server (http://localhost:3030)"
	@echo "  build     Build static site to dist/"
	@echo "  pdf       Export slides to slides-export.pdf (installs Chromium if needed)"
	@echo "  export    Alias for pdf"

install:
	npm install

dev: install
	@echo "Starting Slidev dev server — opening browser at http://localhost:3030"
	npm run dev

build: install
	@echo "Building presentation…"
	npm run build
	@echo "Built to dist/"

pdf: install
	@echo "Installing Playwright Chromium (no-op if already installed)…"
	npx playwright install chromium
	@echo "Exporting slides to slides-export.pdf…"
	npm run export -- --format pdf --output slides-export.pdf
	@echo "Done → slides-export.pdf"

export: pdf
