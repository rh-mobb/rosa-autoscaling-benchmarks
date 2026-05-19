.PHONY: dev build export install

install:
	npm install

dev: install
	@echo "Starting Slidev dev server — opening browser at http://localhost:3030"
	npm run dev

build: install
	@echo "Building presentation…"
	npm run build
	@echo "Built to dist/"

export: install
	npm run export
