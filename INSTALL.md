The following is a brief installation tutorial for [Arch Linux][1]. It assumes
familiarity with the Arch [Installation Guide][2].

It will provide a system with full-disk encryption using [LVM on LUKS][3],
a [Plymouth][4]-themed boot splash and LUKS password prompt, and a
[Vimix][6]-themed GRUB menu. `/boot` lives on the (unencrypted) EFI
partition so the passphrase is asked by Plymouth — GRUB's own cryptodisk
prompt, shown before any theme loads, cannot be themed. The system will be
bootable via both UEFI and legacy BIOS.

On some newer systems (e.g. Dell XPS 15), set SATA operation mode to AHCI.

## Automated install

`install.sh` (repo root) automates everything below: partitioning, LUKS+LVM,
pacstrap, locales, GRUB + Plymouth theming, the wheel user, and a pre-clone of
`~<user>/my-configuration`. From the installer ISO (root shell, network up):

    # bash <(curl -fsSL https://zipline.thenewmans.casa/go/arch)
    (GitHub fallback: https://raw.githubusercontent.com/floatingman/my-configuration/main/install.sh)
or run it from a second USB stick holding this repo. It prompts for the
target disk (typing `YES` is required; the disk is wiped), LUKS/root/user
passwords, hostname, username, swap size (default calculated as RAM x 1.5,
rounded up to the next GiB), and timezone. SSH is enabled from first boot with
your GitHub public keys (installer-seeded), and `make first-boot` gives a
usable shell (base + ssh + shell + dotfiles) before the full
`make configure` run. The rest of this document is the manual equivalent, kept for reference
and debugging.

## Manual install

Boot into the Arch installer.

If your console font is tiny ([HiDPI][5] systems), set a new font.

    $ setfont sun12x22

Connect to the Internet.

Verify that the system clock is up to date.

    $ timedatectl set-ntp true

Store your destination disk in an environment variable.

    $ export DISK=/dev/nvme0n1

Create partitions for legacy boot, EFI, and root.

    $ parted -s $DISK mklabel gpt
    $ parted -s $DISK mkpart primary 2048s 2MiB
    $ parted -s $DISK set 1 bios_grub on
    $ parted -s $DISK mkpart primary fat32 2MiB 515MiB
    $ parted -s $DISK set 2 boot on
    $ parted -s $DISK set 2 esp on
    $ parted -s $DISK mkpart primary 540MiB 100%

Store your EFI and crypt devices in environment variables.

    # If you're using a NVME disk:
    $ export DEVEFI="$DISK"p2
    $ export DEVCRYPT="$DISK"p3
    # If you're using a SATA disk:
    $ export DEVEFI="$DISK"2
    $ export DEVCRYPT="$DISK"3

Create and mount the encrypted root filesystem.

    $ cryptsetup luksFormat --type luks2 $DEVCRYPT
    $ cryptsetup luksOpen $DEVCRYPT lvm
    $ pvcreate /dev/mapper/lvm
    $ vgcreate arch /dev/mapper/lvm
    # For sleep and hibernate to work, this size should be ram x 1.5
    $ lvcreate -L 8G arch -n swap
    $ lvcreate -l +100%FREE arch -n root
    $ lvreduce -L -256M arch/root
    $ lvdisplay
    $ mkswap -L swap /dev/mapper/arch-swap
    $ mkfs.ext4 /dev/mapper/arch-root
    $ mount /dev/mapper/arch-root /mnt
    $ swapon /dev/mapper/arch-swap

Format and mount the EFI partition. It also holds `/boot` (kernel,
initramfs, GRUB files, theme), so keep it at 512MiB or larger.

    $ mkdir /mnt/boot
    $ mkfs.fat -F32 $DEVEFI
    $ mount $DEVEFI /mnt/boot

Optionally edit the mirror list.

    $ vim /etc/pacman.d/mirrorlist

Install the base system.

    $ pacstrap -i /mnt base base-devel linux linux-firmware lvm2 dhcpcd net-tools wireless_tools dialog wpa_supplicant efibootmgr vim git grub plymouth ansible iwd openssh sudo

Generate and verify fstab.

    $ genfstab -U -p /mnt >> /mnt/etc/fstab
    $ less /mnt/etc/fstab

Change root into the base install and perform base configuration tasks.

    $ arch-chroot /mnt /bin/bash
    # Skip on glibc >= 2.33: a real en_SE locale is shipped and the symlink
    # fails with "File exists".
    $ ln -s /usr/share/i18n/locales/en_DK /usr/share/i18n/locales/en_SE
    $ export LANG=en_US.UTF-8
    $ export TIME=en_SE.UTF-8
    $ echo $LANG UTF-8 >> /etc/locale.gen
    $ echo $TIME UTF-8 >> /etc/locale.gen
    $ locale-gen
    $ echo LANG=$LANG > /etc/locale.conf
    $ echo LC_TIME=$TIME >> /etc/locale.conf
    $ ln -fs /usr/share/zoneinfo/America/Los_Angeles /etc/localtime
    $ hwclock --systohc --utc
    $ echo mymachine > /etc/hostname
    $ systemctl enable dhcpcd.service
    $ passwd

Create your regular user and grant it sudo. The playbook is designed to be run
as this user (never as root); it does not create or manage login passwords.

    $ useradd -m -G wheel <username>
    $ passwd <username>
    $ echo '%wheel ALL=(ALL) ALL' > /etc/sudoers.d/01_wheel
    $ chmod 440 /etc/sudoers.d/01_wheel

Set your mkinitcpio hooks: `plymouth` draws the splash and password dialog,
and `encrypt`/`lvm2` open the root volume. The `encrypt` hook routes its
passphrase prompt through Plymouth automatically, so no keyfile is needed.

    $ sed -i 's/^HOOKS=.*/HOOKS=(base udev plymouth autodetect microcode modconf kms keyboard keymap consolefont block encrypt lvm2 resume filesystems fsck)/' /etc/mkinitcpio.conf
    $ mkinitcpio -P

Install the Vimix theme (vendored in this repository under
`roles/grub/files/grub-themes/`; originally from [grub2-themes][6]) and
configure GRUB. `GRUB_DISABLE_BOOTNEXT=true` stops GRUB from mirroring
the firmware's ~20 native boot entries (Setup, diagnostics,
USB/NVMe/ATA, ...) into the menu, persistently (the grub package owns
the script, so chmod -x would be reverted on the next upgrade);
`quiet splash` hands the console over to Plymouth early.

    $ git clone --depth 1 https://github.com/floatingman/my-configuration /tmp/my-configuration
    $ mkdir -p /boot/grub/themes
    $ cp -r /tmp/my-configuration/roles/grub/files/grub-themes/vimix /boot/grub/themes/
    $ echo 'GRUB_DISABLE_BOOTNEXT=true' >> /etc/default/grub
    $ ROOTUUID=$(blkid -s UUID -o value $DEVCRYPT)
    $ sed -i "s/^GRUB_CMDLINE_LINUX=.*/GRUB_CMDLINE_LINUX=\"cryptdevice=UUID="$ROOTUUID":lvm:allow-discards root=\/dev\/mapper\/arch-root resume=\/dev\/mapper\/arch-swap\"/" /etc/default/grub
    $ sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash consoleblank=60"/' /etc/default/grub
    $ echo 'GRUB_THEME="/boot/grub/themes/vimix/theme.txt"' >> /etc/default/grub
    $ grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB --recheck --removable
    $ grub-install --target=i386-pc --recheck $DISK
    $ grub-mkconfig -o /boot/grub/grub.cfg

