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

ANSIBLE_BIN    = $(shell ansible --version 2>&1 | head -1 | grep -q 'ansible 2' && command -v ansible)
BREW_BIN       = $(shell command -v brew 2>/dev/null)
GO_BIN         = $(shell command -v go 2>/dev/null)
LYNIS_BIN      = $(shell command -v lynis 2>/dev/null)
PYENV_BIN      = $(shell command -v pyenv 2>/dev/null)
PRE_COMMIT_BIN = $(shell pre-commit --version 2>&1 | head -1 | grep -q 'pre-commit [12]\.' && command -v pre-commit)
PYLINT_BIN     = $(shell pylint --version 2>&1 | head -1 | grep -q 'pylint 2' && command -v pylint)
SHELLCHECK_BIN = $(shell command -v shellcheck 2>/dev/null)
SHFMT_BIN      = $(shell command -v shfmt 2>/dev/null)


.PHONY: bootstrap
bootstrap: req-pip ## Install ansible (pip required)
	@echo 'Bootstraping your system for ansible'
	pip install ansible --user

.PHONY: install
install: req-galaxy ## Install roles via ansible-galaxy
	@echo 'Installing roles via ansible-galaxy'
	ansible-galaxy install -r requirements.yml -f

.PHONY: configure
configure: req-playbook ## Run ansible
	@echo 'Run ansible-playbook'
	ansible-playbook play.yml -K

.PHONY: all
all: bootstrap install configure ## Run all goals
	@echo 'Applying R1c3'

req-pip:
	@command -v pip >/dev/null 2>&1 || { echo >&2 "require pip"; exit 1; }

req-galaxy:
	@command -v ansible-galaxy >/dev/null 2>&1 || { echo >&2 "require ansible-galaxy"; exit 1; }

req-playbook:
	@command -v ansible-playbook >/dev/null 2>&1 || { echo >&2 "require ansible-playbook"; exit 1; }

.PHONY: help
help:  ## print this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort -d | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'