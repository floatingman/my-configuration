# Homebrew Role

This role installs Homebrew (also known as Linuxbrew on Linux) on Arch and Debian-based Linux systems and manages Homebrew packages.

## Requirements

- Arch Linux or Debian/Ubuntu-based Linux distribution
- Internet connection to download Homebrew installer and packages
- Ansible `community.general` collection (for Homebrew modules)

## Role Variables

Available variables are listed below, along with default values (see `defaults/main.yml`):

```yaml
homebrew_packages: []
```

List of Homebrew packages to install. Each package should be specified by its formula name or tap/formula format.

```yaml
homebrew_update: true
```

Whether to update Homebrew before installing packages.

## Dependencies

None.

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

1. **Checks for existing Homebrew installation** - Skips installation if already present
2. **Installs dependencies** - Installs required build tools for your OS (build-essential for Debian, base-devel for Arch)
3. **Installs Homebrew** - Downloads and runs the official Homebrew installation script (the script handles sudo internally)
4. **Configures shell** - Adds Homebrew to PATH in ~/.bashrc
5. **Updates Homebrew** - Updates package definitions using `community.general.homebrew` module (can be disabled)
6. **Installs packages** - Installs all packages specified in `homebrew_packages` using `community.general.homebrew` module

## Supported Packages

This role works with any Homebrew formula available on Linux. Common packages include:

- Development tools: `gh`, `glab`, `git-delta`
- Kubernetes tools: `kubectl`, `helm`, `k9s`, `kind`, `kubectx`, `kustomize`
- System utilities: `bat`, `fd`, `ripgrep`, `eza`, `dust`, `duf`
- And many more from the Homebrew ecosystem

For packages from custom taps, use the full tap/formula notation:
```yaml
homebrew_packages:
  - fairwindsops/tap/polaris
  - derailed/popeye/popeye
```

## Notes

- Homebrew is installed to `/home/linuxbrew/.linuxbrew` (standard location for Linux)
- The brew executable is located at `/home/linuxbrew/.linuxbrew/bin/brew`
- PATH configuration is added to `~/.bashrc` automatically
- The Homebrew installer script handles sudo permissions internally (do not run with `become: true`)
- This role uses the `community.general.homebrew` module for package management
- For packages not available in Homebrew, use the `ansible-role-binaries` role instead

## License

MIT

## Author Information

Created for the my-configuration repository.
