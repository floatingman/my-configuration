# gaming

Fedora gaming stack, installed via the opt-in `gaming` overlay
(`profiles/overlays/gaming.yml`). The role is a no-op on non-Fedora hosts:
`tasks/main.yml` includes `tasks/fedora.yml` only when
`ansible_facts['os_family'] == "RedHat"`, so adding `gaming: true` on an
Arch or Debian machine installs nothing.

The role keeps the stock Fedora Mesa drivers and the stock (OEM) kernel.
It installs no graphics or kernel packages; hardware-specific GPU driver
setup stays out of scope.

## What gets installed

| Component | Source | When |
| --- | --- | --- |
| Steam | Flathub `com.valvesoftware.Steam`, or RPM Fusion `steam` RPM | always (method selectable) |
| Heroic Games Launcher | Flathub `com.heroicgameslauncher.hgl` | always |
| MangoHud | Fedora package `mangohud` | `gaming_mangohud: true` |
| GameMode | Fedora package `gamemode` | `gaming_gamemode: true` |
| RPM Fusion nonfree repo | `rpmfusion-nonfree-release` | only `gaming_enable_rpmfusion: true` |

Package and app IDs were verified against packages.fedoraproject.org
(`mangohud`, `gamemode`), RPM Fusion docs (`steam` is nonfree-only), and
Flathub (`com.valvesoftware.Steam`, `com.heroicgameslauncher.hgl`).

## Steam: Flatpak (default) vs RPM Fusion RPM

The default is `gaming_steam_install_method: flatpak`, because the RPM
Fusion `steam` package does not exist in Fedora's own repos, and the
default configuration must never add a third-party repository:

- **Flatpak (default)**: works on stock Fedora with no third-party repos;
  Flathub is added by the `flatpak` role's tasks (already present for every
  desktop profile). Sandboxed from the host package set. The known
  trade-off is that 32-bit graphics drivers inside the runtime can lag the
  host stack, which occasionally matters for older native titles.
- **RPM (`gaming_steam_install_method: rpm`)**: uses the host graphics
  stack and updates through dnf, but requires RPM Fusion nonfree. The role
  therefore refuses to install the RPM unless `gaming_enable_rpmfusion:
  true` is also set; both flags must be opted into explicitly.

The RPM Fusion repo task is guarded with `creates:
/etc/yum.repos.d/rpmfusion-nonfree.repo`, so it runs once and is idempotent.
No other task touches third-party sources; MangoHud and GameMode come from
Fedora's own repos.

## Variables (defaults/main.yml)

| Variable | Default | Purpose |
| --- | --- | --- |
| `gaming_steam_install_method` | `flatpak` | `"flatpak"` or `"rpm"` (see above) |
| `gaming_enable_rpmfusion` | `false` | Opt-in to RPM Fusion nonfree repo; required for the `rpm` Steam method |
| `gaming_mangohud` | `false` | Install MangoHud overlay (`mangohud %command%`) |
| `gaming_gamemode` | `false` | Install GameMode daemon (`gamemoderun %command%`) |

## Enabling

Machine-specific flags belong in `group_vars/all/local.yml` (gitignored).
Example block:

```yaml
# --- gaming (Fedora gaming overlay; see roles/gaming/README.md) ---
gaming: true                          # activates profiles/overlays/gaming.yml
gaming_steam_install_method: flatpak  # "flatpak" (default) or "rpm" (needs RPM Fusion)
gaming_enable_rpmfusion: false        # true adds RPM Fusion nonfree (required for the rpm method)
gaming_mangohud: false                # true installs MangoHud
gaming_gamemode: false                # true installs GameMode
```

Then run the playbook with the `gaming` tag (or a full configure run).
