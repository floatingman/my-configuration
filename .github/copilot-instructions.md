# Copilot Instructions

**Read `AGENTS.md` at the repository root first** — it is the canonical, fully verified guidance for this repository (commands, architecture, conventions, workflows). This file only inlines the critical rules; everything else lives in `AGENTS.md`.

## Critical rules (mirror of AGENTS.md)

1. **Never edit `play.yml` by hand.** It is auto-generated from `profiles/`. Edit the profile definition, then run `make generate-playbook` and commit the regenerated `play.yml` together with the profile change. CI fails on drift (`make check-sync`).
2. **`profiles/` is the single source of truth** for which roles run and under what conditions — via annotations (`os`, `requires_display`, `config_check`, `requires_config`), not hand-written `when:` clauses.
3. **Every role has a tag** matching the role name.
4. **In `play.yml`, `when:` clauses use only pre-resolved facts** set by `pre_tasks`: `_is_arch`, `_has_display`, `_is_i3`, `_is_hyprland`, `_is_gnome`, `_is_awesomewm`, `_is_kde`, `_overlay_*`. Never raw `ansible_os_family`/`ansible_distribution`.
5. **Every variable a role reads must have an entry in that role's `defaults/main.yml`.** Optional ⇒ `null`, never omitted. Machine-specific variables also get commented examples in **both** `group_vars/templates/desktop.yml` and `group_vars/templates/server.yml`.
6. **Never run the playbook as root.** Per-task `become: true`; the Makefile passes `--ask-become-pass`.
7. **Idempotency required** — `command`/`shell` tasks need `creates:` or `changed_when:` guards.
8. **No plaintext secrets** — environment variables or ansible-vault.
9. `ansible.cfg` sets `inject_facts_as_vars: false` — use `ansible_facts['…']`; `ansible_user_dir` and friends are undefined (use `lookup('env', 'HOME')` for controller paths).

## Quick verification

```bash
make pytest                # pure-Python test suite, no Ansible needed
make check-sync            # play.yml vs profiles drift (CI gate)
make validate-profiles     # validate all profiles + overlays
```

Note: bare `python` may not be on PATH and system `python3` lacks jinja2 — the make targets resolve the correct interpreter and inject missing deps. 

## Key paths

- `profiles/*.yml` — 6 profiles (headless, i3, hyprland, gnome, awesomewm, kde), all extend `_base.yml`
- `profiles/overlays/*.yml` — laptop, bluetooth, user_environment
- `scripts/profile_dispatcher.py` — profile resolver, PlaybookGenerator, CLI (no Ansible dependency)
- `tests/` — pytest suite for the dispatcher
- `group_vars/all/base.yml` (tracked defaults) · `group_vars/all/local.yml` (gitignored machine-specific)
- `docs/` is gitignored — do not link files under it

For commands (`make setup|install|configure|test|generate-playbook`, `TAGS=`, `profile-<name>`), architecture, host variables, and workflows: **see `AGENTS.md`**.
