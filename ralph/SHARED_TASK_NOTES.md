# Shared Task Notes

Cross-iteration context for the continuous-claude loop.
Claude: read this at the start of each iteration, update it at the end.

## Codebase Patterns
- 74 roles under roles/; each has meta/main.yml with dependencies:[] and allow_duplicates: false
- Quality gate: `make validate-deps && make syntax-check`
- validate-deps checks for dependency cycles and missing role refs
- ansible-playbook --syntax-check warnings about empty inventory are harmless
- Dep format in meta/main.yml: `- role: role_name  # optional comment`
- The `systemd` role is handlers-only; only depend on it if you use its handlers
- `allow_duplicates: false` handles runtime dedup of diamond deps

## Completed Issues

## Issue #48: refactor: create group_vars/all/base.yml with all shared content
- Created `group_vars/all/` directory
- Created `group_vars/all/base.yml` with all shared content from both templates
- base.yml uses all.yml's current values (not template defaults) to avoid Ansible precedence conflicts
  (Ansible loads group_vars/all/*.yml AFTER group_vars/all.yml, so directory files take precedence)
- Machine-specific vars excluded from base.yml: `laptop`, `hostname`, `display_manager`, `desktop_environment`
- all.yml remains unchanged; both files loaded by Ansible with identical effective values
- `make validate-deps && make syntax-check` both pass
- [x] #48: refactor: create group_vars/all/base.yml with all shared content
