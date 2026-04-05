# Makefile for https://github.com/floatingman/my-configuration
#
# Self-documented help from:
# https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html

###
# Makefile configuration
###


.DEFAULT_GOAL := help

# Make output silent by default, use VERBOSE=1 make <command> ...
# to get verbose output.
ifndef VERBOSE
.SILENT:
endif

###
# Define environment variables in the beginning of the file
###

UNAME_S  := $(shell uname -s)

# Use pipx-managed ansible python if available; fall back to system python3
PIPX_VENVS    := $(shell pipx environment 2>/dev/null | grep -o 'PIPX_LOCAL_VENVS=[^[:space:]]*' | cut -d= -f2)
SCRIPT_PYTHON := $(or $(wildcard $(PIPX_VENVS)/ansible/bin/python3),python3)

ANSIBLE_BIN      = $(shell ansible --version 2>&1 | head -1 | grep -q 'ansible 2' && command -v ansible)
ANSIBLE_LINT_BIN = $(shell command -v ansible-lint 2>/dev/null)
YAMLLINT_BIN     = $(shell command -v yamllint 2>/dev/null)
BREW_BIN       = $(shell command -v brew 2>/dev/null)
GO_BIN         = $(shell command -v go 2>/dev/null)
LYNIS_BIN      = $(shell command -v lynis 2>/dev/null)
PRE_COMMIT_BIN = $(shell pre-commit --version 2>&1 | head -1 | grep -q 'pre-commit [12]\.' && command -v pre-commit)
PYLINT_BIN     = $(shell pylint --version 2>&1 | head -1 | grep -q 'pylint 2' && command -v pylint)
SHELLCHECK_BIN = $(shell command -v shellcheck 2>/dev/null)
SHFMT_BIN      = $(shell command -v shfmt 2>/dev/null)


.PHONY: test
test: lint syntax-check validate-profiles check-sync ## Run all tests (lint + syntax check + profile validation + sync check)

.PHONY: lint
lint: ## Run yamllint and ansible-lint
ifdef YAMLLINT_BIN
	@echo 'Running yamllint...'
	yamllint .
else
	@echo 'Warning: yamllint not found, skipping'
endif
ifdef ANSIBLE_LINT_BIN
	@echo 'Running ansible-lint...'
	ansible-lint play.yml
else
	@echo 'Warning: ansible-lint not found, skipping'
endif

.PHONY: syntax-check
syntax-check: req-playbook ## Check playbook syntax
	@echo 'Checking playbook syntax...'
	ansible-playbook --syntax-check play.yml

.PHONY: bootstrap
bootstrap: req-pipx ## Install ansible (pipx required)
	@echo 'Bootstraping your system for ansible'
	pipx install --include-deps ansible

.PHONY: install
install: req-galaxy ## Install roles via ansible-galaxy
	@echo 'Installing roles via ansible-galaxy'
	ansible-galaxy install -r requirements.yml -f
	ansible-galaxy collection install -r requirements.yml

.PHONY: configure
configure: req-playbook validate-deps ## Run ansible (optionally with TAGS="tag1,tag2")
	@echo 'Run ansible-playbook'
ifdef TAGS
	@available_tags=$$(grep -oP 'tags: \["\K[^"]+' play.yml | sort -u); \
	invalid_tags=""; \
	for tag in $$(echo "$(TAGS)" | tr ',' ' '); do \
		if ! echo "$$available_tags" | grep -qx "$$tag"; then \
			invalid_tags="$$invalid_tags $$tag"; \
		fi; \
	done; \
	if [ -n "$$invalid_tags" ]; then \
		echo "Error: The following tag(s) do not exist:$$invalid_tags"; \
		echo ""; \
		echo "Available tags:"; \
		echo "$$available_tags" | sed 's/^/  - /'; \
		echo ""; \
		echo "Run 'make list-tags' to see all available tags."; \
		exit 1; \
	fi
	ansible-playbook -i localhost play.yml --ask-become-pass --tags "$(TAGS)"
else
	ansible-playbook -i localhost play.yml --ask-become-pass
endif

.PHONY: pip-deps
pip-deps: ## Ensure pyyaml is available (injects into pipx ansible environment)
	@$(SCRIPT_PYTHON) -c "import yaml" 2>/dev/null || pipx inject ansible pyyaml

.PHONY: validate-deps
validate-deps: pip-deps ## Validate role dependency graph (no cycles, no missing roles)
	@echo 'Validating role dependency graph...'
	$(SCRIPT_PYTHON) scripts/validate_deps.py

