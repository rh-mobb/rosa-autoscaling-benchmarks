# ROSA Autoscaling Benchmark — Makefile
#
# This Makefile handles cluster lifecycle and prerequisite validation.
# Benchmark test scenarios are driven by Cursor Agent Skills in .cursor/skills/.
#
# Usage:
#   make init-env                     # create classic.env + hcp.env + autonode.env from *.example
#   make setup                        # validate auth and tool prerequisites
#   make create-classic               # provision ROSA Classic cluster
#   make create-hcp                   # provision ROSA HCP cluster (Terraform)
#   make create-hcp-autonode          # provision ROSA HCP + AutoNode/Karpenter (Private Preview)
#   make reconcile-hcp                # terraform apply only (recover partial HCP apply)
#   make destroy-classic              # destroy ROSA Classic cluster (prompts for confirmation)
#   make destroy-hcp                  # destroy ROSA HCP cluster (prompts for confirmation)
#   make destroy-hcp-autonode         # destroy ROSA HCP AutoNode cluster (prompts for confirmation)
#   make add-pool TYPE=standard CLUSTER=<name>   # add a machine pool
#   make lint                         # shellcheck + ruff all scripts

.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: init-env
init-env:
	@set -e; \
	for stem in classic hcp autonode; do \
	  if [[ -f "$$stem.env" ]]; then echo "  [skip]  $$stem.env (already exists)"; \
	  else cp "$$stem.env.example" "$$stem.env" && echo "  [new]   $$stem.env"; fi; \
	done
	@echo ""
	@echo "Edit *.env files, then run: make setup"

# Fixed env filenames (one ROSA Classic + one HCP + one AutoNode at a time in this harness).
# Run `make init-env` to copy from *.env.example when missing.
ROSA_CLUSTER_NAME_CLASSIC  ?= classic-bench
ROSA_CLUSTER_NAME_HCP      ?= hcp-bench
ROSA_CLUSTER_NAME_AUTONODE ?= autonode-bench
-include classic.env
-include hcp.env
-include autonode.env
export

# ── Shared defaults (used when not set in cluster *.env files) ────────────────
# Max 15 chars — ROSA Classic and HCP name validation enforces this.
AWS_REGION                ?= us-east-1
AUTOSCALE_MIN_REPLICAS    ?= 1
AUTOSCALE_MAX_REPLICAS    ?= 10
CLUSTER_ADMIN_PASSWORD    ?= Passw0rd12345!
# HCP benchmarks: see hcp.env.example (Terraform knobs)
ROSA_HCP_REPLICAS         ?= 2
# AutoNode: see autonode.env.example
AUTONODE_PREFIX           ?= autonode
AUTONODE_SHARD_ID         ?= 9f11dd2b-98c1-11f0-8fe5-0a580a830a08

# Valid machine pool types
VALID_TYPES := standard memory-optimized compute-optimized bare-metal

