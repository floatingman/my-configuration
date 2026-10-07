# Fresh-machine runbook

Hard-won knowledge from provisioning pristine machines. Errors that only
happen on a brand-new box are invisible on already-configured ones, because
years of playbook runs paper over the bootstrapping gaps. This file is the
map of the traps we have actually hit, how to recognize them, and the
invariants that keep them fixed.

## The workflow

1. Boot the Arch ISO, connect wifi (`iwctl` — profiles carry over to the
   installed system), run `install.sh` (see [INSTALL.md](INSTALL.md)).
2. First boot: SSH is already live, key-only, with your GitHub public keys
   seeded by the installer. Finish setup from another machine.
3. `make first-boot` — minutes: base + ssh + shell + dotfiles.
4. `make configure 2>&1 | tee configure.log` — everything else, with a
   readable log for post-mortems.

If `install.sh` fails mid-run, just run it again: it tears down stale mounts,
the open LUKS container, and LVM volumes before starting over. No reboot
needed.

## Traps we have hit

### aur_builder does not exist yet

**Symptom:** `failed to set permissions on the temporary files Ansible needs
to create when becoming an unprivileged user` on the first AUR task (grub
hook, archive, ...).

**Cause:** generated play order runs the `base` section (grub, archive use
`kewlfft.aur` + `become_user: aur_builder`) *before* the packages section
(`aur` role), which is what creates the `aur_builder` user. `setfacl` cannot
name a user that does not exist; the fallbacks (chown as non-root, common
group) all fail.

**Fix in place:** `roles/base/tasks/packages.yml` bootstraps the user and
its sudoers rule before any AUR task. Pinned by
`tests/test_fresh_machine_ordering.py` — if you reshuffle profiles/sections
and break the ordering, CI fails with the offenders listed.

### Ansible module tmp vs. 0700 home dirs

**Symptom:** the same "failed to set permissions" error (user exists), or
`failed to create remote module tmp path at dir '/tmp/ansible-<user>'
... permission denied`.

**Cause (three layers):**
- Ansible stages modules in `~/.ansible/tmp`, unreachable to `aur_builder`
  behind a 0700 home. Fix: `ansible_remote_tmp: /tmp/ansible-$USER` in
  `group_vars/all/base.yml`.
- Ansible creates per-module tmp dirs *as the become user*, which cannot
  `mkdir` inside the 0700 base dir. Fix: the first task in
  `roles/base/tasks/main.yml` sets the dir to 0770 with group `wheel`
  (both the invoking user and aur_builder are members).
- Keying the dir on the *configured* `user.name` lets a `sudo make
  configure` run create a root-owned `/tmp/ansible-<name>` that later
  normal runs cannot use. Fix: the path is keyed on the invoking `$USER`.
  If a machine ever shows this, `sudo rm -rf /tmp/ansible-*` once.

### Dead upstream sources behind healthy AUR packages

**Symptom:** an AUR package fails to build with a 404/403 on its `source=`
URL even though the AUR page shows it maintained and current.

**Cause:** maintainers pin vendor CDN URLs that the vendor later kills. Hit
so far: `hey-bin` (S3 403), `clion`/`clion-gdb`/`clion-lldb`
(`download-cf.jetbrains.com` 404), and repo-side, `pandoc-cli`/`shellcheck`
(the GHC library tree — 200+ haskell packages rebuilt on every GHC bump).

**Pattern fix:** install from the still-live vendor source directly in the
owning role (`hey` via GCS in `roles/shell/tasks/hey.yml`, `clion` via the
JetBrains CDN with a pinned sha256 in `roles/devtools/tasks/clion.yml`), add
the AUR package to the aur role's deprecated-removal list, and drop the
`aur.packages` entry. Reproduce with `makepkg -o` in a scratch dir before
blaming anything else.

### copy does not create parent directories

**Symptom:** `destination ... does not exist` on a fresh machine for a task
that works everywhere else.

**Cause:** `ansible.builtin.copy` needs the parent dir to exist; already-
configured machines have it from some earlier tool. Fix: precede with a
`file: state=directory` task (see `roles/devtools/tasks/clion.yml`).

### Don't pipe the installer into bash

`curl ... | bash` leaves the script's stdin as the pipe, so the first
interactive `read` dies (`install failed at line N`). The installer guards
against it, but use the supported form:

    bash <(curl -fsSL https://zipline.thenewmans.casa/go/arch)

## Debugging tips

- SSH in early (it is live from first boot) — console error transcription
  is the worst part of fresh-machine work.
- `make configure 2>&1 | tee configure.log` keeps evidence.
- Re-run single roles with `make TAGS=<role> configure`.
- `make check-sync` after touching `profiles/`; regenerate with
  `make generate-playbook`.
- CI now runs `ansible-lint` + `yamllint`; run `make lint` locally before
  pushing — the fqcn/var-naming classes slip through pytest otherwise.
