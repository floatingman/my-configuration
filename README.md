# My Configuration Script

Ansible is cool. This guy's config is cool. (see [Allaman](https://github.com/Allaman/rice)) and so is this guy's [pigmonkey](https://github.com/pigmonkey/spark) I've copied a lot from
them.

This is my attempt at fully automating the setup of my linux machines with it.

## Installing a new machine

For a fresh Arch machine, run [install.sh](install.sh)
from the Arch installer ISO (root shell, network up). It performs the full
[INSTALL.md](INSTALL.md) flow — LUKS2 + LVM, Plymouth-themed boot with a
Vimix GRUB menu (`/boot` on the ESP), dual UEFI/legacy-BIOS boot — and
prompts for disk, passwords, hostname, and user:

    # bash <(curl -fsSL https://zipline.thenewmans.casa/go/arch)

After reboot, log in as your user and finish with the playbook (these steps
are also saved as `~/NEXT_STEPS.txt` on the new machine):

```bash
cd ~/my-configuration
make setup && exec $SHELL -l      # pipx + ansible, then reload PATH
make install                      # ansible role requirements
cp group_vars/templates/desktop.yml group_vars/all/local.yml
# edit local.yml: set hostname and machine-specific variables
make first-boot                   # minutes: base + ssh + shell + dotfiles
make configure 2>&1 | tee configure.log   # everything else, with a readable log

```

After the first boot, SSH is already enabled with your GitHub public keys
(seeded by the installer), so you can finish setup — and read any errors —
from another machine.

Frequent provisioner? [FRESH_MACHINE.md](FRESH_MACHINE.md) collects the
failure modes that only appear on pristine machines and the fixes that
guard them.

## What's here?

This is my [Ansible](https://www.ansible.com/) playbook to automatically configure a new Linux installation on an Arch or Debian system. The following roles are being used:

- [packages](https://github.com/Allaman/ansible-role-packages) installs packages via package manager and an AUR helper
- [system](https://github.com/Allaman/ansible-role-system) configure system related settings
- **[homebrew](roles/homebrew)** installs and manages packages via Homebrew (for both Arch and Debian systems)
- [binaries](https://github.com/Allaman/ansible-role-binaries) "installs" applications by downloading it's binary and placing them in PATH (for tools not available in Homebrew)
- [dotfiles](https://github.com/floatingman/ansible-role-dotfiles) fork of [Allaman's](https://github.com/Allaman/ansible-role-dotfiles) Ansible role to clone and link dotfiles
- [shell](https://github.com/floatingman/ansible-role-shell) fork of [Allaman's](https://github.com/Allaman/ansible-role-shell) Ansible role that installs shell tools
- [asdf](https://github.com/floatingman/ansible-role-asdf) manages programming language versions (replaces pyenv)
- uv_python_packages manages Python package installation using the modern uv package manager
- **gpu_detect** auto-detects GPU hardware (AMD, NVIDIA, Intel) using lspci (Arch Linux only)
- **gpu_drivers** installs appropriate GPU drivers based on detected or configured GPU type (Arch Linux only)

You should checkout each roles README to see configuration options and decide if you need to fork a role for your own uses.

### Package Management Strategy

Starting from this version, the playbook uses **Homebrew** as the primary package manager for development tools and CLI utilities on both Arch and Debian-based systems. This provides:

- **Consistency**: Same package versions across different Linux distributions
- **Up-to-date packages**: Homebrew often has newer versions than distribution repositories
- **Easy management**: Simple installation and updates with `brew install` and `brew upgrade`

For packages not available in Homebrew, the `ansible-role-binaries` role downloads and installs binaries to `/usr/local/bin`.

### Multi-User Support

All development tools are installed system-wide, making them available to every user on the machine:

| Tool | Location | PATH mechanism |
|------|----------|---------------|
| asdf (languages, kubectl, etc.) | `/opt/asdf` | `/etc/profile.d/asdf.sh` |
| Linuxbrew (bat, fd, ripgrep, etc.) | `/home/linuxbrew/.linuxbrew` | `/etc/profile.d/linuxbrew.sh` |
| Rust/Cargo | `/opt/rust` | `/etc/profile.d/rust.sh` |
| Go | `/usr/local/go` | Already on PATH |
| Direct binaries | `/usr/local/bin` | Already on PATH |
| AI tools (pi, forge) | asdf shims / `/usr/local/bin` | `/etc/profile.d/asdf.sh` |

New users get access automatically when added to the `devtools` and `linuxbrew` groups:
```bash
sudo usermod -aG devtools,linuxbrew <username>
```

Per-user personalization (shell plugins, dotfiles, AI tool config) is separated into the `user_environment` overlay (see [Overlays](#overlays) below). Set `user_environment: false` in `group_vars/all/local.yml` to skip user-specific setup entirely.

### Configuration Profiles

The playbook ships with **profiles** — pre-configured bundles that set up a complete desktop stack in one command. Each profile selects the right roles, display manager, and environment variables automatically.

| Profile     | Desktop Environment        | Display Manager |
|-------------|----------------------------|-----------------|
| `headless`  | CLI-only (no display)      | none            |
| `i3`        | i3 window manager (X11)    | LightDM         |
| `hyprland`  | Hyprland compositor (Wayland) | SDDM         |
| `gnome`     | GNOME desktop              | GDM             |
| `awesomewm` | AwesomeWM tiling WM        | LightDM         |
| `kde`       | KDE Plasma                 | SDDM            |

**Quick start with a profile:**

```sh
# List all available profiles
make list-profiles

# Configure with a specific profile
make profile-i3
make profile-hyprland
make profile-gnome
make profile-awesomewm
make profile-kde
make profile-headless
```

You can still apply specific tags within a profile run by appending `TAGS=`:

```sh
make profile-i3 TAGS="editors,shell"
```

Profile definitions live in the `profiles/` directory as YAML files:

```
profiles/
├── _base.yml       # Core roles shared by all profiles
├── headless.yml    # CLI-only (extends _base)
├── i3.yml          # i3 + X11 (extends _base)
├── hyprland.yml    # Hyprland + Wayland (extends _base)
├── gnome.yml       # GNOME (extends _base)
├── awesomewm.yml   # AwesomeWM (extends _base)
└── kde.yml         # KDE Plasma (extends _base)
```

#### Overlays

Overlays are optional role groups in `profiles/overlays/` that apply on top of
any profile. Each overlay gates itself on a variable from
`group_vars/all/local.yml`:

| Overlay            | Enabled when                                   | Roles |
|--------------------|------------------------------------------------|-------|
| `user_environment` | by default — set `user_environment: false` to skip | shell, dotfiles, gnupg, ai (AI tooling additionally needs `ai_enabled: true`) |
| `laptop`           | `laptop: true`                                 | laptop, network_shares, backlight (display required) |
| `bluetooth`        | `bluetooth:` defined and not disabled (Arch only) | bluetooth |

```yaml
# group_vars/all/local.yml examples
laptop: true                 # enable the laptop overlay

bluetooth:
  disable: false             # defining bluetooth enables the overlay (default)

user_environment: false      # skip shell/dotfiles/gnupg/ai personalization
```

To opt out of bluetooth entirely, set `disable: true` (or remove the
`bluetooth:` variable).

#### Role annotations

Roles in `profiles/*.yml` are entries with gating annotations. At run time the
dispatcher translates them into `when:` conditions over pre-resolved facts
(`_is_arch`, `_has_display`, `_is_i3`, … and the `_overlay_*` flags):

| Annotation         | Meaning                                              | Example |
|--------------------|------------------------------------------------------|---------|
| `tags`             | Run targets for `make configure TAGS=`               | `[editors]` |
| `os`               | Restrict to `archlinux` or `debian`                  | `os: archlinux` |
| `requires_display` | Only runs with a display server (`_has_display`)     | `requires_display: true` |
| `requires_config`  | Match a specific config value                        | `requires_config: { display_manager: lightdm }` |
| `config_check`     | Jinja2 expression evaluated against host vars        | `"ai_enabled \| default(false) \| bool"` |
| `section`          | play.yml grouping; section order and comments are defined in `profiles/_sections.yml` | `section: dev` |

#### Changing profiles or roles: regenerate play.yml

`play.yml` is **auto-generated** from `profiles/` — never edit it by hand (its
header says so). Edit the profile instead, regenerate, and commit both files
together:

```sh
# 1. edit a profile or overlay
$EDITOR profiles/i3.yml

# 2. regenerate play.yml from the profile definitions
make generate-playbook

# 3. commit the profile change and the regenerated play.yml together
git add profiles/i3.yml play.yml && git commit -m "profiles: ..."
```

CI runs `make check-sync` and fails when `play.yml` is stale relative to
`profiles/`. Useful companion commands:

```sh
make validate-profiles             # validate all profiles + overlays
make list-profiles                 # human-readable profile table
python3 scripts/profile_dispatcher.py resolve-role-manifest --profile i3
                                   # inspect the fully resolved manifest
```

> The direct `python3 ...` dispatcher calls need `pyyaml` + `jinja2` in that
> interpreter (the `make` targets handle this for you by resolving the
> pipx-managed ansible venv) — prefer the make targets when in doubt.

To add a new profile, create `profiles/<name>.yml` (usually with
`extends: _base.yml`) using an existing profile as a reference, then run
`make generate-playbook`.

### Desktop Environment Support (Legacy / Manual)

If you prefer to configure desktop environments manually instead of using profiles, you can set variables in `group_vars/all/local.yml`:

```yaml
# Install only i3
desktop_environment: i3
display_manager: lightdm

# Install only Hyprland
desktop_environment: hyprland
display_manager: sddm
```

Opt-out variables are also supported:

```yaml
# Disable i3 (only install Hyprland)
disable_i3: true

# Disable Hyprland (only install i3)
disable_hyprland: true
```

When neither opt-out variables nor `desktop_environment` are set, both i3 and Hyprland are installed automatically.

## Display Management (monitors and laptop lid)

Display switching is automatic: no commands need to be run when docking or undocking (enabled by default; `x_display_autoswitch: false` in `group_vars/all/local.yml` turns it off and removes the deployed override, hook, watcher and scripts).

The [autorandr](https://github.com/phillipberndt/autorandr) profiles in `~/.config/autorandr` (deployed from the dotfiles) remain the source of truth for which outputs are active, their resolutions and per-output settings — with one deliberate exception: the lid rule below always turns the internal panel off/on with the lid, regardless of what the matching profile says. On top of them the `x` role wires up:

- **Monitor hotplug** — the udev rule shipped by the autorandr package (`40-monitor-hotplug.rules`) starts `autorandr.service` on every DRM change event. The role shadows that unit with one that runs `/usr/local/bin/display-autoswitch`: apply the best matching profile in every open X11 session, then enforce the lid rule.
- **Resume** — `autorandr.service` is enabled for `sleep.target`, so the best profile is re-applied after waking from suspend.
- **Laptop lid** — a small watcher service (`autorandr-lid-watcher.service`, laptops only) notices lid open/close (lid toggles produce no DRM udev events on most hardware) and triggers the same switch. The internal panel (`eDP*`/`LVDS*`) is turned off when the lid closes and turned back on — preferred mode, placed just beyond the rightmost edge of all active external outputs so it never overlaps a second monitor — when it opens, via `/usr/local/bin/display-lid-enforce`. That lid rule runs as two system-wide autorandr hooks: `predetect.d/10-lid-enforce` fires whenever autorandr actually applies a profile (`--change`/`--cycle`/`--load`) — including the login-time `exec_always autorandr --change` in the i3 config when no profile matches or the configuration is already loaded, which is exactly when autorandr skips its other hooks — while skipping `--save`, `--dry-run` and the inspection commands, which must never mutate displays; `postswitch.d/10-lid-enforce` re-checks after every profile application.

Saving a **new** monitor arrangement still takes one manual step the first time you use it (`arandr` to arrange, then `autorandr --save <name>` and commit the profile in the dotfiles); every later plug/unplug of that arrangement is applied automatically.

## GPU Driver Management

The playbook automatically detects and installs GPU drivers on Arch Linux systems.

### Automatic Detection

The `gpu_detect` role uses `lspci` to identify your GPU hardware and sets the appropriate driver variables for:
- **AMD**: Mesa drivers, Vulkan support, amdgpu_top
- **NVIDIA**: Open-source (nouveau) or proprietary drivers
- **Intel**: Mesa drivers, Intel Vulkan support
- **Hybrid systems**: Multiple GPUs handled with `gpu_drivers_hybrid_install_all`

### Configuration

Configure GPU behavior in `group_vars/all/local.yml`:

```yaml
# Detection mode: auto (default), amd, nvidia, intel
gpu_drivers_detection_mode: auto

# Force a specific GPU type (overrides detection)
# gpu_drivers_type: nvidia

# Use proprietary NVIDIA drivers
# gpu_drivers_nvidia_proprietary: true

# Install drivers for all GPUs in a hybrid system
# gpu_drivers_hybrid_install_all: true
```

### Testing GPU Changes

```sh
# Test GPU detection only
make configure TAGS="gpu_detect"

# Test GPU driver installation
make configure TAGS="gpu_drivers"

# Show detected GPU hardware
make gpu-info
```

## Fingerprint Unlock

i3 + betterlockscreen supports unlocking with the fingerprint sensor (fprintd).
The lock wrapper (`~/.local/bin/lock-fingerprint`, managed by chezmoi in the
dotfiles repo) runs `fprintd-verify` alongside i3lock and unlocks on a
successful scan; typing your password still works. It is bound to
`$mod+Shift+x` and is used by the idle auto-lock (xidlehook).

> Why a wrapper instead of PAM: i3lock only starts its PAM conversation after
> you press Enter, so `pam_fprintd` never runs. The wrapper performs the
> equivalent authentication itself.

The goesimage role deploys a systemd drop-in
(`~/.config/systemd/user/goesimage.service.d/override.conf`) that re-renders
the betterlockscreen cache from the current satellite wallpaper every time
goesimage updates it.

### Adding a new fingerprint

Enrollment requires an **active graphical session** and a running polkit
authentication agent (the i3 config autostarts
`/usr/lib/polkit-kde-authentication-agent-1`); a password prompt appears
before enrollment begins.

```sh
# List enrolled fingers
fprintd-list "$USER"

# Enroll a finger (touch the sensor repeatedly until "enroll-completed")
fprintd-enroll                       # defaults to right-index-finger
fprintd-enroll -f left-thumb         # or name any other finger

# Delete one and re-enroll
fprintd-delete "$USER" right-index-finger

# Verify a scan without locking
fprintd-verify
```

If enrollment fails with `PermissionDenied: Not Authorized`, your session is
not active or no polkit agent is running — start the agent and retry.

## Requirements

- Python 3
- A non-superuser account with sudo privileges (the playbook will prompt for the sudo password when needed)

> **Fresh machine?** You no longer need to install `pipx` by hand. Run `make setup`
> first — it installs pipx (and puts `~/.local/bin` on PATH) and then installs
> Ansible via pipx, all in one shot. (See [Quick start](#running-the-playbook)
> below.)
>
> The Python deps for the repo's own tooling (`pyyaml`, `jinja2`, `pytest`) are
> provisioned automatically: `make setup`/`make bootstrap` inject them into the
> pipx Ansible venv, and any make target that needs them (`make pytest`,
> `make check-sync`, …) self-heals via `make pip-deps` — on machines running
> system-wide Ansible it falls back to distro packages (`python-yaml`
> `python-jinja` `python-pytest` on Arch, `python3-*` equivalents on Debian).

## Use

The playbook is designed to be run by a non-superuser account. It will automatically escalate privileges (via sudo) for tasks that require root access, such as package installations and system configuration.

```sh
> make help
all                           Run all goals
apply                         Quick-apply a config subset: make apply WHAT=nmtrust (shortcut name or raw tags; no WHAT lists shortcuts)
bootstrap-pipx                Install pipx and add ~/.local/bin to PATH (run FIRST on a fresh system)
bootstrap                     Install ansible (pipx required)
check-sync                    Check play.yml sync with profile definitions (CI gate)
configure                     Run ansible (optionally with TAGS="tag1,tag2")
first-boot                    Minimal first run: base + ssh + shell + dotfiles (usable machine fast)
generate-playbook             Regenerate play.yml from profile definitions
gpu-info                      Display detected GPU information
help                          print this help
install                       Install roles via ansible-galaxy
lint                          Run yamllint and ansible-lint
list-profiles                 List all available configuration profiles
list-tags                     List all available tags in the playbook
pip-deps                      Ensure pyyaml is available (injects into pipx ansible environment)
pytest                        Run Python test suite with pytest
rerun-failed                  Rerun only the roles that failed in the last playbook run
setup                         One-shot fresh-system setup: install pipx + PATH, then ansible
sync-playbook                 Show drift between play.yml and profile definitions
syntax-check                  Check playbook syntax
test                          Run all tests (lint + syntax check + profile validation + sync check + pytest)
```

### Running the playbook

1. **Bootstrap** (first time on a fresh machine): install pipx + PATH + Ansible
   ```sh
   make setup           # installs pipx, ~/.local/bin on PATH, and ansible
   exec $SHELL -l       # reload the shell so the new PATH takes effect
   ```
   If `pipx` is already installed and only Ansible is missing, use `make bootstrap` instead.

2. **Install roles**: Install required Ansible roles and collections
   ```sh
   make install
   ```

3. **Create your local config**: Copy the template for your machine type and edit at minimum `hostname`
   ```sh
   # Desktop or laptop:
   cp group_vars/templates/desktop.yml group_vars/all/local.yml

   # Headless server:
   cp group_vars/templates/server.yml group_vars/all/local.yml
   ```
   Then open `group_vars/all/local.yml` and set:
   - `hostname` — short hostname for this machine
   - `network.trusted_uuid` — run `nmcli connection show` to find your UUIDs
   - `illuminanced` paths (desktop/laptop only) — run `ls /sys/class/backlight/` to find your device

4. **Configure**: Run the playbook (you will be prompted for your sudo password)
   ```sh
   make configure
   ```

The playbook uses `--ask-become-pass` to prompt for your sudo password when privilege escalation is needed. This ensures that the playbook can be run by any user with sudo privileges, not just root.

### Quick-apply shortcuts

For frequently re-applied subsets, `make apply WHAT=<name>` saves you from
remembering tag names. Bare `make apply` lists every shortcut with the tags it
runs; any raw playbook tag (or comma-separated mix) also works and is
validated against `play.yml` before anything runs.

```sh
make apply                    # list shortcuts
make apply WHAT=nmtrust       # re-render /etc/nmtrust trusted networks
make apply WHAT=update-tools  # apply new version pins: asdf + ~/.tool-versions + homebrew
make apply WHAT=rust,python   # raw tags still work
```

Shortcut definitions live in `APPLY_SHORTCUTS` in the `Makefile` — one
`name=tags` line each, picked up by `make apply` and `make help` automatically.

### Running specific tags

You can run specific roles by using tags. This allows you to only run certain parts of the playbook instead of the entire configuration.

1. **List all available tags**:
   ```sh
   make list-tags
   ```

2. **Run a single tag**:
   ```sh
   make configure TAGS="docker"
   ```

3. **Run multiple tags** (comma-separated):
   ```sh
   make configure TAGS="docker,editors,shell"
   ```

This is useful when you only want to configure specific components without running the entire playbook.

### Error resilience: continue past minor failures

A full run no longer dies at the first failing role. `play.yml` (generated
from `profiles/`, never hand-edited) wraps every role in a `block/rescue`
pair: when a role fails — a renamed package, a package that moved between
pacman and the AUR, a changed upstream URL — the failure is recorded and the
run continues with the next role. Everything that was skipped is reported
in one place at the end:

```sh
make configure
...
TASK [Summarize each rescued failure at the end of the run]
[role] media -- One or more packages failed ... [task: Install media packages]
[package] aur (package nova) -- not found in any pacman repo or the AUR (renamed or removed?)
The playbook ran to the end, but 2 failure(s) were rescued along the way ...
```

The run then exits non-zero on purpose, so a failed-but-completed run cannot
masquerade as a green one.

**Reading the error report.** Besides the console summary, every run writes
a machine-readable report to `~/.cache/my-configuration/failures.json`
(override with `resilience_report_path`; reports are also written for
`--check` runs, tagged `check_mode: true`). Each entry records the kind
(`role` or `package`), the role, the failing task, and the error message. A
report from a previous run is removed at the start of each run, so it always
describes the run that just finished.

**Rerunning only the failed parts.** After fixing a problem, rerun just the
affected roles:

```sh
make rerun-failed            # reads the report, runs make configure TAGS=<failed roles>
# or explicitly:
make configure TAGS="media,aur"
```

`make rerun-failed` maps each failed role to its playbook tag (e.g.
`ansible-role-packages` -> `packages`), deduplicates them, and runs the same
tag-validated `configure` target. When there is nothing to rerun it says so
and exits 0. Package-level failures are attributed to the role that owns the
list (`base_packages` -> `base`, `aur.packages` -> `aur`).

**Fatal problems.** By default nothing aborts the run. If some role must not
be skipped, list it in `resilience_fatal_roles` (default `[]`) in
`group_vars/all/local.yml`; a failure in a listed role stops the run
immediately. Failures of the `pre_tasks` manifest resolution are always
fatal. Set `resilience_exit_nonzero: false` to make even a run with rescued
failures exit 0.

**Package routing (pacman <-> AUR).** The `resilient_packages` helper role
(`roles/resilient_packages/`, used by the `base` and `aur` roles for
`base_packages` and `aur.packages`) installs each package from whichever
source actually has it: already-installed packages are skipped, packages in
the official repos install via `pacman`, AUR-only packages via `yay`, and
names that exist nowhere are reported at the end of the run as likely
renames instead of aborting. `yay` and the `aur_builder` sudoers bootstrap
are ensured on demand. Other roles can adopt the same helper:

```yaml
- name: Install my packages resiliently
  ansible.builtin.include_role:
    name: resilient_packages
  vars:
    resilient_packages_list: "{{ my_role_packages }}"
    resilient_packages_owner: my_role
```

Roles that have not adopted it are still protected by the block/rescue
wrappers — a bad package name in them surfaces in the end-of-run report
instead of stopping the playbook. The monthly
[package-liveness workflow](.github/workflows/package-liveness.yml) keeps
catching dead names in CI as well; for `base_packages` and `aur.packages` its
findings are advisory, since the runtime now routes both directions.
