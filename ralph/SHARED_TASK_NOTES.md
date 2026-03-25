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
- [x] #49: refactor: extract machine-specific scalars to group_vars/all/local.yml
- [x] #50: docs: write desktop and server templates for local.yml (no changes needed)
- [x] #51: chore: remove legacy group_vars files and update setup docs
- [x] #56: refactor: add defaults/main.yml to laptop, backlight, ssh, grub, networkmanager roles
- [x] #57: docs: document role defaults convention in CLAUDE.md (no changes needed)
- [x] #58: docs: complete desktop and server templates with missing configurable variables
