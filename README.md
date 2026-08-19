# My Configuration Script

Ansible is cool. This guy's config is cool. (see [Allaman](https://github.com/Allaman/rice)) and so is this guy's [pigmonkey](https://github.com/pigmonkey/spark) I've copied a lot from
them.

This is my attempt at fully automating the setup of my linux machines with it.

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

Per-user personalization (shell plugins, dotfiles, AI tool config) is separated into the `user_environment` overlay. Set `user_environment: false` in `local.yml` to skip user-specific setup entirely.

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

## Use

The playbook is designed to be run by a non-superuser account. It will automatically escalate privileges (via sudo) for tasks that require root access, such as package installations and system configuration.

```sh
> make
all                           Run all goals
bootstrap-pipx               Install pipx and add ~/.local/bin to PATH (run FIRST on a fresh system)
bootstrap                     Install ansible (pipx required)
configure                     Run ansible (optionally with TAGS="tag1,tag2")
gpu-info                      Display detected GPU information
help                          print this help
install                       Install roles via ansible-galaxy
list-profiles                 List all available configuration profiles
list-tags                     List all available tags in the playbook
profile-awesomewm             Run AwesomeWM tiling window manager profile
profile-gnome                 Run GNOME desktop environment profile
profile-headless              Run headless profile (CLI-only, no display)
profile-hyprland              Run Hyprland Wayland compositor profile
profile-i3                    Run i3 window manager profile
profile-kde                   Run KDE Plasma desktop profile
setup                         One-shot fresh-system setup: install pipx + PATH, then ansible
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
