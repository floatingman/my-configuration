# Dotfiles Role

Manages user dotfiles with [chezmoi](https://www.chezmoi.io/). This role installs chezmoi and applies a dotfiles repository for the primary user.

This role is part of the `user_environment` overlay — it only runs when `user_environment` is `true` (the default). Set `user_environment: false` in `group_vars/all/local.yml` to skip it.

## What This Role Does

1. **Installs chezmoi**
   - On **Arch**, via the AUR (`kewlfft.aur.aur`, as `aur_builder`).
   - On **Debian/Ubuntu**, via Homebrew (`community.general.homebrew`). The linuxbrew bin dir is added to PATH explicitly because the Homebrew install runs before `/etc/profile.d` is sourced for the current shell.
2. **Pre-seeds the chezmoi config** (`~/.config/chezmoi/chezmoi.toml`) with `dotfiles_config.data` (see below), only when the file does not already exist.
3. **Initializes and applies the user's dotfiles** with:
   ```
   chezmoi init --apply --branch=<branch> -- <repo_url>
   ```
   Run as `{{ user.name }}`, with `HOME` and the linuxbrew bin dir on PATH.
4. **Generates the global gitconfig** from `templates/gitconfig.j2` into `/home/{{ user.name }}/.gitconfig`.

## How `chezmoi init` Works Here

chezmoi's `init` command takes the repo as a **positional** argument — it clones the repo into the source directory and (with `--apply`) runs `chezmoi apply` immediately. The `--source` flag sets the source *directory* (a filesystem path), **not** the repo URL, so it must not be used for the repo. The `--branch` flag selects the branch to check out.

Because the task uses `become_user: "{{ user.name }}"`, Ansible resets PATH to a minimal secure path that does not include `/home/linuxbrew/.linuxbrew/bin`. The task therefore sets `PATH` explicitly in its `environment` so the `chezmoi` binary is found.

Idempotency: on a second run, chezmoi detects the existing git repo in the source directory and skips the clone, but still runs `chezmoi apply` (which is idempotent).

The dotfiles' `.chezmoi.toml.tmpl` asks machine-specific questions with `promptBoolOnce`/`promptStringOnce`, which open `/dev/tty` and fail under Ansible (no TTY). `promptOnce` functions return a value already present in the config data without prompting, so the role pre-seeds `~/.config/chezmoi/chezmoi.toml` from `dotfiles_config.data` (with `force: false`) before `init`. **Every `promptOnce` key in the template must be covered by `dotfiles_config.data`**, otherwise init still fails. A successful init regenerates the config from the template and the values persist in it.

## Variables

### `dotfiles_config`

Required to enable the role. Defines the dotfiles repository.

```yaml
dotfiles_config:
  repo_url: "https://github.com/user/dotfiles.git"
  branch: main   # optional, defaults to main
  data:          # optional; pre-seeded into ~/.config/chezmoi/chezmoi.toml
    pi:          # before init (answers the template's promptOnce questions)
      enabled: true
      repo: "git@github.com:user/pi-dotfiles.git"
      reviewerRepo: "git@github.com:user/pi-reviewer.git"
```

`repo_url` may be a full URL or a `user/repo` shorthand (chezmoi guesses the GitHub URL for shorthands).

`data` holds chezmoi template data: top-level scalars go under `[data]`, one level of nested mappings under `[data.<key>]` (deeper nesting is not supported). Leave `data` unset only if the dotfiles repo's `.chezmoi.toml.tmpl` contains no `promptOnce` calls, or init will fail under Ansible.

The role also reads:

- `user.name`, `user.email`, `user.group` — the primary user (from `group_vars/all/base.yml`)
- `github_user` — used by the gitconfig template
- `gitconfig.*` — name, mail, delta, neovim_remote, meld flags (from `group_vars/all/base.yml`)
- `asdf_plugins` — asdf version pins (from `group_vars/all/base.yml`); rendered
  into `~/.tool-versions` (see Notes)

## Tags

- `dotfiles`: Apply all tasks in this role
- `aur`: The Arch chezmoi install task is also tagged `aur`

## Requirements

- The `homebrew` role must have run on Debian/Ubuntu (chezmoi is installed via Homebrew there)
- Internet access to clone the dotfiles repository
- A public dotfiles repo (or credentials configured for a private one)

## Notes

- The server template (`group_vars/templates/server.yml`) sets `dotfiles_config` using `user.githubuser`, so the repo URL resolves to `https://github.com/<githubuser>/dotfiles.git` by default.
- `~/.tool-versions` is **derived, not hand-edited**: the role renders it from
  `asdf_plugins` after `chezmoi init --apply`. The dotfiles repo no longer
  manages the path (its copy drifted and pinned uninstalled versions, breaking
  tools like helm); `.chezmoiignore` lists `.tool-versions`. Change pins in
  `group_vars/all/base.yml`, then re-run `make configure TAGS="dotfiles"` —
  the monthly bump bot keeps them current.

## License

MIT

## Author Information

Created for the my-configuration repository.
