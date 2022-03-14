# My Configuration Script

Ansible is cool. This guy's config is cool. (see [Allaman](https://github.com/Allaman/rice)) and so is this guy's [pigmonkey](https://github.com/pigmonkey/spark) I've copied a lot from
them.

This is my attempt at fully automating the setup of my linux machines with it.

## What's here?

This is my [Ansible](https://www.ansible.com/) playbook to automatically configure a new Linux installation on an Arch or Debian system. The following roles are being used:

- [basic](https://github.com/Allaman/ansible-role-basic) installs common/basic packages via package manager
- [packages](https://github.com/Allaman/ansible-role-packages) installs packages via package manager and an AUR helper
- [system](https://github.com/Allaman/ansible-role-system) configure system related settings
- [pip](https://github.com/Allaman/ansible-role-pip) install python packages via pip as current user
- [binaries](https://github.com/Allaman/ansible-role-binaries) "installs" applications by downloading it's binary and placing them in PATH
- [dotfiles](https://github.com/floatingman/ansible-role-dotfiles) fork of [Allaman's](https://github.com/Allaman/ansible-role-dotfiles) Ansible role to clone and link dotfiles
- [shell](https://github.com/floatingman/ansible-role-shell) fork of [Allaman's](https://github.com/Allaman/ansible-role-shell) Ansible role that installs shell tools

You should checkout each roles README to see configuration options and decide if you need to fork a role for your own uses.

## Requirements

The only requirement is a working pip installation and Python 3

## Use

```sh
> make
help                          This help.
bootstrap                     Install ansible (pip required)
install                       Install roles via ansible-galaxy
configure                     Run ansible-playbook
aur                           Run AUR helper to install AUR packages
all                           Run all goals (except AUR)
```
