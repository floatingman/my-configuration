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
test: lint syntax-check check-sync ## Run all tests (lint + syntax check + sync check)

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

.PHONY: validate-profiles
validate-profiles: pip-deps check-sync ## Validate all profiles and sync check
	@echo 'Validating profiles...'
	$(SCRIPT_PYTHON) scripts/profile_dispatcher.py validate

.PHONY: sync-playbook
sync-playbook: pip-deps ## Show drift between profiles and play.yml
	@$(SCRIPT_PYTHON) scripts/profile_dispatcher.py sync-playbook

.PHONY: check-sync
check-sync: pip-deps ## Check if play.yml is in sync with profiles (CI gate)
	@$(SCRIPT_PYTHON) scripts/profile_dispatcher.py sync-playbook --check

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

.PHONY: list-tags
list-tags: ## List all available tags in the playbook
	@echo 'Available tags:'
	@grep -oP 'tags: \["\K[^"]+' play.yml | sort -u | sed 's/^/  - /'

.PHONY: list-profiles
list-profiles: ## List all available configuration profiles
	@echo 'Available profiles:'
	@echo '  headless   - CLI-only, no display manager or desktop environment'
	@echo '  i3         - i3 window manager with lightdm display manager'
	@echo '  hyprland   - Hyprland Wayland compositor with sddm display manager'
	@echo '  gnome      - GNOME desktop environment with gdm display manager'
	@echo '  awesomewm  - AwesomeWM tiling window manager with lightdm display manager'
	@echo '  kde        - KDE Plasma desktop with sddm display manager'
	@echo ''
	@echo 'Usage: make profile-<name>  (e.g. make profile-i3)'
	@echo 'Add TAGS="tag1,tag2" to run specific roles within a profile'

.PHONY: profile-headless
profile-headless: req-playbook ## Run headless profile (CLI-only, no display)
	@echo 'Configuring headless profile (no display manager)'
	ansible-playbook -i localhost play.yml --ask-become-pass \
		-e "profile=headless"

.PHONY: profile-i3
profile-i3: req-playbook ## Run i3 window manager profile
	@echo 'Configuring i3 window manager profile'
	ansible-playbook -i localhost play.yml --ask-become-pass \
		-e "desktop_environment=i3 display_manager=lightdm profile=i3"

.PHONY: profile-hyprland
profile-hyprland: req-playbook ## Run Hyprland Wayland compositor profile
	@echo 'Configuring Hyprland Wayland compositor profile'
	ansible-playbook -i localhost play.yml --ask-become-pass \
		-e "desktop_environment=hyprland display_manager=sddm profile=hyprland"

.PHONY: profile-gnome
profile-gnome: req-playbook ## Run GNOME desktop environment profile
	@echo 'Configuring GNOME desktop environment profile'
	ansible-playbook -i localhost play.yml --ask-become-pass \
		-e "desktop_environment=gnome display_manager=gdm profile=gnome"

.PHONY: profile-awesomewm
profile-awesomewm: req-playbook ## Run AwesomeWM tiling window manager profile
	@echo 'Configuring AwesomeWM tiling window manager profile'
	ansible-playbook -i localhost play.yml --ask-become-pass \
		-e "desktop_environment=awesomewm display_manager=lightdm profile=awesomewm"

.PHONY: profile-kde
profile-kde: req-playbook ## Run KDE Plasma desktop profile
	@echo 'Configuring KDE Plasma desktop profile'
	ansible-playbook -i localhost play.yml --ask-become-pass \
		-e "desktop_environment=kde display_manager=sddm profile=kde"

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

PHONY: help
help:  ## print this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort -d | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
