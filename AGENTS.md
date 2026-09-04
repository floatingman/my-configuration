# AGENTS.md

Guidance for AI coding agents working in this repository (any agent: Claude Code, Copilot, Cursor, Codex, …).

Ansible playbook that fully configures a Linux workstation — Arch Linux (primary) and Debian (secondary): base system, GPU drivers, desktop environments (i3, Hyprland, GNOME, AwesomeWM, KDE), dev tools, applications. Always runs against localhost (`ansible-playbook -i localhost play.yml`).

## Hard rules

1. **Never edit `play.yml` by hand.** It is generated from `profiles/` (header says so). Edit the profile, then `make generate-playbook`, and commit `play.yml` together with the profile change. CI fails on drift (`make check-sync`).
2. **`profiles/` is the single source of truth** for which roles run and under what conditions. Conditions are expressed as profile annotations, not hand-written `when:` clauses.
3. **Every role has a tag** matching the role name. `make configure TAGS=…` validates tags against `play.yml` before running and exits on unknown tags.
4. **In `play.yml` `when:` clauses, use only the pre-resolved facts** set by `pre_tasks`: `_is_arch`, `_has_display`, `_is_i3`, `_is_hyprland`, `_is_gnome`, `_is_awesomewm`, `_is_kde`, and the overlay flags `_overlay_*`. Never use raw `ansible_os_family`/`ansible_distribution` there — OS gating belongs in profile annotations (`os: archlinux` / `os: debian`).
5. **Every variable a role reads must have an entry in that role's `defaults/main.yml`.** Optional variables default to `null` (feature disabled), never omitted. Machine-specific variables must also appear as commented-out examples in **both** `group_vars/templates/desktop.yml` and `group_vars/templates/server.yml`.
6. **Never run the playbook as root.** Sudo is per-task `become: true`; the Makefile passes `--ask-become-pass`.
7. **Idempotency is required.** `command`/`shell` tasks need `creates:` or `changed_when:` guards. Running the playbook twice must be safe.
8. **No plaintext secrets.** Use environment variables or ansible-vault.
9. `ansible.cfg` sets `inject_facts_as_vars: false` — facts are only reachable as `ansible_facts['…']`; `ansible_user_dir` and friends are undefined. For controller paths use `lookup('env', 'HOME')`.

## Commands

| Command                                 | Purpose                                                            |
| --------------------------------------- | ------------------------------------------------------------------ |
| `make setup`                            | One-shot fresh system: pipx + PATH + ansible                       |
| `make bootstrap`                        | Install ansible via pipx (requires pipx)                           |
| `make install`                          | `ansible-galaxy install` roles + collections from requirements.yml |
| `make configure`                        | Run the playbook (prompts for sudo password)                       |
| `make configure TAGS="rust,python"`     | Run only tagged roles (tags validated first)                       |
| `make profile-i3`                       | Run one profile; see `make list-profiles`                          |
| `make test`                             | lint + syntax-check + validate-profiles + check-sync + pytest      |
| `make check-sync`                       | CI gate: `play.yml` vs `profiles/` drift                           |
| `make generate-playbook`                | Regenerate `play.yml` from profiles                                |
| `make validate-deps`                    | Role dependency graph check (cycles, missing roles)                |
| `make gpu-info`                         | Show detected GPUs via `lspci` (requires pciutils)                 |
| `make list-tags` / `make list-profiles` | Discovery                                                          |
| `VERBOSE=1 make configure`              | Non-silent output for troubleshooting                              |

Dispatcher CLI (`scripts/profile_dispatcher.py`, pure Python — needs pyyaml + jinja2, no Ansible). **Prefer the make targets**: they resolve the pipx-managed ansible-venv interpreter and inject missing deps (`make pip-deps`). A bare `python` is often not on PATH, and system `python3` lacks jinja2. CI pip-installs the deps, so direct invocation works there.