# ── Help ──────────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "ROSA Autoscaling Benchmark"
	@echo ""
	@echo "  Cluster lifecycle:"
	@echo "    make init-env                      Create classic.env + hcp.env + autonode.env from examples"
	@echo "    make setup                         Validate auth and tool prerequisites"
	@echo "    make create-classic                Provision ROSA Classic cluster"
	@echo "    make create-hcp                    Provision ROSA HCP cluster (Terraform)"
	@echo "    make create-hcp-autonode           Provision ROSA HCP + AutoNode/Karpenter (Private Preview)"
	@echo "    make reconcile-hcp                 Terraform full apply only (HCP recovery; same env as create)"
	@echo "      (oc uses per-cluster KUBECONFIG under tmp/kubeconfig.<cluster>.yaml — not ~/.kube/config)"
	@echo "    make destroy-classic               Destroy ROSA Classic cluster"
	@echo "    make destroy-hcp                   Destroy ROSA HCP cluster"
	@echo "    make destroy-hcp-autonode          Destroy ROSA HCP AutoNode cluster (drains Karpenter first)"
	@echo "    make cluster-create-lock-status      Show in-progress Classic / HCP / AutoNode create locks"
	@echo ""
	@echo "  Machine pools:"
	@echo "    make add-pool TYPE=<type> CLUSTER=<name>"
	@echo "      Types: standard | memory-optimized | compute-optimized | bare-metal"
	@echo "    make remove-pool NAME=<pool-name> CLUSTER=<name>"
	@echo "      Deletes a named machine pool and terminates its nodes"
	@echo ""
	@echo "  Deck:"
	@echo "    make deck                          Preview CAS vs AutoNode slide deck (http://localhost:3030)"
	@echo ""
	@echo "  Python environment:"
	@echo "    make venv                          Create .venv and install all dependencies"
	@echo ""
	@echo "  Quality:"
	@echo "    make lint                          Run shellcheck + ruff on all scripts"
	@echo "    make typecheck                     Run mypy type checking on Python scripts"
	@echo "    make test                          Run pytest with coverage"
	@echo ""
	@echo "  Benchmark results:"
	@echo "    make results                       List all benchmark runs"
	@echo "    make results-show RUN_ID=<id>      Show events for a specific run"
	@echo "    make results-summary RUN_ID=<id>   Print JSON summary for a run"
	@echo "    make reports-index                 Regenerate reports/index.html + reports/index-data.json"
	@echo "    make compare-report                Generate CAS vs AutoNode comparison HTML (auto-detects latest runs)"
	@echo "    make run-test-11 CLUSTER=<name> TYPE=<classic|hcp|hcp-autonode>   Planned surge (proactive scale-up)"
	@echo "    make run-test-12 CLUSTER=<name> TYPE=<classic|hcp|hcp-autonode>   Sudden spike (degradation window)"
	@echo "    make run-test-13 CLUSTER=<name> TYPE=<classic|hcp|hcp-autonode>   Multi-node parallel provisioning"
	@echo "    make run-test-15 CLUSTER=<name> TYPE=<classic|hcp-autonode>       Spot instance autoscaling"
	@echo "    make run-test-16 CLUSTER=<name> TYPE=<classic|hcp|hcp-autonode>  ARM64 (Graviton) node provisioning"
	@echo "    make results-clean                 Delete all result files"
	@echo ""
	@echo "  Benchmark skills (run from Cursor chat):"
	@echo "    benchmark-create-hcp-autonode      Provision HCP + AutoNode and record Canvas"
	@echo "    benchmark-cluster-install          Time cluster creation"
	@echo "    benchmark-machine-pool             Time machine pool provisioning"
	@echo "    benchmark-autoscale-up             Measure cluster scale-up"
	@echo "    benchmark-autoscale-down           Measure cluster scale-down"
	@echo "    benchmark-unschedulable            Oversize workload demo"
	@echo "    benchmark-hpa                      HPA response time"
	@echo "    benchmark-vpa-advise               VPA recommendations"
	@echo "    benchmark-hpa-triggers-cas         HPA → CAS end-to-end"
	@echo "    benchmark-overprovisioning         Faster HPA with pause pods"
	@echo "    benchmark-run-all                  All benchmarks + comparison Canvas"
	@echo ""

