# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an Ansible configuration management repository that automates the complete setup of Linux machines (Arch Linux and Debian-based systems). The playbook handles system configuration, desktop environments, development tools, and application installations with comprehensive OS and desktop environment support.

## Supported Systems

### Primary Systems
- **Arch Linux** - Full feature support including AUR packages
- **Debian-based** - Ubuntu, Mint, etc. with Homebrew integration

### Hardware Support
- **Laptops**: Special configurations for power management, WiFi, and trackpads
- **Desktops**: Full desktop environment support
- Framework laptop specific configurations included

### Special Features
- **Dual Boot**: Automatic GRUB configuration (see INSTALL_DUAL_BOOT.md)
- **Package Migration**: Homebrew-based package management for cross-distribution consistency
- **ASDF Integration**: Version management for programming languages
- **Multi-Desktop**: Support for multiple DEs with opt-out options

## Common Development Commands

### Essential Commands
- `make bootstrap` - Install Ansible using pipx (first-time setup)
- `make install` - Install Ansible roles and collections via ansible-galaxy
- `make configure` - Run the main playbook (requires sudo)
- `make configure TAGS="role1,role2"` - Run specific roles only
- `make list-tags` - List all available tags in the playbook
- `make help` - Show all available Makefile targets

### Testing and Validation
- Tag-based testing: Run individual roles with `make configure TAGS="rolename"`
- Validate tag syntax: The Makefile automatically validates tags before execution
- Use `VERBOSE=1` for detailed Ansible output during troubleshooting

### Output Control
- By default, Makefile runs in silent mode for cleaner output
- Use `VERBOSE=1` flag for verbose output: `make configure VERBOSE=1`

## Architecture and Structure

### Core Components
- **play.yml** - Main playbook orchestrating ~60 roles with conditional OS support
- **requirements.yml** - Defines Ansible roles and collections (all Git-based)
- **Makefile** - Build automation with validation and help system
- **group_vars/all.yml** - Main configuration file with all system variables

### Key Technologies
- Ansible for configuration management
- Homebrew as primary package manager for development tools
- Support for multiple desktop environments (i3, Hyprland, GNOME, AwesomeWM, KDE)
- AUR collection for Arch Linux packages
- ASDF for version management of programming languages

### Role Categories
1. **Base System**: base, grub, microcode, system configuration
2. **Development**: asdf, editors (neovim, vscode), devtools, kubernetes
3. **Desktop**: i3, hyprland, gnome, awesomewm, kde with dual-desktop support
4. **Utilities**: shell, ssh, dotfiles, cron, networking
5. **Applications**: browsers, media, editors, productivity
6. **Services**: docker, cups, bluetooth, printing

### Important Patterns
- **Tagging System**: All roles are tagged for selective execution
- **OS-Specific**: Conditional execution using `ansible_facts['os_family']`
- **Desktop Variables**: Use `display_manager` and `desktop_environment` variables
- **Opt-out Variables**: Individual desktop components can be disabled with `disable_*` flags
- **Idempotency**: Playbook designed to be safe to run multiple times
- **Privilege Escalation**: Uses `--ask-become-pass` for sudo access when needed

## Configuration Variables

The playbook uses several key configuration variables:
- `display_manager`: Controls which display manager to install
- `desktop_environment`: Sets the primary desktop environment
- `disable_i3`: Disable i3 window manager
- `disable_hyprland`: Disable Hyprland Wayland compositor
- Variables are set in group_vars templates for different use cases

## Configuration Variables

The playbook uses several key configuration variables:
- `display_manager`: Controls which display manager to install (e.g., lightdm, gdm)
- `desktop_environment`: Sets the primary desktop environment (i3, hyprland, gnome, etc.)
- `disable_i3`: Disable i3 window manager (opt-out)
- `disable_hyprland`: Disable Hyprland Wayland compositor (opt-out)
- `laptop`: Enable laptop-specific configurations
- Variables are set in group_vars/all.yml and can be customized per environment

## Package Management Strategy

The configuration uses a hybrid approach:

1. **Homebrew** (Primary): Main package manager for development tools and CLI utilities
   - Provides consistency across Arch and Debian systems
   - Installed on both Arch and Debian via ansible-role-homebrew
   - Packages defined in `homebrew_packages` list in group_vars/all.yml
   - Migration documented in HOMEBREW_MIGRATION.md

2. **System Package Managers**: OS-specific packages
   - Arch: pacman via ansible-role-packages
   - Debian: apt via ansible-role-packages

3. **AUR**: Arch User Repository packages via kewlfft.aur collection
   - Run separately with `make aur` after main playbook

4. **Direct Binaries**: For packages not available in Homebrew
   - Handled by ansible-role-binaries
   - Reduced list after migration to Homebrew

5. **GPU Drivers**: Automatic GPU driver management (Arch Linux only)
   - Auto-detects AMD, NVIDIA, and Intel GPUs using lspci
   - Supports manual override in group_vars/all.yml
   - Handles hybrid GPU systems with multiple GPUs
   - Supports both open-source and proprietary NVIDIA drivers
   - Role: gpu_drivers with tag "gpu_drivers"