Cleanup and reboot!

    $ exit
    $ umount -R /mnt
    $ reboot

After rebooting into your new system, log in as a regular user and run the Ansible playbook!

## Migrating an existing machine

Machines installed before the themed-boot change keep `/boot` on the encrypted
root: GRUB unlocks it as a cryptodisk (its unthemeable passphrase prompt shows
before any theme loads) using a LUKS keyfile embedded in the initramfs. The
grub role's preflight asserts refuse to deploy onto that layout, so those
machines need a one-time migration to the current layout (`/boot` on the ESP,
no keyfile). Everything else (plymouth package and hook, theme, `quiet
splash`, BootNext disable) is converged by the playbook after the migration.

`scripts/migrate-boot-esp.sh` automates the steps below, with the same
preflights and ordering (device walk from the mounted root, keyslot
discovery, ESP free-space check). `--dry-run` prints the plan without
mutating anything and works as a regular user; the real run needs root and
prompts for the LUKS passphrase only inside `cryptsetup luksKillSlot`.

Run the following as root on the running machine, then reboot once. If the
reboot fails, recover the usual way (installer ISO, unlock, chroot); the
pre-migration `/boot` survives as `/boot.old` inside the encrypted root and
can be deleted once the new layout boots.

Identify the disk and crypt device with `lsblk -f`; `/.install-env` on the
installed system still records `INSTALL_DISK` and `INSTALL_DEVEFI` from
install day when present.

    $ export DISK=/dev/nvme0n1
    $ export DEVCRYPT="$DISK"p3