# ── Setup / Prerequisites ─────────────────────────────────────────────────────
.PHONY: setup
setup:
	@echo "==> Checking required tools..."
	@fail=0; \
	check_tool() { \
		local tool=$$1 ver_cmd=$$2; \
		if command -v $$tool &>/dev/null; then \
			echo "  [OK]      $$tool ($$($$ver_cmd 2>&1 | head -1))"; \
		else \
			echo "  [MISSING] $$tool — please install it before continuing"; \
			fail=1; \
		fi; \
	}; \
	check_tool rosa       "rosa version"; \
	check_tool terraform  "terraform version"; \
	check_tool oc        "oc version --client"; \
	check_tool aws       "aws --version"; \
	check_tool jq        "jq --version"; \
	check_tool python3   "python3 --version"; \
	check_tool shellcheck "shellcheck --version"; \
	if command -v ruff &>/dev/null; then \
		echo "  [OK]      ruff ($$(ruff --version 2>&1 | head -1))"; \
	elif [ -x .venv/bin/ruff ]; then \
		echo "  [OK]      ruff ($$(${PWD}/.venv/bin/ruff --version 2>&1 | head -1)) [via .venv]"; \
	else \
		echo "  [MISSING] ruff — run: make venv  (installs via .venv)"; \
		fail=1; \
	fi; \
	[ "$$fail" -eq 0 ] || exit 1
	@echo ""
	@echo "==> Checking ROSA authentication..."
	@if ! rosa whoami &>/dev/null; then \
		echo "  [ERROR] Not logged in to ROSA. Run: rosa login"; \
		exit 1; \
	fi
	@echo "  [OK]      rosa whoami ($$(rosa whoami --output json 2>/dev/null | jq -r '.username // "unknown"'))"
	@echo ""
	@echo "==> Checking AWS authentication..."
	@if ! aws sts get-caller-identity --region "$(AWS_REGION)" &>/dev/null; then \
		echo "  [ERROR] Not authenticated with AWS. Run: aws configure"; \
		exit 1; \
	fi
	@echo "  [OK]      aws ($$(aws sts get-caller-identity --region "$(AWS_REGION)" --query 'Account' --output text))"
	@echo ""
	@if [[ ! -f classic.env ]] || [[ ! -f hcp.env ]]; then \
	  echo "  [WARN]  Missing classic.env and/or hcp.env"; \
	  echo "          Run: make init-env"; \
	  echo ""; \
	fi
	@echo "==> All prerequisites satisfied."
	@echo ""

# ── ROSA Classic ──────────────────────────────────────────────────────────────
.PHONY: create-classic
create-classic: setup
	@echo "==> Creating ROSA Classic cluster: $(ROSA_CLUSTER_NAME_CLASSIC)"
	@AWS_REGION="$(AWS_REGION)" \
	 ROSA_CLUSTER_NAME="$(ROSA_CLUSTER_NAME_CLASSIC)" \
	 ROSA_VERSION="$(ROSA_VERSION)" \
	 CLUSTER_ADMIN_PASSWORD="$(CLUSTER_ADMIN_PASSWORD)" \
	 bash clusters/classic/create.sh

.PHONY: destroy-classic
destroy-classic:
	@echo ""
	@echo "WARNING: This will permanently destroy the ROSA Classic cluster:"
	@echo "         $(ROSA_CLUSTER_NAME_CLASSIC) in $(AWS_REGION)"
	@echo ""
	@if [ "$(ROSA_DESTROY_YES)" = "$(ROSA_CLUSTER_NAME_CLASSIC)" ]; then \
		echo "Confirmed via ROSA_DESTROY_YES — skipping interactive prompt."; \
	else \
		read -r -p "Type the cluster name to confirm: " confirm; \
		if [ "$$confirm" != "$(ROSA_CLUSTER_NAME_CLASSIC)" ]; then \
			echo "Confirmation did not match. Aborting."; \
			exit 1; \
		fi; \
	fi
	@ROSA_CLUSTER_NAME="$(ROSA_CLUSTER_NAME_CLASSIC)" \
	 bash clusters/classic/destroy.sh