```bash
make validate-profiles                # validate all profiles + overlays (includes sync check)
make check-sync                       # drift check (CI gate)
make pytest                           # test suite
# Direct CLI (interpreter must have pyyaml+jinja2 — e.g. the pipx ansible venv):
python3 scripts/profile_dispatcher.py resolve-role-manifest --profile i3  # inspect resolved manifest
python3 scripts/profile_dispatcher.py list-profiles --format pretty
```

Tests: `make pytest` — pure Python, no Ansible; split by domain under `tests/`:
`test_generator.py` (PlaybookGenerator boundary: generate/sync*check/resolve/explain),
`test_cli.py` (subcommands via `main()`), `test_profiles.py` (profile/overlay loading, resolution),
`test_conditions.py` (condition translation + evaluators),
`test_golden.py` + `test_manifest_resolver.py` (PRD-176 golden wire matrix, resolver contract).
Tests import only the public API (`profile_dispatcher.__all__`) — never `*`-prefixed symbols.

## Architecture

```
Build time:   profiles/*.yml ──PlaybookGenerator──> play.yml   (make generate-playbook)

Run time:     play.yml pre_tasks (tag: always)
                └─ scripts/profile_dispatcher.py resolve-role-manifest
                     └─ set_fact: _is_arch, _has_display, _is_<de>, _overlay_<role>
                          └─ each role: when: <fact>
```

- **Profiles** (`profiles/*.yml`): 6 profiles — headless, i3, hyprland, gnome, awesomewm, kde — all `extends: _base.yml`. Role annotations: `tags`, `os` (`archlinux`/`debian`), `requires_display`, `config_check` (Jinja expression over host vars), `requires_config` (key/value match, e.g. `display_manager: lightdm`). Roles exclusive to one DE profile automatically get `_is_<de>` conditions.
- **Overlays** (`profiles/overlays/*.yml`): optional role groups gated by host vars via `applies_when`:
  - `laptop.yml` — `laptop | default(false)` → roles: laptop, backlight
  - `bluetooth.yml` — `bluetooth is defined and not bluetooth.disable` → role: bluetooth (Arch only)
  - `user_environment.yml` — `user_environment | default(true)` → roles: shell, dotfiles, gnupg, ai (each further gated: `dotfiles_config is defined`, `ai_enabled | default(false)`)
    In `play.yml`, overlay roles are gated by the overlay-level fact: `when: _overlay_laptop` / `_overlay_bluetooth` / `_overlay_user_environment`. The manifest also computes per-role facts (`_overlay_shell`, `_overlay_ai`, …) which `pre_tasks` exposes.
- **`scripts/profile_dispatcher.py`** (~3.5k lines): profile resolver, `PlaybookGenerator` engine, condition translation (`ConditionTranslator` protocol), and CLI. No Ansible import. Tests in `tests/`.
- **CI** (`.github/workflows/ci.yml`, Python 3.13): `pytest tests/` + `validate` + `sync-playbook --check` on push/PR to main. Nothing else — no Ansible in CI.
- **Bump bot** (`.github/workflows/bump-versions.yml`): two cadences, one workflow — weekly Mondays, shell/tmux plugin pins in `roles/shell/defaults/main.yml` (`scripts/bump_plugin_versions.py`); monthly on the 1st, `base.yml` binary-download versions (`scripts/bump_base_versions.py`, manifest doubles as the exclusion list). Both open pin-only PRs — versions move only through review; the playbook never floats. Plugin clones are always version-pinned — never floating `HEAD`.
- **`facts.yml`**: debug playbook that dumps `ansible_facts` to `/tmp/ansible_facts.json`.
- **External roles**: git-based from `floatingman/*` (binaries, packages, asdf) + `kewlfft.aur` collection. Run `make install` after changing `requirements.yml`.

## Key host variables

