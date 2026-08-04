# Python Role

Installs Python tooling system-wide, split by OS family:

- **Arch** (`python-arch.yml`): `pipenv`, `pipx`, `black`, `python-docs`, and a set of Python utilities and GObject/GTK development libraries (`uv`, `gtk4`, `libadwaita`, `libsoup3`, `python-opencv`, etc.).
- **Debian/Ubuntu** (`python-debian.yml`): `python3`, `python3-pip`, `pipx`, `python3-venv`, `python3-dev`, and `build-essential`, plus PATH configuration so per-user `pipx`/`pip` installs are usable by all login shells.

## Why pipx matters here

`pipx` is the mechanism used to bootstrap Ansible itself (`make bootstrap` / `make setup`). On a fresh headless Ubuntu/WSL server, pipx is not present, so the Debian task file ensures it is installed during `make configure` as well, keeping the machine self-healing for future users.

## What the Debian Task File Does

1. **Installs** `python3`, `python3-pip`, `pipx`, `python3-venv`, `python3-dev`, `build-essential` via `apt`.
2. **Writes `/etc/profile.d/user_local_bin.sh`** so `~/.local/bin` (where pipx/pip place user executables) is on PATH for every login shell.
3. **Creates `~/.local/bin`** for the primary user.
4. **Runs `pipx ensurepath`** for the primary user so future interactive shells pick up `~/.local/bin`.

## Variables

This role reads:

- `user.name` — the primary user (from `group_vars/all/base.yml`)
- `user.group` — the primary user's group (defaults to `user.name` if unset)

No role-specific variables are defined; the Arch package list is hard-coded in `python-arch.yml`.

## Tags

- `python`: Apply all tasks in this role

## Usage

```yaml
- { role: python, tags: ["python"] }
```

## Fresh-Server Bootstrapping

This role keeps pipx present *after* Ansible is running. For the very first bootstrap on a fresh machine (before Ansible exists), use:

```bash
make setup          # installs pipx + PATH, then ansible via pipx
# open a new shell, then:
make install && make configure
```

See `scripts/bootstrap-pipx.sh` for the underlying bootstrap logic.

## License

MIT

## Author Information

Created for the my-configuration repository.
