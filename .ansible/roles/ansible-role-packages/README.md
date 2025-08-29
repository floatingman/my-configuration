# ansible-role-packages

Install packages on Arch or Ubuntu based systems via their package manager. Optionally, install an AUR package manager on Arch based systems.

## Test

Run `molecule test` to test this role in a docker container

## Requirements

- Arch Linux or Ubuntu based OS
- Sudo permissions

## Role Variables

- `cli`: Manage CLI packages for instance for server configuration

  - `cli.enabled`: Set to `True` to enable installation of cli packages
  - `cli.common`: List of common packages to install on all types of OS
  - `cli.arch`: List of packages to install on Arch Linux only
  - `cli.debian`: List of packages to install on Debian only

- `gui`: Manage GUI packages for instance for workstation/Laptop configuration

  - `gui.enabled`: Set to `True` to enable installation of GUI packages
  - `gui.common`: List of common packages to install on all types of OS
  - `gui.arch`: List of packages to install on Arch Linux only
  - `gui.debian`: List of packages to install on Debian only

- `lang`: Manage programming languages

  - `lang.enabled`: Set to `True` to enable installation of programming languages
  - `lang.common`: List of common packages to install on all types of OS
  - `lang.arch`: List of packages to install on Arch Linux only
  - `lang.debian`: List of packages to install on Debian only

- `install_aur_helper`: Set to `True` to install an [AUR helper](https://aur.archlinux.org/)
- `is_test`: Set to `True` only required when running molecule test

## Dependencies

ansible-role-basic

## Example Playbook

See [converge.yml](https://github.com/Allaman/ansible-role-packages/blob/master/molecule/default/converge.yml)

## License

MIT