# ── ROSA HCP ──────────────────────────────────────────────────────────────────
.PHONY: create-hcp
create-hcp: setup
	@echo "==> Creating ROSA HCP cluster: $(ROSA_CLUSTER_NAME_HCP)"
	@AWS_REGION="$(AWS_REGION)" \
	 ROSA_CLUSTER_NAME="$(ROSA_CLUSTER_NAME_HCP)" \
	 ROSA_VERSION="$(ROSA_VERSION)" \
	 CLUSTER_ADMIN_PASSWORD="$(CLUSTER_ADMIN_PASSWORD)" \
	 AUTOSCALE_MAX_REPLICAS="$(AUTOSCALE_MAX_REPLICAS)" \
	 ROSA_HCP_NETWORK_VPC_CIDR="$(ROSA_HCP_NETWORK_VPC_CIDR)" \
	 ROSA_HCP_REPLICAS="$(ROSA_HCP_REPLICAS)" \
	 ROSA_HCP_MULTI_AZ="$(ROSA_HCP_MULTI_AZ)" \
	 ROSA_HCP_TERRAFORM_VAR_FILE="$(ROSA_HCP_TERRAFORM_VAR_FILE)" \
	 ROSA_HCP_INSTANCE_TYPE="$(ROSA_HCP_INSTANCE_TYPE)" \
	 ROSA_HCP_TERRAFORM_403_MAX_RETRIES="$(ROSA_HCP_TERRAFORM_403_MAX_RETRIES)" \
	 ROSA_HCP_TERRAFORM_403_RETRY_SLEEP_SEC="$(ROSA_HCP_TERRAFORM_403_RETRY_SLEEP_SEC)" \
	 bash clusters/hcp/create.sh

.PHONY: reconcile-hcp
reconcile-hcp: setup
	@echo "==> HCP Terraform reconcile (full apply): $(ROSA_CLUSTER_NAME_HCP)"
	@AWS_REGION="$(AWS_REGION)" \
	 ROSA_CLUSTER_NAME="$(ROSA_CLUSTER_NAME_HCP)" \
	 ROSA_VERSION="$(ROSA_VERSION)" \
	 CLUSTER_ADMIN_PASSWORD="$(CLUSTER_ADMIN_PASSWORD)" \
	 AUTOSCALE_MAX_REPLICAS="$(AUTOSCALE_MAX_REPLICAS)" \
	 ROSA_HCP_NETWORK_VPC_CIDR="$(ROSA_HCP_NETWORK_VPC_CIDR)" \
	 ROSA_HCP_REPLICAS="$(ROSA_HCP_REPLICAS)" \
	 ROSA_HCP_MULTI_AZ="$(ROSA_HCP_MULTI_AZ)" \
	 ROSA_HCP_TERRAFORM_VAR_FILE="$(ROSA_HCP_TERRAFORM_VAR_FILE)" \
	 ROSA_HCP_INSTANCE_TYPE="$(ROSA_HCP_INSTANCE_TYPE)" \
	 ROSA_HCP_MAX_POOL_REPLICAS="$(ROSA_HCP_MAX_POOL_REPLICAS)" \
	 ROSA_HCP_TERRAFORM_403_MAX_RETRIES="$(ROSA_HCP_TERRAFORM_403_MAX_RETRIES)" \
	 ROSA_HCP_TERRAFORM_403_RETRY_SLEEP_SEC="$(ROSA_HCP_TERRAFORM_403_RETRY_SLEEP_SEC)" \
	 bash clusters/hcp/reconcile.sh

.PHONY: destroy-hcp
destroy-hcp:
	@echo ""
	@echo "WARNING: This will permanently destroy the ROSA HCP cluster:"
	@echo "         $(ROSA_CLUSTER_NAME_HCP) in $(AWS_REGION)"
	@echo ""
	@if [ "$(ROSA_DESTROY_YES)" = "$(ROSA_CLUSTER_NAME_HCP)" ]; then \
		echo "Confirmed via ROSA_DESTROY_YES — skipping interactive prompt."; \
	else \
		read -r -p "Type the cluster name to confirm: " confirm; \
		if [ "$$confirm" != "$(ROSA_CLUSTER_NAME_HCP)" ]; then \
			echo "Confirmation did not match. Aborting."; \
			exit 1; \
		fi; \
	fi
	@AWS_REGION="$(AWS_REGION)" \
	 ROSA_CLUSTER_NAME="$(ROSA_CLUSTER_NAME_HCP)" \
	 CLUSTER_ADMIN_PASSWORD="$(CLUSTER_ADMIN_PASSWORD)" \
	 ROSA_HCP_TERRAFORM_VAR_FILE="$(ROSA_HCP_TERRAFORM_VAR_FILE)" \
	 ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH="$(ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH)" \
	 bash clusters/hcp/destroy.sh

