# Rust Role

This role installs Rust and Cargo packages on the system.

## What it does

1. Installs Rust using rustup (the official Rust installer)
2. Configures the stable Rust toolchain as default
3. Adds cargo to the user's PATH in bashrc and fish config (if fish is installed)
4. Installs specified Cargo packages

## Variables

### `cargo_packages`

A list of cargo packages to install. Each package should be the name of a crate available on crates.io.

Default: `[]` (empty list)

Example:
```yaml
cargo_packages:
  - ripgrep
  - fd-find
  - bat
  - exa
  - tokei
  - starship
  - zoxide
```

## Usage

Add the role to your playbook:

```yaml
- { role: rust, tags: ["rust"] }
```

Configure packages in your group_vars or host_vars:

```yaml
cargo_packages:
  - ripgrep  # Fast grep alternative
  - fd-find  # Fast find alternative
  - bat      # Cat with syntax highlighting
  - exa      # Modern ls replacement
```

## Tags

- `rust`: Apply all tasks in this role

## Requirements

- Internet connection to download rustup and cargo packages
- User account with home directory

## Notes

- The role is idempotent - it checks if rustup is already installed and if cargo packages are already installed before attempting installation
- Cargo packages are installed per-user in `~/.cargo/bin/`
- The role supports both bash and fish shells for PATH configuration
