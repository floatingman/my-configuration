The following is a brief installation tutorial for [Arch Linux][1]. It assumes
familiarity with the Arch [Installation Guide][2].

It will provide a system with full-disk encryption using [LVM on LUKS][3],
a [Plymouth][4]-themed boot splash and LUKS password prompt, and a
[Vimix][6]-themed GRUB menu. `/boot` lives on the (unencrypted) EFI
partition so the passphrase is asked by Plymouth — GRUB's own cryptodisk
prompt, shown before any theme loads, cannot be themed. The system will be
bootable via both UEFI and legacy BIOS.

On some newer systems (e.g. Dell XPS 15), set SATA operation mode to AHCI.

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

    $ cryptsetup luksFormat --type luks2 --pbkdf pbkdf2 $DEVCRYPT
    $ cryptsetup luksOpen $DEVCRYPT lvm
    $ pvcreate /dev/mapper/lvm
    $ vgcreate arch /dev/mapper/lvm
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

    $ pacstrap -i /mnt base base-devel linux linux-firmware lvm2 dhcpcd net-tools wireless_tools dialog wpa_supplicant efibootmgr vi git grub plymouth ansible

Generate and verify fstab.

    $ genfstab -U -p /mnt >> /mnt/etc/fstab
    $ less /mnt/etc/fstab

Change root into the base install and perform base configuration tasks.

    $ arch-chroot /mnt /bin/bash
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

Set your mkinitcpio hooks: `plymouth` draws the splash and password dialog,
and `encrypt`/`lvm2` open the root volume. The `encrypt` hook routes its
passphrase prompt through Plymouth automatically, so no keyfile is needed.

    $ sed -i 's/^HOOKS=.*/HOOKS=(base udev plymouth autodetect microcode modconf kms keyboard keymap consolefont block encrypt lvm2 resume filesystems fsck)/' /etc/mkinitcpio.conf
    $ mkinitcpio -P

Install the Vimix theme (generated from [grub2-themes][6]) and configure
GRUB. `chmod -x 31_efi_bootnext` stops GRUB from mirroring the firmware's
~20 native boot entries (Setup, diagnostics, USB/NVMe/ATA, ...) into the
menu; `quiet splash` hands the console over to Plymouth early.

    $ git clone --depth 1 https://github.com/vinceliuice/grub2-themes /tmp/grub2-themes
    $ /tmp/grub2-themes/install.sh -t vimix -i color -s 1080p -g /tmp/theme
    $ mkdir -p /boot/grub/themes
    $ cp -r /tmp/theme/vimix /boot/grub/themes/
    $ chmod -x /etc/grub.d/31_efi_bootnext
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

Run ansible!


[1]: https://www.archlinux.org/
[2]: https://wiki.archlinux.org/index.php/Installation_guide
[3]: https://wiki.archlinux.org/index.php/Dm-crypt/Encrypting_an_entire_system#LVM_on_LUKS
[4]: https://wiki.archlinux.org/title/Plymouth
[5]: https://wiki.archlinux.org/index.php/HiDPI
[6]: https://github.com/vinceliuice/grub2-themes