# ── ROSA HCP AutoNode ─────────────────────────────────────────────────────────
.PHONY: create-hcp-autonode
create-hcp-autonode: setup
	@echo "==> Creating ROSA HCP AutoNode cluster: $(ROSA_CLUSTER_NAME_AUTONODE)"
	@AWS_REGION="$(AWS_REGION)" \
	 ROSA_CLUSTER_NAME="$(ROSA_CLUSTER_NAME_AUTONODE)" \
	 ROSA_VERSION="$(ROSA_VERSION)" \
	 CLUSTER_ADMIN_PASSWORD="$(CLUSTER_ADMIN_PASSWORD)" \
	 AUTOSCALE_MAX_REPLICAS="$(AUTOSCALE_MAX_REPLICAS)" \
	 ROSA_HCP_NETWORK_VPC_CIDR="$(ROSA_HCP_NETWORK_VPC_CIDR)" \
	 ROSA_HCP_REPLICAS="$(ROSA_HCP_REPLICAS)" \
	 ROSA_HCP_MULTI_AZ="$(ROSA_HCP_MULTI_AZ)" \
	 ROSA_HCP_TERRAFORM_VAR_FILE="$(ROSA_HCP_TERRAFORM_VAR_FILE)" \
	 ROSA_HCP_INSTANCE_TYPE="$(ROSA_HCP_INSTANCE_TYPE)" \
	 ROSA_HCP_TERRAFORM_403_MAX_RETRIES="$(ROSA_HCP_TERRAFORM_403_MAX_RETRIES)" \
	 ROSA_HCP_TERRAFORM_403_RETRY_SLEEP_SEC="$(ROSA_HCP_TERRAFORM_403_RETRY_SLEEP_SEC)" \
	 AUTONODE_PREFIX="$(AUTONODE_PREFIX)" \
	 AUTONODE_SHARD_ID="$(AUTONODE_SHARD_ID)" \
	 bash clusters/hcp-autonode/create.sh

.PHONY: destroy-hcp-autonode
destroy-hcp-autonode:
	@echo ""
	@echo "WARNING: This will permanently destroy the ROSA HCP AutoNode cluster:"
	@echo "         $(ROSA_CLUSTER_NAME_AUTONODE) in $(AWS_REGION)"
	@echo ""
	@if [ "$(ROSA_DESTROY_YES)" = "$(ROSA_CLUSTER_NAME_AUTONODE)" ]; then \
		echo "Confirmed via ROSA_DESTROY_YES — skipping interactive prompt."; \
	else \
		read -r -p "Type the cluster name to confirm: " confirm; \
		if [ "$$confirm" != "$(ROSA_CLUSTER_NAME_AUTONODE)" ]; then \
			echo "Confirmation did not match. Aborting."; \
			exit 1; \
		fi; \
	fi
	@AWS_REGION="$(AWS_REGION)" \
	 ROSA_CLUSTER_NAME="$(ROSA_CLUSTER_NAME_AUTONODE)" \
	 CLUSTER_ADMIN_PASSWORD="$(CLUSTER_ADMIN_PASSWORD)" \
	 ROSA_HCP_TERRAFORM_VAR_FILE="$(ROSA_HCP_TERRAFORM_VAR_FILE)" \
	 ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH="$(ROSA_HCP_TERRAFORM_DESTROY_NO_REFRESH)" \
	 bash clusters/hcp-autonode/destroy.sh