## Important Documentation

### README.md
- Main project documentation
- Usage instructions and overview
- Desktop environment configuration options

### HOMEBREW_MIGRATION.md
- Details the migration to Homebrew package management
- Lists packages migrated and remaining
- Explains the benefits of the new approach

### INSTALL_DUAL_BOOT.md
- Instructions for dual boot setup
- GRUB configuration
- Bootloader management

### Role-specific READMEs
- Each role in roles/ may have its own README.md
- Contains role-specific documentation and configuration options

## Desktop Environment Support

The playbook supports multiple desktop environments with unique dual-desktop capabilities:

- **i3**: X11-based window manager
- **Hyprland**: Wayland compositor
- **GNOME**: Desktop environment
- **AwesomeWM**: Tiling window manager
- **KDE**: Plasma desktop environment

When no `disable_*` flags are set and `desktop_environment` is undefined, both i3 and Hyprland are installed together, allowing switching at login.

## Development Workflow

### Adding New Roles
1. Create role directory or add to requirements.yml if using remote role
2. Add role to play.yml with appropriate tags and conditions
3. Follow role structure: tasks/, defaults/, vars/, handlers/, meta/
4. Test with `make configure TAGS="role_name"`

### Role Variable Convention (PR checklist item)

Every variable a role reads **must** have an entry in that role's `defaults/main.yml` before the PR merges:

- **Optional variables** must default to `null` (meaning "feature disabled"), not be omitted entirely. This makes the variable self-documenting and prevents `undefined variable` errors on hosts that skip `local.yml`.
- **Machine-specific variables** that belong in `group_vars/all/local.yml` must also be added as commented-out examples in **both** `group_vars/templates/desktop.yml` and `group_vars/templates/server.yml` so that new-machine setup instructions remain accurate.

Example `defaults/main.yml` entry for an optional feature:
```yaml
# Set to true to enable foo on this machine; null disables it
foo_enabled: null
```

### Modifying Existing Roles
1. Always maintain backward compatibility
2. Use tags for selective testing
3. Test in VM or container before production use
4. Ensure idempotency - playbook can run safely multiple times

### Role Structure Guidelines
Each role should follow Ansible Galaxy structure:
- `tasks/main.yml` - Main task definitions
- `defaults/main.yml` - Default variables
- `vars/main.yml` - Role-specific variables
- `handlers/main.yml` - Handler definitions
- `meta/main.yml` - Role metadata

### Testing and Validation
- **Before Changes**: Run `make list-tags` to see available tags
- **Role Testing**: Use `make configure TAGS="tag_name"` to test specific roles
- **VM Testing**: Always test on VM or container first
- **Tag Validation**: Makefile automatically validates tags before execution
- **Verbose Output**: Use `VERBOSE=1` for detailed Ansible output during troubleshooting

### Error Handling
- If ansible-galaxy fails, check connectivity and requirements.yml syntax
- If role fails, isolate with specific tag
- Check Ansible version compatibility (requires Ansible 2.x)
- For AUR packages, run `make aur` separately

## GPU Driver Management

### Automatic Detection
The system automatically detects GPUs using `lspci` and installs appropriate drivers:
- **AMD**: Mesa drivers, Vulkan support, amdgpu_top
- **NVIDIA**: Choice between open-source (nouveau) or proprietary drivers
- **Intel**: Mesa drivers, Vulkan Intel support

### Configuration Options
Configure in `group_vars/all.yml`:
```yaml
# Detection mode: auto, amd, nvidia, intel
gpu_drivers_detection_mode: auto

# Force specific GPU type (overrides detection)
# gpu_drivers_type: nvidia

# Use proprietary drivers for NVIDIA
# gpu_drivers_nvidia_proprietary: true

# Install drivers for all GPUs in hybrid systems
# gpu_drivers_hybrid_install_all: true
```

### Testing GPU Changes
```bash
# Test GPU detection only
make configure TAGS="gpu_detect"

# Test GPU driver installation
make configure TAGS="gpu_drivers"

# Test full configuration with GPU support
make configure
```

## Best Practices

1. **Never run playbook as root** - Use privilege escalation with sudo
2. **Test with tags** - Validate individual roles before full configuration
3. **Use templates** - Configuration variables are in .template files requiring manual copying
4. **Verify OS compatibility** - Role execution varies between Arch and Debian systems
5. **Update dependencies** - Run `make install` after updating requirements.yml
6. **Run playbook incrementally** - Start with base system, then add components
7. **Use the AUR target separately** - `make aur` for AUR packages after main configuration
8. **Document changes** - Update README.md for user-facing changes
9. **Maintain compatibility** - Support both Arch and Debian where possible
10. **Test GPU changes separately** - Use gpu_detect and gpu_drivers tags for GPU-specific testing