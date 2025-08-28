# Cursor Theme Role

This Ansible role installs and manages Bibata cursor themes on Linux systems. It was converted from a PKGBUILD to provide configurable cursor theme installation across different distributions.

## Requirements

- Ansible 2.9 or higher
- Internet connection for downloading cursor themes
- `unarchive` module support

## Role Variables

### Default Variables

```yaml
cursor_theme:
  enabled: true                           # Enable/disable cursor theme installation
  variant: "Bibata-Modern-Classic"        # Cursor theme variant to install
  version: "2.0.6"                        # Version to install
  install_path: "/usr/share/icons"        # Installation directory
```

### Available Variants

- `Bibata-Modern-Classic`
- `Bibata-Modern-Ice`
- `Bibata-Original-Classic`
- `Bibata-Original-Ice`
- `Bibata-Modern-Amber`
- `Bibata-Original-Amber`

### Configuration Options

```yaml
cursor_theme:
  # Packages that conflict with cursor themes (automatically removed on Arch Linux)
  conflicts:
    - bibata-cursor-theme
    - bibata-cursor-theme-bin
    - xcursor-themes
  
  # GitHub repository information
  repo:
    owner: "ful1e5"
    name: "Bibata_Cursor"
    base_url: "https://github.com/ful1e5/Bibata_Cursor"
  
  # Temporary download directory
  temp_dir: "/tmp/cursor-theme"
```

## Dependencies

None.

## Example Playbook

```yaml
- hosts: desktop
  roles:
    - role: cursor-theme
      vars:
        cursor_theme:
          enabled: true
          variant: "Bibata-Modern-Ice"
          version: "2.0.6"
```

## Platform Support

- Arch Linux (with automatic conflict resolution)
- Ubuntu/Debian
- Other Linux distributions

## Features

- **Configurable variants**: Choose from multiple Bibata cursor theme variants
- **Version management**: Specify exact version to install
- **Conflict handling**: Automatically removes conflicting packages on Arch Linux
- **Cross-distribution**: Works on multiple Linux distributions
- **Idempotent**: Safe to run multiple times
- **Cleanup**: Automatically cleans up temporary files

## Original PKGBUILD

This role was converted from the following PKGBUILD:

```bash
pkgname=illogical-impulse-bibata-modern-classic-bin
pkgver=2.0.6
pkgrel=1
pkgdesc="Material Based Cursor Theme, installed for illogical-impulse dotfiles"
arch=('any')
url="https://github.com/ful1e5/Bibata_Cursor"
license=('GPL-3.0-or-later')
conflicts=("bibata-cursor-theme" "bibata-cursor-theme-bin")
options=('!strip')
_variant=Bibata-Modern-Classic
source=("${pkgname%-bin}-$pkgver.tar.xz::$url/releases/download/v$pkgver/$_variant.tar.xz")
sha256sums=('SKIP')

package() {
  install -dm755 "$pkgdir/usr/share/icons"
  cp -dr --no-preserve=mode $_variant "$pkgdir/usr/share/icons"
}
```

## License

GPL-3.0-or-later

## Author Information

This role was created by Daniel Newman as part of the my-configuration Ansible project.