# ── Cluster create locks (mkdir under tmp/; create scripts enforce per-type mutex)
.PHONY: cluster-create-lock-status
cluster-create-lock-status:
	@if [[ -d tmp/cluster-create-classic.lock ]]; then \
	  echo "ROSA Classic create lock: HELD"; \
	  echo "  pid:     $$(cat tmp/cluster-create-classic.lock/pid 2>/dev/null || echo '?')"; \
	  echo "  cluster: $$(cat tmp/cluster-create-classic.lock/cluster 2>/dev/null || echo '?')"; \
	  echo "  started: $$(cat tmp/cluster-create-classic.lock/started 2>/dev/null || echo '?') (epoch UTC)"; \
	  echo ""; \
	else \
	  echo "ROSA Classic create lock: free"; \
	  echo ""; \
	fi
	@if [[ -d tmp/cluster-create-hcp.lock ]]; then \
	  echo "ROSA HCP create lock: HELD"; \
	  echo "  pid:     $$(cat tmp/cluster-create-hcp.lock/pid 2>/dev/null || echo '?')"; \
	  echo "  cluster: $$(cat tmp/cluster-create-hcp.lock/cluster 2>/dev/null || echo '?')"; \
	  echo "  started: $$(cat tmp/cluster-create-hcp.lock/started 2>/dev/null || echo '?') (epoch UTC)"; \
	else \
	  echo "ROSA HCP create lock: free"; \
	fi
	@echo ""
	@if [[ -d tmp/cluster-create-hcp-autonode.lock ]]; then \
	  echo "ROSA HCP AutoNode create lock: HELD"; \
	  echo "  pid:     $$(cat tmp/cluster-create-hcp-autonode.lock/pid 2>/dev/null || echo '?')"; \
	  echo "  cluster: $$(cat tmp/cluster-create-hcp-autonode.lock/cluster 2>/dev/null || echo '?')"; \
	  echo "  started: $$(cat tmp/cluster-create-hcp-autonode.lock/started 2>/dev/null || echo '?') (epoch UTC)"; \
	else \
	  echo "ROSA HCP AutoNode create lock: free"; \
	fi

# ── Machine Pools ─────────────────────────────────────────────────────────────
.PHONY: add-pool
add-pool:
	@if [ -z "$(TYPE)" ]; then \
		echo "Error: TYPE is required. Valid values: $(VALID_TYPES)"; \
		exit 1; \
	fi
	@if [ -z "$(CLUSTER)" ]; then \
		echo "Error: CLUSTER is required. E.g.: make add-pool TYPE=standard CLUSTER=$(ROSA_CLUSTER_NAME_CLASSIC)"; \
		exit 1; \
	fi
	@case "$(TYPE)" in \
		standard)          script="machine-pools/add-standard.sh" ;; \
		memory-optimized)  script="machine-pools/add-memory-optimized.sh" ;; \
		compute-optimized) script="machine-pools/add-compute-optimized.sh" ;; \
		bare-metal)        script="machine-pools/add-bare-metal.sh" ;; \
		*) echo "Error: unknown TYPE '$(TYPE)'. Valid: $(VALID_TYPES)"; exit 1 ;; \
	esac; \
	ROSA_CLUSTER_NAME="$(CLUSTER)" \
	AUTOSCALE_MIN_REPLICAS="$(AUTOSCALE_MIN_REPLICAS)" \
	AUTOSCALE_MAX_REPLICAS="$(AUTOSCALE_MAX_REPLICAS)" \
	AWS_REGION="$(AWS_REGION)" \
	bash "$$script"

.PHONY: remove-pool
remove-pool:
	@if [ -z "$(NAME)" ]; then \
		echo "Error: NAME is required. E.g.: make remove-pool NAME=bench-standard CLUSTER=$(ROSA_CLUSTER_NAME_CLASSIC)"; \
		exit 1; \
	fi
	@if [ -z "$(CLUSTER)" ]; then \
		echo "Error: CLUSTER is required. E.g.: make remove-pool NAME=bench-standard CLUSTER=$(ROSA_CLUSTER_NAME_CLASSIC)"; \
		exit 1; \
	fi
	ROSA_CLUSTER_NAME="$(CLUSTER)" \
	AWS_REGION="$(AWS_REGION)" \
	bash machine-pools/delete.sh "$(NAME)"

