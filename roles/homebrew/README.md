# Homebrew Role

This role installs Homebrew (Linuxbrew) on Arch and Debian-based Linux systems and manages Homebrew packages. It installs Homebrew in a **multi-user, system-wide** layout so that every member of the `linuxbrew` group can use `brew`, while keeping a single non-root owner for the tree (the model Homebrew itself recommends on Linux).

## Requirements

- Arch Linux or Debian/Ubuntu-based Linux distribution
- Internet connection to download Homebrew and packages
- Ansible `community.general` collection (for the Homebrew modules)
- A `user` variable (defined in `group_vars/all/base.yml`) whose `user.name` will own the Homebrew tree

## Installation Layout

| Path | Owner | Purpose |
|------|-------|---------|
| `/home/linuxbrew` | `{{ user.name }}:linuxbrew` (mode `2775`) | Base directory |
| `/home/linuxbrew/.linuxbrew` | `{{ user.name }}:linuxbrew` (setgid tree) | Homebrew installation |
| `/home/linuxbrew/.linuxbrew/bin/brew` | — | The brew executable |
| `/etc/profile.d/linuxbrew.sh` | `root:root` | Adds Homebrew to PATH for **all** login shells |

The whole tree is normalized to be **group-writable with the setgid bit** on directories, so files created by one `linuxbrew` member (taps, Cellar installs, downloads) are writable by the others. The primary user (`{{ user.name }}`) is the owner; add other users to the `linuxbrew` group to grant them access.

> Homebrew refuses to run as root ("extremely dangerous and no longer supported"). This role therefore installs and normalizes the tree up front so that brew can always run as an unprivileged user. The `ai` role performs the same normalization as a one-time migration safety net for trees created by older versions of this role.

## Role Variables

Available variables are listed below, along with default values (see `defaults/main.yml`):

```yaml
homebrew_packages: []
```

List of Homebrew packages to install. Each package is specified by its formula name or `tap/formula` format.

```yaml
homebrew_update: true
```

Whether to update Homebrew before installing packages.

```yaml
homebrew_tap_packages: []
```

List of taps to add before installing packages.

## Dependencies

None. The `linuxbrew` group is created by this role and also by the `system` role (which runs earlier in `play.yml`).

## Example Playbook

```yaml
- hosts: localhost
  roles:
    - role: homebrew
      vars:
        homebrew_packages:
          - bat
          - ripgrep
          - fd
          - kubectl
          - helm
```

## What This Role Does

1. **Checks for an existing Homebrew installation** — skips installation if `/home/linuxbrew/.linuxbrew/bin/brew` already exists.
2. **Installs OS dependencies** — `build-essential`, `procps`, `curl`, `file`, `git` on Debian; `base-devel`, `curl`, `file`, `git` on Arch.
3. **Creates the directory tree** — `/home/linuxbrew` and `/home/linuxbrew/.linuxbrew`, owned by `{{ user.name }}:linuxbrew` with mode `2775`.
4. **Downloads and extracts** the Homebrew master tarball into the tree, owned by the primary user.
5. **Normalizes ownership** — recursively `chown`s to `{{ user.name }}:linuxbrew`, sets `g+rwX`, and applies the setgid bit to every directory so the tree stays multi-user friendly.
6. **Configures PATH system-wide** — writes `/etc/profile.d/linuxbrew.sh` so every login shell gets `brew` on PATH.
7. **Adds taps and installs packages** from `homebrew_tap_packages` and `homebrew_packages` using the `community.general.homebrew` module (run as the primary user).

## Supported Packages

This role works with any Homebrew formula available on Linux. Common packages include:

- Development tools: `gh`, `glab`, `git-delta`
- Kubernetes tools: `kubectl`, `helm`, `k9s`, `kind`, `kubectx`, `kustomize`
- System utilities: `bat`, `fd`, `ripgrep`, `eza`, `dust`, `duf`

For packages from custom taps, use the full tap/formula notation:

```yaml
homebrew_packages:
  - fairwindsops/tap/polaris
  - derailed/popeye/popeye
```

## Notes

- Homebrew is installed to `/home/linuxbrew/.linuxbrew` (the standard Linux location).
- PATH is configured globally via `/etc/profile.d/linuxbrew.sh` (not per-user `~/.bashrc`), so it is available to every user on the machine.
- Grant additional users access by adding them to the `linuxbrew` group: `sudo usermod -aG linuxbrew <user>`.
- This role uses the `community.general.homebrew` module for package management.
- For packages not available in Homebrew, use the `ansible-role-binaries` role instead.

## Troubleshooting

- **"`/home/linuxbrew/.linuxbrew` is not writable"** — the tree lost its group-writable/setgid bits. Re-run `make configure TAGS="homebrew"` to re-normalize ownership, or run the role's normalization step manually.
- **brew refuses to run as root** — never invoke `brew` with `become: true` (root). The role runs brew as the primary user; the `ai` role does the same for its taps.

## License

MIT

## Author Information

Created for the my-configuration repository.
