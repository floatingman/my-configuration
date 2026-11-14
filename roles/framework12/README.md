# framework12

Hardware guard and diagnostics role for the **Framework Laptop 12** running the
**Fedora KDE Plasma OEM image** (issue #234, PR4). It skips cleanly on every
other machine, reports the state of the tablet-mode/rotation/sensor/input
stacks without mutating anything, installs and inventories `fwupd` (never
flashes firmware), and exposes the disruptive kernel/power/keyboard overrides
behind explicit, default-off variables.

## Identity guard

The role imports nothing and changes nothing unless all three hold:

| Check | Fact | Match |
| --- | --- | --- |
| Opt-in | `framework12_enabled` | `true` (default `false`) |
| Hardware | `ansible_facts['system_vendor']` | `Framework` |
| Hardware | `ansible_facts['product_name']` | contains `laptop 12` (case-insensitive) |
| Distro | `ansible_facts['distribution']` | `Fedora` |

Mismatching checks end the host cleanly (`meta: end_host`) with a report
message; a Framework 13/16 or a Fedora desktop that is not a Laptop 12 never
sees this role's tasks. The product-string match mirrors Framework's own
detector in `FrameworkComputer/linux-docs` (`fw-log-tool`), which matches
`laptop 12` against the DMI product string.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `framework12_enabled` | `false` | Master gate; role ends cleanly unless `true`. |
| `framework12_power_backend` | `null` | `null`/`ppd`: keep the Fedora OEM `power-profiles-daemon` (recommended). `tuned`: explicit switch to TuneD + its PPD shim. The two claim the same `net.hadess.PowerProfiles` D-Bus name; the role disables the OEM daemon before enabling the shim and never runs both. |
| `framework12_kernel_tablet_mode_fix` | `false` | Disruptive kernel override for the tablet-mode switch (dracut + modprobe driver ordering per Framework's Fedora doc, initramfs regeneration, reboot required, never rebooted automatically). |
| `framework12_keyboard_virtual_install` | `false` | Install the on-screen keyboard package matching the detected Plasma version (`plasma-keyboard` on Plasma >= 6.6, `maliit-keyboard` on older Plasma). Default keeps the OEM keyboard. |
| `framework12_tablet_pinctrl_module` | `null` | Escape hatch for the workaround's pinctrl module; `null` auto-detects (`pinctrl_intel_platform` for Core Series 3, `pinctrl_tigerlake` for 13th Gen) from product-name keywords. |

Machine values go into the gitignored `group_vars/all/local.yml`.

## What changes on a default run

1. `fwupd` installed (OEM image already ships it; idempotent no-op there).
2. Everything else is reporting: input-device inventory, tablet-mode switch
   stack (gpio-keys / soc_button_array / pinctrl), IIO sensor devices,
   iio-sensor-proxy state incl. the known 3.7 udev-rule regression, hwmon
   chips, sleep states, active power profile, and the fwupd device inventory
   with pending-update count.

## Package provenance

All package names verified against the Fedora packages site
(packages.fedoraproject.org, Fedora 44 stable channel) and Fedora dist-git:

| Package | Provides | Source |
| --- | --- | --- |
| `fwupd` | Firmware update daemon | packages.fedoraproject.org/pkgs/fwupd/fwupd |
| `tuned` | TuneD daemon | packages.fedoraproject.org/pkgs/tuned/tuned |
| `tuned-ppd` | PPD compatibility daemon (`tuned-ppd.service`) | packages.fedoraproject.org/pkgs/tuned/tuned-ppd; unit names in src.fedoraproject.org/rpms/tuned spec |
| `plasma-keyboard` | Virtual keyboard, Plasma >= 6.6 | packages.fedoraproject.org/pkgs/plasma-keyboard/plasma-keyboard |
| `maliit-keyboard` | Maliit Keyboard 2, Plasma < 6.6 | packages.fedoraproject.org/pkgs/maliit-keyboard/maliit-keyboard |

Deliberately NOT packaged here: `keyd` (not in Fedora official repos; AUR-only
so far), `fw-ectool` (Arch lane of `roles/laptop/tasks/framework.yml`), and
`iio-sensor-proxy` (OEM-shipped; the diagnostics report its absence and the
install command instead of installing it from a diagnostics-only include).

## Firmware policy (never flash)

The role never refreshes metadata, downloads, or flashes. The human hardware
lane applies firmware manually per the Framework Fedora KDE guide:

```
fwupdmgr refresh --force
fwupdmgr get-updates
fwupdmgr update
```

LVFS refuses updates at 100% battery; discharge to about 95%, plug AC back in,
and rerun.

## Virtual keyboard decision (Plasma detection runs first)

| Detected Plasma | Package | Activation |
| --- | --- | --- |
| >= 6.6 | `plasma-keyboard` | System Settings -> Keyboard -> Virtual Keyboard |
| 6.0 - 6.5 | `maliit-keyboard` | System Settings -> Keyboard -> Virtual Keyboard -> select Maliit |
| 5.x | `maliit-keyboard` | System Settings -> Input & Output -> Virtual Keyboard -> select Maliit |

## Tablet-mode kernel override

Only behind `framework12_kernel_tablet_mode_fix: true`. Writes
`/etc/dracut.conf.d/99-fw-tabletmode.conf` (`omit_drivers soc_button_array`,
`force_drivers <pinctrl>`) and `/etc/modprobe.d/99-fw-tabletmode.conf`
(`softdep soc_button_array pre: <pinctrl>`), notifies an initramfs
regeneration handler, and reports the required reboot. Variant mapping comes
from Framework's Fedora doc: Core Series 3 -> `pinctrl_intel_platform`,
13th Gen -> `pinctrl_tigerlake`; an unclassifiable product string writes
nothing and warns (set `framework12_tablet_pinctrl_module`).

## Wiring (for the integration slice, W5)

Role self-gates, so a bare line is already safe on every machine:

```yaml
  # profiles/kde.yml, Desktop Applications or optional section
  - { role: framework12, tags: [framework12], config_check: "framework12_enabled | default(false) | bool", section: optional }
```

Machine opt-in (`group_vars/all/local.yml`):

```yaml
framework12_enabled: true
# framework12_power_backend: tuned      # only with deliberate PPD->TuneD switch
# framework12_kernel_tablet_mode_fix: true
# framework12_keyboard_virtual_install: true
```

Complements the `laptop` overlay (laptop + backlight); no power or backlight
service is duplicated: the role mutates power services only in the explicit
`tuned` arm and reports (never disables) the OEM daemon otherwise. Commented
examples for `group_vars/templates/{desktop,server}.yml` belong to W5.

## Hardware checklist (human lane, record results in issue #234)

Run on the real Laptop 12 after a clean provisioning run; each line references
what the role's report shows:

- [ ] Keyboard and touchpad listed in input inventory (`Report sensor, tablet
      and input diagnostics`; touchpad reports as PixArt PIXA3854).
- [ ] Touchscreen detected; touch and gestures work in a Plasma Wayland
      session (manual test).
- [ ] Pen/stylus input detected (MPP 2.0 default; USI 2.0 requires the UEFI
      touchscreen-mode switch, not this role).
- [ ] Tablet-mode switch: fold the screen; `gpio-keys`/`soc_button_array`/
      pinctrl flags all true; rotation follows in KDE.
- [ ] On-screen keyboard appears in a text field in tablet mode.
- [ ] `iio-sensor-proxy` service active, version >= 3.8, accelerometer
      reported true; screen rotation works.
- [ ] Keyboard/touchpad disabled in tablet mode (OEM behavior; manual test).
- [ ] Brightness and audio work (manual; hwmon chips listed in the report).
- [ ] Suspend/resume works; sleep states line shows `s2idle` (Framework
      guidance) and the machine resumes.
- [ ] fwupd report lists devices; manual `fwupdmgr update` applied or
      confirmed clean.
- [ ] KDE still on Wayland after Ansible (`kwin_wayland` active; no xorg
      session was provisioned).
- [ ] Second provisioning run reports no unexpected changes (idempotency).