# ── Linting ───────────────────────────────────────────────────────────────────
.PHONY: lint
lint: lint-shell lint-python

.PHONY: lint-shell
lint-shell:
	@echo "==> shellcheck (bash scripts)"
	@find clusters machine-pools -type f -name '*.sh' ! -path '*/.terraform/*' | sort | while read -r f; do \
		shellcheck -x "$$f" && echo "  [OK] $$f" || exit 1; \
	done
	@echo ""

.PHONY: lint-python
lint-python:
	@echo "==> ruff (python scripts)"
	@if [ -x .venv/bin/ruff ]; then RUFF=.venv/bin/ruff; else RUFF=ruff; fi; \
	find scripts -name '*.py' | sort | while read -r f; do \
		$$RUFF check "$$f" && echo "  [OK] $$f" || exit 1; \
	done
	@echo ""

.PHONY: typecheck
typecheck:
	@echo "==> mypy (python scripts)"
	@if [ -x .venv/bin/mypy ]; then MYPY=.venv/bin/mypy; else MYPY=mypy; fi; \
	find scripts -name '*.py' | sort | while read -r f; do \
		$$MYPY "$$f" && echo "  [OK] $$f" || exit 1; \
	done
	@echo ""

.PHONY: test
test:
	@echo "==> pytest"
	@if [ -x .venv/bin/pytest ]; then \
		.venv/bin/pytest --cov=scripts --cov-report=term-missing; \
	else \
		pytest --cov=scripts --cov-report=term-missing; \
	fi
	@echo ""

# ── Benchmark results ─────────────────────────────────────────────────────────
.PHONY: results
results:
	@python3 scripts/record-event.py ls

.PHONY: results-show
results-show:
	@if [ -z "$(RUN_ID)" ]; then \
		echo "Error: RUN_ID is required. E.g.: make results-show RUN_ID=20260501T001423-classic"; \
		exit 1; \
	fi
	@python3 scripts/record-event.py list --run-id "$(RUN_ID)"

.PHONY: results-summary
results-summary:
	@if [ -z "$(RUN_ID)" ]; then \
		echo "Error: RUN_ID is required. E.g.: make results-summary RUN_ID=20260501T001423-classic"; \
		exit 1; \
	fi
	@python3 scripts/record-event.py summary --run-id "$(RUN_ID)"

.PHONY: results-checkpoint
results-checkpoint:
	@if [ -z "$(RUN_ID)" ]; then \
		echo "Error: RUN_ID is required."; \
		exit 1; \
	fi
	@python3 scripts/checkpoint.py status --run-id "$(RUN_ID)"