.PHONY: check-sync
check-sync: pip-deps ## Check play.yml sync with profile definitions (CI gate)
	@echo 'Checking play.yml sync with profile definitions...'
	@$(SCRIPT_PYTHON) scripts/profile_dispatcher.py sync-playbook --check

.PHONY: sync-playbook
sync-playbook: pip-deps ## Show drift between play.yml and profile definitions
	@echo 'Checking play.yml sync with profile definitions...'
	@$(SCRIPT_PYTHON) scripts/profile_dispatcher.py sync-playbook

.PHONY: list-tags
list-tags: ## List all available tags in the playbook
	@echo 'Available tags:'
	@grep -oP 'tags: \["\K[^"]+' play.yml | sort -u | sed 's/^/  - /'

.PHONY: list-profiles
list-profiles: pip-deps ## List all available configuration profiles
	@if ! $(SCRIPT_PYTHON) $(CURDIR)/scripts/profile_dispatcher.py list-profiles --format pretty; then \
		echo '  (Run make configure to set up profile dispatcher)'; \
		exit 1; \
	fi
	@echo ''
	@echo 'Usage: make profile-<name>  (e.g. make profile-i3)'
	@echo 'Add TAGS="tag1,tag2" to run specific roles within a profile'

# ---------------------------------------------------------------------------
# Dynamic profile targets
# ---------------------------------------------------------------------------

# Get list of valid profile names from available profile files (no Python dependency)
PROFILES := $(basename $(notdir $(wildcard profiles/*.yml)))

# Template for generating profile targets
# Usage: $(call profile_target,<name>)
define profile_target
.PHONY: profile-$(1)
profile-$(1): req-playbook pip-deps ## Run $(1) profile
	@echo 'Configuring $(1) profile'
	@set -e; \
		ARGS="$$($(SCRIPT_PYTHON) $(CURDIR)/scripts/profile_dispatcher.py make-args --profile $(1) 2>/dev/null)" || \
		{ echo "Error: Unknown profile '$(1)'" >&2; \
		  echo "" >&2; \
		  echo "Available profiles: $$(echo "$(PROFILES)" | sed 's/ /, /g')" >&2; \
		  exit 1; }; \
		ansible-playbook -i localhost play.yml --ask-become-pass $$$$ARGS
endef

# Generate a target for each profile
$(foreach profile,$(PROFILES),$(eval $(call profile_target,$(profile))))

# Catch-all profile target for unknown profiles (gives a helpful error)
.PHONY: profile-%
profile-%: req-playbook pip-deps ## Run arbitrary profile (with validation)
	@echo 'Configuring $* profile'
	@ARGS="$$($(SCRIPT_PYTHON) $(CURDIR)/scripts/profile_dispatcher.py make-args --profile $* 2>/dev/null)" || \
		{ echo "Error: Unknown profile '$*'" >&2; \
		  echo "" >&2; \
		  echo "Available profiles: $$(echo "$(PROFILES)" | sed 's/ /, /g')" >&2; \
		  exit 1; }; \
	ansible-playbook -i localhost play.yml --ask-become-pass $$ARGS

.PHONY: validate-profiles
validate-profiles: pip-deps check-sync ## Validate all profiles for correctness and check play.yml sync
	@echo 'Validating profiles...'
	@$(SCRIPT_PYTHON) $(CURDIR)/scripts/profile_dispatcher.py validate

.PHONY: all
all: install configure ## Run all goals
	@echo 'Applying R1c3'

req-pipx:
	@command -v pipx >/dev/null 2>&1 || { echo >&2 "require pipx"; exit 1; }

req-galaxy:
	@command -v ansible-galaxy >/dev/null 2>&1 || { echo >&2 "require ansible-galaxy"; exit 1; }

req-playbook:
	@command -v ansible-playbook >/dev/null 2>&1 || { echo >&2 "require ansible-playbook"; exit 1; }

req-lspci:
	@command -v lspci >/dev/null 2>&1 || { echo >&2 "require lspci (pciutils package)"; exit 1; }

.PHONY: gpu-info
gpu-info: req-lspci ## Display detected GPU information
	@echo 'Detected GPUs:'
	@lspci | grep -E "(VGA|3D|Display)" | sed 's/^[0-9a-f]*:[0-9a-f]*.[0-9a-f]* /  - /'

.PHONY: help
help:  ## print this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort -d | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Profile targets (generated from profiles/):"
	@for profile in $$($(SCRIPT_PYTHON) $(CURDIR)/scripts/profile_dispatcher.py list-profiles --format names 2>/dev/null); do \
		printf "\033[36m%-30s\033[0m Run $$profile profile\n" "profile-$$profile"; \
	done || true
