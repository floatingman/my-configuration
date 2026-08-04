# Dotfiles Role

Manages user dotfiles with [chezmoi](https://www.chezmoi.io/). This role installs chezmoi and applies a dotfiles repository for the primary user.

This role is part of the `user_environment` overlay — it only runs when `user_environment` is `true` (the default). Set `user_environment: false` in `group_vars/all/local.yml` to skip it.

## What This Role Does

1. **Installs chezmoi**
   - On **Arch**, via the AUR (`kewlfft.aur.aur`, as `aur_builder`).
   - On **Debian/Ubuntu**, via Homebrew (`community.general.homebrew`). The linuxbrew bin dir is added to PATH explicitly because the Homebrew install runs before `/etc/profile.d` is sourced for the current shell.
2. **Initializes and applies the user's dotfiles** with:
   ```
   chezmoi init --apply --branch=<branch> -- <repo_url>
   ```
   Run as `{{ user.name }}`, with `HOME` and the linuxbrew bin dir on PATH.
3. **Generates the global gitconfig** from `templates/gitconfig.j2` into `/home/{{ user.name }}/.gitconfig`.

## How `chezmoi init` Works Here

chezmoi's `init` command takes the repo as a **positional** argument — it clones the repo into the source directory and (with `--apply`) runs `chezmoi apply` immediately. The `--source` flag sets the source *directory* (a filesystem path), **not** the repo URL, so it must not be used for the repo. The `--branch` flag selects the branch to check out.

Because the task uses `become_user: "{{ user.name }}"`, Ansible resets PATH to a minimal secure path that does not include `/home/linuxbrew/.linuxbrew/bin`. The task therefore sets `PATH` explicitly in its `environment` so the `chezmoi` binary is found.

Idempotency: on a second run, chezmoi detects the existing git repo in the source directory and skips the clone, but still runs `chezmoi apply` (which is idempotent).

## Variables

### `dotfiles_config`

Required to enable the role. Defines the dotfiles repository.

```yaml
dotfiles_config:
  repo_url: "https://github.com/user/dotfiles.git"
  branch: main   # optional, defaults to main
```

`repo_url` may be a full URL or a `user/repo` shorthand (chezmoi guesses the GitHub URL for shorthands).

The role also reads:

- `user.name`, `user.email`, `user.group` — the primary user (from `group_vars/all/base.yml`)
- `github_user` — used by the gitconfig template
- `gitconfig.*` — name, mail, delta, neovim_remote, meld flags (from `group_vars/all/base.yml`)

## Tags

- `dotfiles`: Apply all tasks in this role
- `aur`: The Arch chezmoi install task is also tagged `aur`

## Requirements

- The `homebrew` role must have run on Debian/Ubuntu (chezmoi is installed via Homebrew there)
- Internet access to clone the dotfiles repository
- A public dotfiles repo (or credentials configured for a private one)

## Notes

- The server template (`group_vars/templates/server.yml`) sets `dotfiles_config` using `user.githubuser`, so the repo URL resolves to `https://github.com/<githubuser>/dotfiles.git` by default.
- If you need to force a fresh re-clone, remove `~/.local/share/chezmoi` for the user and re-run `make configure TAGS="dotfiles"`.

## License

MIT

## Author Information

Created for the my-configuration repository.