.PHONY: results-clean
results-clean:
	@echo "WARNING: This will delete ALL benchmark result files in results/."
	@read -r -p "Confirm? [y/N] " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		rm -rf results/*/; \
		echo "Results cleared."; \
	else \
		echo "Aborted."; \
	fi

.PHONY: reports-index
reports-index:
	@python3 scripts/update-reports-index.py

.PHONY: compare-report
compare-report:
	@python3 scripts/generate-comparison-report.py --auto

# ── Retail scenario benchmarks (Tests 11–13) ──────────────────────────────────
.PHONY: run-test-11
run-test-11:
	@if [ -z "$(CLUSTER)" ] || [ -z "$(TYPE)" ]; then \
		echo "Error: CLUSTER and TYPE are required."; \
		echo "  make run-test-11 CLUSTER=<name> TYPE=<classic|hcp|hcp-autonode>"; \
		exit 1; \
	fi
	@python3 scripts/run-test-11-planned-surge.py \
		--cluster-name "$(CLUSTER)" \
		--cluster-type "$(TYPE)" \
		$(if $(RUN_ID),--run-id "$(RUN_ID)") \
		$(if $(STRATEGY),--strategy "$(STRATEGY)") \
		$(if $(BALLOON_REPLICAS),--balloon-replicas "$(BALLOON_REPLICAS)") \
		$(if $(PREWARM_NODES),--prewarm-nodes "$(PREWARM_NODES)") \
		$(if $(NODEPOOL_NAME),--nodepool-name "$(NODEPOOL_NAME)")

.PHONY: run-test-12
run-test-12:
	@if [ -z "$(CLUSTER)" ] || [ -z "$(TYPE)" ]; then \
		echo "Error: CLUSTER and TYPE are required."; \
		echo "  make run-test-12 CLUSTER=<name> TYPE=<classic|hcp|hcp-autonode>"; \
		exit 1; \
	fi
	@python3 scripts/run-test-12-sudden-spike.py \
		--cluster-name "$(CLUSTER)" \
		--cluster-type "$(TYPE)" \
		$(if $(RUN_ID),--run-id "$(RUN_ID)") \
		$(if $(TARGET_REPLICAS),--target-replicas "$(TARGET_REPLICAS)") \
		$(if $(BALLOON_REPLICAS),--balloon-replicas "$(BALLOON_REPLICAS)") \
		$(if $(NODEPOOL_NAME),--nodepool-name "$(NODEPOOL_NAME)")

.PHONY: run-test-13
run-test-13:
	@if [ -z "$(CLUSTER)" ] || [ -z "$(TYPE)" ]; then \
		echo "Error: CLUSTER and TYPE are required."; \
		echo "  make run-test-13 CLUSTER=<name> TYPE=<classic|hcp|hcp-autonode>"; \
		exit 1; \
	fi
	@python3 scripts/run-test-13-parallel-nodes.py \
		--cluster-name "$(CLUSTER)" \
		--cluster-type "$(TYPE)" \
		$(if $(RUN_ID),--run-id "$(RUN_ID)") \
		$(if $(NODE_COUNT),--node-count "$(NODE_COUNT)") \
		$(if $(NODEPOOL_NAME),--nodepool-name "$(NODEPOOL_NAME)")

.PHONY: run-test-15
run-test-15:
	@if [ -z "$(CLUSTER)" ] || [ -z "$(TYPE)" ]; then \
		echo "Error: CLUSTER and TYPE are required."; \
		echo "  make run-test-15 CLUSTER=<name> TYPE=<classic|hcp-autonode>"; \
		exit 1; \
	fi
	@python3 scripts/run-test-15-spot-instances.py \
		--cluster-name "$(CLUSTER)" \
		--cluster-type "$(TYPE)" \
		$(if $(RUN_ID),--run-id "$(RUN_ID)") \
		$(if $(NODEPOOL_NAME),--nodepool-name "$(NODEPOOL_NAME)") \
		$(if $(SPOT_MAX_PRICE),--spot-max-price "$(SPOT_MAX_PRICE)")

.PHONY: run-test-16
run-test-16:
	@if [ -z "$(CLUSTER)" ] || [ -z "$(TYPE)" ]; then \
		echo "Error: CLUSTER and TYPE are required."; \
		echo "  make run-test-16 CLUSTER=<name> TYPE=<classic|hcp|hcp-autonode>"; \
		exit 1; \
	fi
	@python3 scripts/run-test-16-arm-nodes.py \
		--cluster-name "$(CLUSTER)" \
		--cluster-type "$(TYPE)" \
		$(if $(RUN_ID),--run-id "$(RUN_ID)") \
		$(if $(NODEPOOL_NAME),--nodepool-name "$(NODEPOOL_NAME)")

# ── Slide deck ────────────────────────────────────────────────────────────────
.PHONY: deck
deck:
	@echo "==> Starting CAS vs AutoNode slide deck at http://localhost:3030"
	$(MAKE) -C reports/classic-vs-hcp_autonode dev

# ── Python virtualenv ─────────────────────────────────────────────────────────
.PHONY: venv
venv:
	@echo "==> Creating Python virtualenv in .venv/"
	@python3 -m venv .venv
	@.venv/bin/pip install --upgrade pip -q
	@.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
	@echo ""
	@echo "Activate with: source .venv/bin/activate"
	@echo ""
