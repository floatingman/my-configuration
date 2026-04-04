# Copilot Instructions for my-configuration

## Repository Overview

This is an Ansible-based configuration management repository for automating Linux system setup on Arch and Debian-based systems. The repository uses Ansible playbooks to configure a fresh Linux installation with various roles for system configuration, package management, desktop environments, and development tools.

## Project Structure

- **play.yml**: Main Ansible playbook that orchestrates all roles
- **Makefile**: Build automation with targets for bootstrapping, installing, and configuring
- **requirements.yml**: Ansible Galaxy roles and collections dependencies
- **roles/**: Directory containing all Ansible roles for configuration
- **group_vars/**: Variable files for different groups
- **ansible.cfg**: Ansible configuration file

## Key Technologies

- **Ansible**: Configuration management and automation
- **Python**: Required for Ansible and custom scripts
- **Make**: Build automation and task running
- **YAML**: Configuration and playbook definitions

## Development Guidelines

### Ansible Best Practices

1. **Role Structure**: Each role should follow Ansible Galaxy role structure:
   - `tasks/main.yml` - Main task definitions
   - `defaults/main.yml` - Default variables
   - `vars/main.yml` - Role-specific variables
   - `handlers/main.yml` - Handler definitions
   - `meta/main.yml` - Role metadata

2. **Tagging System**: All roles in play.yml must have tags for selective execution:
   ```yaml
   - { role: role_name, tags: ["tag_name"] }
   ```
   Tags should match the role name or functionality for consistency.

3. **Conditional Execution**: Use `when` clauses for OS-specific or environment-specific roles:
   - `ansible_os_family == "Archlinux"` for Arch Linux specific tasks
   - Check for `desktop_environment is defined` before desktop-specific roles
   - Check for `display_manager is defined` before display manager roles

4. **Variable Naming**: Follow Ansible conventions:
   - Use lowercase with underscores: `desktop_environment`, `display_manager`
   - Prefix role-specific variables with the role name to avoid conflicts

### Code Style

- **YAML**: Use 2-space indentation consistently
- **Python**: Follow PEP 8 style guidelines
- **Makefile**: Use tabs for indentation (required by Make)
- **Shell Scripts**: Use shellcheck-compliant bash scripting

### Testing and Validation

1. **Before Making Changes**:
   - Run `make list-tags` to see available tags
   - Check role dependencies in requirements.yml
   - Validate YAML syntax with ansible linters if available

2. **Testing Changes**:
   - Use `make configure TAGS="tag_name"` to test specific roles
   - Test on a VM or container before applying to production systems
   - Verify idempotency (running playbook twice should be safe)

## PR Review Guidelines

Copilot should use the following checklist when reviewing pull requests. Focus on **correctness and safety** — this playbook runs on real machines that people depend on.

### MUST check (flag as blocking)

1. **Every new role in play.yml has a matching tag**: Roles without tags cannot be selectively tested or skipped. Tag name should match the role name.
2. **OS conditionals are correct**: Arch-only roles use `when: _is_arch`, Debian-only roles use `when: not _is_arch`, desktop roles use `when: _has_display`. Profile roles use `when: _is_i3`, `_is_hyprland`, etc. Do NOT use raw `ansible_os_family` checks in play.yml — use the pre-resolved `_is_arch` fact.
3. **New variables have defaults**: Every variable a role reads MUST have an entry in `defaults/main.yml`. Optional variables default to `null`, not omitted. Machine-specific variables must also appear as commented-out examples in `group_vars/templates/desktop.yml` and `group_vars/templates/server.yml`.
4. **No hardcoded secrets or tokens**: No API keys, passwords, or tokens in plain text. Use environment variables, `ansible-vault`, or secret references.
5. **Idempotency**: Tasks should produce the same result when run twice. Watch for `command`/`shell` tasks without `creates` or `changed_when` guards. Template/file tasks are generally fine.
6. **Privilege escalation**: Never run the playbook as root. Use `become: true` on individual tasks that need it, not globally.
7. **YAML syntax**: 2-space indentation, no tabs in YAML. Check for trailing whitespace and missing `---` document starts in playbooks.

### SHOULD check (flag as suggestion)

1. **Template vs copy**: Prefer `template` (Jinja2) over `copy` for config files that need variable interpolation. Use `copy` only for static files.
2. **Handler correctness**: Any task that restarts a service must `notify` a handler. Handlers should be defined in `handlers/main.yml`, not inline.
3. **Package manager consistency**: Development tools go through Homebrew where possible. System packages use the OS-native manager. AUR packages are separate (`make aur`).
4. **Profile Dispatcher compatibility**: New desktop/display roles must integrate with the profile dispatcher (`scripts/profile_dispatcher.py`). New profile flags need corresponding `--disable-*` args in the playbook's `pre_tasks`.
5. **Backward compatibility**: Changes to existing roles must not break existing deployments. Adding new defaults is fine; changing existing defaults needs careful consideration.

### IGNORE (do not flag)

- Cosmetic YAML formatting differences that don't affect execution
- Suggestions to add comments to self-explanatory tasks
- Requests to split large roles into smaller ones unless clearly warranted
- Style suggestions that differ from existing patterns in the repo
- General Ansible best practices that don't apply to this specific change

### Review Tone

- Be concise. One sentence per finding, with file:line reference.
- Severity: BLOCK (must fix before merge), WARN (should fix), SUGGEST (nice to have).
- Don't explain Ansible basics. The maintainers know Ansible.
- Don't suggest unrelated improvements. Review only the diff.

### Common Tasks

#### Adding a New Role

1. Create role directory in `roles/` or add to requirements.yml
2. Add role to play.yml with appropriate tags and conditions
3. Update documentation if the role adds new functionality
4. Test the role independently using tags

#### Modifying the Playbook

1. Always maintain backward compatibility
2. Use tags for all new roles
3. Add appropriate conditionals for OS or environment-specific roles
4. Update README.md if user-facing functionality changes

#### Working with Variables

1. Host-specific variables go in `group_vars/`
2. Role defaults go in `roles/role_name/defaults/main.yml`
3. Sensitive data should never be committed (use Ansible Vault)

### Makefile Targets

- `make bootstrap`: Install Ansible (requires pip)
- `make install`: Install roles from ansible-galaxy
- `make configure`: Run the full playbook (prompts for sudo password)
- `make configure TAGS="tag1,tag2"`: Run specific roles only
- `make list-tags`: List all available tags in the playbook
- `make help`: Show all available targets

### Important Notes

1. **Privilege Escalation**: The playbook uses `--ask-become-pass` to prompt for sudo password. Never run as root directly.

2. **Supported Systems**:
   - Primary: Arch Linux
   - Secondary: Debian-based systems
   - Some roles are OS-specific (check conditionals)

3. **Desktop Environments**:
   - i3 (X11-based)
   - Hyprland (Wayland-based)
   - GNOME
   - AwesomeWM

4. **Dependencies**:
   - Python 3 and pip must be installed before running make bootstrap
   - User account must have sudo privileges

## Error Handling

- If ansible-galaxy fails, check internet connectivity and requirements.yml syntax
- If a role fails, run with specific tag to isolate the issue
- Check Ansible version compatibility (this repo expects Ansible 2.x)
- For AUR packages on Arch, use `make aur` separately as it requires additional setup

## Contributing

When modifying this repository:
- Keep changes minimal and focused
- Test changes with tags before running full playbook
- Update documentation for user-facing changes
- Maintain compatibility with both Arch and Debian where possible
- Follow existing code style and conventions
