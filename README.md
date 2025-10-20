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

You should checkout each roles README to see configuration options and decide if you need to fork a role for your own uses.

### Package Management Strategy

Starting from this version, the playbook uses **Homebrew** as the primary package manager for development tools and CLI utilities on both Arch and Debian-based systems. This provides:

- **Consistency**: Same package versions across different Linux distributions
- **Up-to-date packages**: Homebrew often has newer versions than distribution repositories
- **Easy management**: Simple installation and updates with `brew install` and `brew upgrade`

For packages not available in Homebrew, the `ansible-role-binaries` role is still used to download and install binaries directly.

### Desktop Environment Support

This playbook supports both **i3 (Xorg)** and **Hyprland (Wayland)** desktop environments simultaneously. When a `display_manager` is configured (e.g., LightDM), both desktop environments are installed by default and available as session options at login.

**Key Features:**
- **Dual Installation**: Both i3 and Hyprland are installed together, allowing you to switch between them at the login screen
- **Session Files**: The playbook automatically creates session files in `/usr/share/xsessions/` (for i3) and `/usr/share/wayland-sessions/` (for Hyprland)
- **LightDM Integration**: Both desktop environments appear as selectable sessions in the LightDM greeter

**Customization Options:**

If you want to install only one desktop environment, you can use opt-out variables in your `group_vars/all.yml`:

```yaml
# Disable i3 installation (only install Hyprland)
disable_i3: true

# Disable Hyprland installation (only install i3)
disable_hyprland: true
```

For backward compatibility, you can also use the `desktop_environment` variable to install only one environment:

```yaml
# Install only i3
desktop_environment: i3

# Install only Hyprland
desktop_environment: hyprland
```

When neither opt-out variables nor `desktop_environment` are set, both environments are installed automatically.

## Requirements

- Python 3
- pip (Python package installer)
- A non-superuser account with sudo privileges (the playbook will prompt for the sudo password when needed)

## Use

The playbook is designed to be run by a non-superuser account. It will automatically escalate privileges (via sudo) for tasks that require root access, such as package installations and system configuration.

```sh
> make
help                          This help.
bootstrap                     Install ansible (pip required)
install                       Install roles via ansible-galaxy
configure                     Run ansible-playbook (will prompt for sudo password)
aur                           Run AUR helper to install AUR packages
all                           Run all goals (except AUR)
```

### Running the playbook

1. **Bootstrap**: Install Ansible as a regular user
   ```sh
   make bootstrap
   ```

2. **Install roles**: Install required Ansible roles and collections
   ```sh
   make install
   ```

3. **Configure**: Run the playbook (you will be prompted for your sudo password)
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
