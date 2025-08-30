# OneUI4 Icons Ansible Role

This Ansible role installs OneUI4-Icons theme from the git repository, converting the functionality of the `illogical-impulse-oneui4-icons-git` PKGBUILD into an idempotent Ansible role.

## Description

A fork of mjkim0727/OneUI4-Icons for illogical-impulse dotfiles. This role clones the repository and installs the OneUI, OneUI-dark, and OneUI-light icon themes to `/usr/share/icons`.

## Requirements

- Ansible 2.9+
- Git (automatically installed as dependency)
- Arch Linux (currently supported)

## Role Variables

Available variables are listed below, along with default values (see `defaults/main.yml`):

```yaml
# Repository settings
oneui4_icons_repo_url: "https://github.com/end-4/OneUI4-Icons.git"
oneui4_icons_git_version: "HEAD"
oneui4_icons_package_name: "illogical-impulse-oneui4-icons-git"

# Build settings
oneui4_icons_build_dir: "/tmp/oneui4-icons-build"
oneui4_icons_cleanup_build: true

# Installation settings
oneui4_icons_install_path: "/usr/share/icons"
oneui4_icons_enabled: true

# Icon themes to install
oneui4_icons_themes:
  - "OneUI"
  - "OneUI-dark"
  - "OneUI-light"

# Update icon cache after installation
oneui4_icons_update_cache: true
```

## Dependencies

None.

## Example Playbook

```yaml
- hosts: desktop
  roles:
    - oneui4_icons
```

Or with custom variables:

```yaml
- hosts: desktop
  roles:
    - role: oneui4_icons
      vars:
        oneui4_icons_git_version: "main"
        oneui4_icons_cleanup_build: false
```

## License

MIT

## Author Information

This role was created by Daniel Newman for the illogical-impulse dotfiles configuration, converted from the original PKGBUILD format.

## Original PKGBUILD

This role is based on the `illogical-impulse-oneui4-icons-git` PKGBUILD which installs OneUI4-Icons from https://github.com/end-4/OneUI4-Icons.
