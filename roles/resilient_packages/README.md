# resilient_packages

Resilient Arch Linux package installation as a reusable include-role. It
exists to handle the dominant fresh-machine failure class directly: a
package has been renamed, or has moved between the AUR and the official
pacman repos, and a plain batch install then dies mid-playbook.

## What it does

For every entry in `resilient_packages_list`:

1. already installed -> nothing to do
2. available in an official repo -> installed with `pacman`
   (entries that are not literal repo names get a second chance via
   `pacman -S --print-format %n`, so provides aliases like `cron` ->
   `cronie` and version specs like `pkg>=1.2` resolve from the repos the
   way `ansible.builtin.package` used to resolve them)
3. available in the AUR -> installed with `yay` (as `aur_builder`)
4. found in **neither** source -> recorded in the end-of-run resilience
   report (`kind: package`) as a likely rename/removal, and the run
   continues

`yay` and the `aur_builder` user plus its sudoers rule are ensured on
demand (same bootstrap the `base` and `aur` roles perform). The repo leg
runs before the AUR leg, so an AUR-side bootstrap problem can never block
official-repo packages; `yay` itself is installed from whichever source
has it (official repo copy if present, otherwise built from the AUR via
`kewlfft.aur`, which falls back to makepkg).

## Usage

Include from any role:

```yaml
- name: Install my packages resiliently
  ansible.builtin.include_role:
    name: resilient_packages
  vars:
    resilient_packages_list: "{{ my_role_packages }}"
    resilient_packages_owner: my_role
```

`resilient_packages_owner` must be the name of the *including* role so that
`make rerun-failed` re-runs the right role tag after a package name has been
fixed.

Current users: `roles/base` (`base_packages`) and `roles/aur`
(`aur.packages`). Other roles can adopt it the same way; until they do,
their package batches are still protected by the playbook-level
block/rescue wrappers (a failed batch is rescued and reported instead of
aborting the run).

## Variables

| Variable                     | Default                 | Purpose                                            |
| ---------------------------- | ----------------------- | -------------------------------------------------- |
| `resilient_packages_list`    | `[]`                    | Package names to install                            |
| `resilient_packages_owner`   | `resilient_packages`    | Role name recorded in the resilience report         |

Arch Linux only; every task is a no-op on other OS families.
