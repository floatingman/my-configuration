# Rust Role

This role installs Rust and Cargo **system-wide** so that every user on the machine can access the Rust toolchain and cargo-installed binaries. It uses rustup with explicit `RUSTUP_HOME` and `CARGO_HOME` locations under `/opt/rust`, and exposes the tools on PATH for all login shells via `/etc/profile.d/rust.sh`.

## Installation Layout

| Path | Contents |
|------|----------|
| `/opt/rust` (`RUSTUP_HOME`) | rustup data + toolchains (owner `root:devtools`, mode `2775`) |
| `/opt/rust/cargo` (`CARGO_HOME`) | cargo registry, cache, and the rustup-managed proxy binaries (`cargo`, `rustc`, `rustup`) |
| `/opt/rust/cargo/bin` | The executables placed on PATH |
| `/etc/profile.d/rust.sh` | Exports `RUSTUP_HOME`, `CARGO_HOME`, and adds `$CARGO_HOME/bin` to PATH for all login shells |

The installation is owned by `root:devtools` with mode `2775` (group-writable + setgid). Add users to the `devtools` group to grant them write access for installing additional crates; all users can read and execute the tools.

## What This Role Does

1. **Installs build dependencies** — `build-essential`, `pkg-config`, `libssl-dev`, `curl`, `ca-certificates` on Debian; `base-devel`, `openssl`, `pkgconf`, `ca-certificates` on Arch. These are required to compile crates from source.
2. **Checks for an existing install** — by testing for `/opt/rust/cargo/bin/rustup` (where rustup actually installs its own binary; *not* `$RUSTUP_HOME/bin/rustup`).
3. **Creates** `/opt/rust`, `/opt/rust/cargo`, and `/opt/rust/cargo/bin` with the correct ownership.
4. **Downloads and runs rustup-init** with `--default-toolchain stable --no-modify-path --profile minimal`, pinned to the system-wide `RUSTUP_HOME`/`CARGO_HOME`.
5. **Sets ownership** of the whole tree to `root:devtools` (mode `2775`).
6. **Writes `/etc/profile.d/rust.sh`** so the tools are on PATH for every user.
7. **Installs cargo packages** from `rust_cargo_packages`, skipping any that are already installed. A single failing crate does **not** abort the playbook — failures are reported as warnings at the end.

## Variables

### `rust_cargo_packages`

A list of cargo packages (crates) to install. Default: `[]` (empty list).

```yaml
rust_cargo_packages:
  - ripgrep
  - fd-find
  - bat
  - starship
  - zoxide
  - cargo-edit
  - cargo-watch
  - cargo-audit
```

## Usage

Add the role to your playbook:

```yaml
- { role: rust, tags: ["rust"] }
```

Configure packages in your group_vars (see `group_vars/all/base.yml`):

```yaml
rust_cargo_packages:
  - cargo-edit
  - fd-find
```

## Tags

- `rust`: Apply all tasks in this role

## Requirements

- Internet connection to download rustup and crates from crates.io
- `sudo`/root access (the role installs to `/opt`)

## Notes

- **Idempotent.** The install check tests the correct path (`/opt/rust/cargo/bin/rustup`), and the `cargo install --list` check runs with the same `RUSTUP_HOME`/`CARGO_HOME` as the install, so already-installed crates are skipped. (Earlier versions checked the wrong path and rebuilt every crate on every run.)
- **Non-fatal crate failures.** If a crate fails to compile, the role logs a warning and continues instead of aborting the entire server configuration.
- **System-wide, not per-user.** Nothing is written to `~/.cargo` or `~/.bashrc`; all tools live under `/opt/rust` and are exposed via `/etc/profile.d/rust.sh`.
- **Manual usage.** To install a crate by hand after the role has run:
  ```bash
  sudo CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust cargo install <crate>
  ```

## License

MIT

## Author Information

Created for the my-configuration repository.