| Variable                     | Meaning                                                               |
| ---------------------------- | --------------------------------------------------------------------- |
| `profile`                    | Profile to run (unset ⇒ manual mode driven by the vars below)         |
| `display_manager`            | `lightdm` \| `gdm` \| `sddm` \| `""`                                  |
| `desktop_environment`        | `i3` \| `hyprland` \| `gnome` \| `awesomewm` \| `kde` \| `""`         |
| `disable_i3` … `disable_kde` | Per-desktop opt-out flags (one per DE)                                |
| `laptop`, `bluetooth`        | Overlay toggles                                                       |
| `user_environment`           | Per-user personalization overlay; default `true`, set `false` to skip |
| `ai_enabled`                 | AI tooling (pi, forge, …), gated inside user_environment              |
| `dotfiles_config`            | Defined ⇒ dotfiles role runs                                          |

### group_vars layout

| File                                        | Status         | Content                                                           |
| ------------------------------------------- | -------------- | ----------------------------------------------------------------- |
| `group_vars/all/base.yml`                   | tracked        | Shared defaults for all machines                                  |
| `group_vars/all/local.yml`                  | **gitignored** | Machine-specific overrides (laptop, hostname, display_manager, …) |
| `group_vars/templates/{desktop,server}.yml` | tracked        | Starting-point templates for a new machine                        |

## Conventions

- Role layout follows Ansible Galaxy structure: `tasks/`, `defaults/`, `vars/`, `handlers/`, `meta/`. YAML: 2-space indent, no tabs, `---` document start; enforced by `.yamllint` / `.ansible-lint`.
- Dev tools install **system-wide** (table below) and are exposed to all users via `/etc/profile.d/`. Per-user personalization (shell, dotfiles, gnupg, ai) is separate: the `user_environment` overlay, skippable via tag or `user_environment: false`.
- Package strategy: Homebrew = cross-distro dev/CLI tools (`homebrew_packages`); pacman/apt via `ansible-role-packages`; AUR via `kewlfft.aur` (Arch only); direct binaries via `ansible-role-binaries` (Debian). See HOMEBREW_MIGRATION.md.
- GPU drivers: auto-detected via `lspci` (`gpu_drivers_detection_mode: auto`; override with `gpu_drivers_type`; `gpu_drivers_nvidia_proprietary`, `gpu_drivers_hybrid_install_all` for hybrid). Arch only. Test with tags `gpu_detect` / `gpu_drivers`.
- Handlers live in `handlers/main.yml`, notified by name — not inline restarts.
- Prefer `template` over `copy` whenever variables are interpolated.

### System-wide tool paths

| Tool                            | Location                     | PATH via                      |
| ------------------------------- | ---------------------------- | ----------------------------- |
| asdf (languages, kubectl)       | `/opt/asdf`                  | `/etc/profile.d/asdf.sh`      |
| Linuxbrew (bat, fd, ripgrep, …) | `/home/linuxbrew/.linuxbrew` | `/etc/profile.d/linuxbrew.sh` |
| Rust/Cargo                      | `/opt/rust`                  | `/etc/profile.d/rust.sh`      |
| Go                              | `/usr/local/go`              | default PATH                  |
| Direct binaries                 | `/usr/local/bin`             | default PATH                  |

Grant a new user access: `sudo usermod -aG devtools,linuxbrew <username>`.

## Workflows

### Add a role

1. Create `roles/<name>/` (or add to `requirements.yml` + `make install` for a remote role).
2. Add the role to `profiles/_base.yml` (or the DE profile, or an overlay) with tag + annotations.
3. `make generate-playbook` — verify with `make check-sync`.
4. Satisfy rule 5 for every role variable.
5. Verify: `make pytest && make check-sync`; smoke-test on a VM with `make configure TAGS="<role>"`.

### Add / change a variable

Default in the role's `defaults/main.yml`; machine value in `group_vars/all/local.yml`; commented example in both `group_vars/templates/` files.

## Docs

`README.md` (usage/overview — update for user-facing changes), `INSTALL.md`, `INSTALL_DUAL_BOOT.md`, `HOMEBREW_MIGRATION.md`, per-role `roles/*/README.md`.

## Mistakes

Follow guidelines listed in @MISTAKES.md
