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
