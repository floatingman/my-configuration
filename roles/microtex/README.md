# MicroTeX Ansible Role

This Ansible role builds and installs MicroTeX from source, based on the PKGBUILD for `illogical-impulse-microtex-git`.

## Description

MicroTeX is a dynamic, cross-platform, and embeddable LaTeX rendering library. This role:

1. Installs required dependencies (tinyxml2, gtkmm3, gtksourceviewmm, cairomm, git, cmake)
2. Clones the MicroTeX repository from GitHub
3. Applies necessary patches to CMakeLists.txt
4. Builds the project using CMake
5. Installs the binary and resources to `/opt/MicroTeX/`
6. Installs the license file
7. Optionally creates a symbolic link for easy access
8. Optionally cleans up build artifacts

## Requirements

- Arch Linux (currently only supported distribution)
- Ansible 2.9+
- Internet connection for cloning the repository

## Role Variables

Available variables are listed below, along with default values (see `defaults/main.yml`):

```yaml
# Repository settings
microtex_repo_url: "https://github.com/NanoMichael/MicroTeX.git"
microtex_package_name: "illogical-impulse-microtex-git"

# Build settings
microtex_build_dir: "/tmp/microtex-build"
microtex_cleanup_build: true

# Installation settings
microtex_create_symlink: true
microtex_install_path: "/opt/MicroTeX"
microtex_cmake_build_type: "None"
```

## Dependencies

None.

## Example Playbook

```yaml
- hosts: localhost
  become: true
  roles:
    - { role: microtex, tags: ["microtex"] }
```

## Example with custom variables

```yaml
- hosts: localhost
  become: true
  roles:
    - role: microtex
      vars:
        microtex_cleanup_build: false
        microtex_create_symlink: false
      tags: ["microtex"]
```

## License

MIT

## Author Information

Created for illogical-impulse dotfiles configuration.