Drop the LUKS keyfile: strip it from `mkinitcpio.conf`, kill its keyslot
(prompts for your real passphrase), and delete the file. The keyslot must go
before the initramfs is rebuilt onto the unencrypted ESP.

    $ sed -i -e 's|^FILES=.*|FILES=()|' -e 's|^#FILES=.*|FILES=()|' /etc/mkinitcpio.conf
    $ for s in $(seq 0 31); do cryptsetup open --test-passphrase \
        --key-slot "$s" --key-file /crypto_keyfile.bin "$DEVCRYPT" 2>/dev/null \
        && echo "keyfile is slot $s"; done
    $ cryptsetup luksKillSlot "$DEVCRYPT" <slot>
    $ rm /crypto_keyfile.bin

Move `/boot` onto the ESP (mounted at `/efi` on the old layout):

    $ umount /efi
    $ mv /boot /boot.old
    $ mkdir /boot
    $ sed -i 's|[[:space:]]/efi[[:space:]]| /boot |' /etc/fstab
    $ rmdir /efi
    $ mount /boot

Copy the kernel images (and microcode images, when present) across —
`mkinitcpio -P` only rebuilds initramfs images and never places kernels.
Never copy the old initramfs: it embeds the keyfile.

    $ cp -a /boot.old/vmlinuz-* /boot/
    $ for f in /boot.old/*-ucode.img; do [[ -f "$f" ]] && cp -a "$f" /boot/; done

Regenerate the boot artifacts in their new location. `mkinitcpio -P` writes
keyfile-free images to the ESP; verify everything fits (512MiB holds one
kernel, two initramfs images, GRUB, and the theme).

    $ sed -i '/^GRUB_ENABLE_CRYPTODISK=/d' /etc/default/grub
    $ mkinitcpio -P
    $ df -h /boot
    $ grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB --recheck --removable
    $ grub-install --target=i386-pc --recheck "$DISK"
    $ grub-mkconfig -o /boot/grub/grub.cfg

Reboot: the GRUB menu is still unthemed and the LUKS prompt appears on the
console (the plymouth hook is not in place yet). Log in, set `grub_theme` and
`grub_kernel_parameters` in `group_vars/all/local.yml` (see the Boot section
of the machine templates), and run `make configure`: both preflight asserts
now pass and the grub role finishes the job; the next boot shows the themed
splash. Machines installed from the older INSTALL_DUAL_BOOT.md layout follow
the same steps.

## Running the Ansible Playbook

The playbook is designed to be run by a non-superuser account with sudo privileges.

1. Clone this repository:
   ```bash
   $ git clone https://github.com/floatingman/my-configuration.git
   $ cd my-configuration
   ```

2. Install pipx and Ansible (first time on a fresh machine):
   ```bash
   $ make setup          # installs pipx + ~/.local/bin on PATH + ansible
   $ exec $SHELL -l      # reload shell so PATH takes effect
   ```
   If `pipx` is already installed and only Ansible is missing, use `make bootstrap` instead.

3. Install required Ansible roles:
   ```bash
   $ make install
   ```

4. Configure your machine-specific variables:
   ```bash
   cp group_vars/templates/desktop.yml group_vars/all/local.yml
   # Edit hostname and any hardware-specific paths
   ```

5. Run the playbook (you will be prompted for your sudo password):
   ```bash
   $ make configure
   ```

The playbook will automatically escalate privileges for tasks that require root access (package installations, system configuration, etc.) while running user-level tasks with your regular account privileges.

A failing role does not abort the run: failures are rescued, collected, and summarized at the end (the run still exits non-zero). Fix what the summary lists and re-run just those roles with `make rerun-failed`. See [Error resilience](README.md#error-resilience-continue-past-minor-failures) in the README for the report format and tuning options.


[1]: https://www.archlinux.org/
[2]: https://wiki.archlinux.org/index.php/Installation_guide
[3]: https://wiki.archlinux.org/index.php/Dm-crypt/Encrypting_an_entire_system#LVM_on_LUKS
[4]: https://wiki.archlinux.org/title/Plymouth
[5]: https://wiki.archlinux.org/index.php/HiDPI
[6]: https://github.com/vinceliuice/grub2-themes
