#!/usr/bin/env bash
#
# install.sh — automated Arch Linux base install (INSTALL.md).
#
# Produces the exact layout INSTALL.md describes:
#   * GPT with a 1MiB BIOS-boot partition, 512MiB EFI (FAT32), and a
#     LUKS2 (pbkdf2) root partition holding LVM volume group `arch`
#     (swap + ext4 root)
#   * encrypted /boot via GRUB cryptodisk; bootable via UEFI and legacy BIOS
#   * pacstrap package list from INSTALL.md, en_US.UTF-8 + en_SE.UTF-8
#     (LC_TIME) locales, prompted timezone (default America/Los_Angeles)
#   * wheel-sudo regular user; my-configuration pre-cloned to
#     ~<user>/my-configuration for the playbook
#
# Usage — from the Arch install ISO root shell, with network up:
#   # curl -fsSL https://zipline.thenewmans.casa/go/arch | bash
#   # (same script via GitHub, if the shortener is ever down:)
#   # curl -fsSL https://raw.githubusercontent.com/floatingman/my-configuration/main/install.sh | bash
#   # (download-first equivalent, if you prefer inspecting before running:)
#   # curl -fsSL .../install.sh -o /tmp/install.sh && less /tmp/install.sh && bash /tmp/install.sh
#   # or copy this repo to a second USB stick and run:
#   # bash /mnt/my-configuration/install.sh
#
# Everything is prompted; nothing is written until you confirm the target
# disk by typing YES (this wipes the disk). HiDPI consoles: run
# `setfont sun12x22` first. On newer systems (e.g. Dell XPS 15), set SATA
# operation mode to AHCI before booting the ISO.
#
# Never run this on a working system: it destroys the target disk's partition
# table and filesystems.

set -euo pipefail
trap 'echo "ERROR: install failed at line $LINENO" >&2' ERR

err() { printf 'error: %s\n' "$*" >&2; exit 1; }
log() { printf '\n==> %s\n' "$*"; }

# --- guards -----------------------------------------------------------------

[[ ${EUID} -eq 0 ]] || err 'run this as root from the Arch install ISO shell'
command -v pacstrap >/dev/null 2>&1 \
  || err 'pacstrap not found — run from the Arch install ISO, not a live system'
curl -fsSI --max-time 10 https://archlinux.org/ >/dev/null 2>&1 \
  || err 'no network — connect first (wifi: iwctl; see INSTALL.md)'

timedatectl set-ntp true

# --- prompts ----------------------------------------------------------------

log 'Disks on this machine'
lsblk -dno NAME,SIZE,TYPE,MODEL

read -rp 'Target disk (e.g. /dev/nvme0n1): ' DISK
[[ ${DISK} == /dev/* ]] || DISK="/dev/${DISK}"
[[ -b ${DISK} ]] || err "${DISK} is not a block device"

read -rp "THIS WIPES ${DISK} COMPLETELY. Type YES to continue: " CONFIRM
[[ ${CONFIRM} == 'YES' ]] || err 'aborted (nothing was written)'

read -rp 'Hostname [mymachine]: ' HOSTNAME_IN
HOSTNAME_IN=${HOSTNAME_IN:-mymachine}
[[ ${HOSTNAME_IN} =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] \
  || err "invalid hostname: ${HOSTNAME_IN}"

read -rp 'Username for the regular (wheel/sudo) user: ' USERNAME_IN
[[ ${USERNAME_IN} =~ ^[a-z_][a-z0-9_-]*$ ]] \
  || err "invalid username: ${USERNAME_IN}"

# Swap default: RAM x 1.5 (INSTALL.md's hibernate rule), rounded up to the
# next whole GiB — e.g. 32GiB RAM -> 48G. Override by typing another size.
MEM_BYTES=$(awk '/^MemTotal:/{print $2 * 1024}' /proc/meminfo)
SWAP_DEFAULT=$(( (MEM_BYTES * 3 + (1 << 30)) / 2 >> 30 ))G
read -rp "Swap size [${SWAP_DEFAULT}]: " SWAP_SIZE
SWAP_SIZE=${SWAP_SIZE:-${SWAP_DEFAULT}}

read -rp 'Timezone [America/Los_Angeles]: ' TIMEZONE_IN
TIMEZONE_IN=${TIMEZONE_IN:-America/Los_Angeles}
[[ -e /usr/share/zoneinfo/${TIMEZONE_IN} ]] \
  || err "unknown timezone: ${TIMEZONE_IN} (e.g. America/Los_Angeles)"

prompt_secret() { # prompt_secret <varname> <label>
  local var=$1 label=$2 p1 p2
  while :; do
    read -rsp "${label}: " p1; echo
    [[ -n ${p1} ]] || { echo '  must not be empty'; continue; }
    read -rsp "Confirm ${label}: " p2; echo
    [[ ${p1} == "${p2}" ]] && break
    echo '  entries do not match, try again'
  done
  printf -v "${var}" '%s' "${p1}"
}

prompt_secret LUKS_PASSPHRASE 'LUKS passphrase'
prompt_secret ROOT_PASSWORD 'root password'
prompt_secret USER_PASSWORD "password for ${USERNAME_IN}"

# --- partitioning (INSTALL.md) ----------------------------------------------

case ${DISK} in
  /dev/nvme* | /dev/mmcblk* | /dev/loop*)
    DEVEFI="${DISK}p2"
    DEVCRYPT="${DISK}p3"
    ;;
  *)
    DEVEFI="${DISK}2"
    DEVCRYPT="${DISK}3"
    ;;
esac

log "Partitioning ${DISK} (BIOS-boot + EFI + LUKS root)"
parted -s "${DISK}" mklabel gpt
parted -s "${DISK}" mkpart primary 2048s 2MiB
parted -s "${DISK}" set 1 bios_grub on
parted -s "${DISK}" mkpart primary fat32 2MiB 515MiB
parted -s "${DISK}" set 2 boot on
parted -s "${DISK}" set 2 esp on
parted -s "${DISK}" mkpart primary 540MiB 100%

for _ in $(seq 1 10); do
  [[ -b ${DEVCRYPT} && -b ${DEVEFI} ]] && break
  sleep 1
done
[[ -b ${DEVCRYPT} ]] || err "partition ${DEVCRYPT} did not appear after partitioning"

# --- LUKS + LVM -------------------------------------------------------------

log "Creating LUKS2 container on ${DEVCRYPT}"
printf '%s' "${LUKS_PASSPHRASE}" \
  | cryptsetup luksFormat -q --type luks2 --pbkdf pbkdf2 -d - "${DEVCRYPT}"
printf '%s' "${LUKS_PASSPHRASE}" | cryptsetup luksOpen -d - "${DEVCRYPT}" lvm

log 'Creating LVM volumes (arch/swap + arch/root)'
pvcreate -y /dev/mapper/lvm
vgcreate -y arch /dev/mapper/lvm
lvcreate -y -L "${SWAP_SIZE}" arch -n swap
lvcreate -y -l +100%FREE arch -n root
lvreduce -y -L -256M arch/root

log 'Formatting and mounting'
mkswap -L swap /dev/mapper/arch-swap
mkfs.ext4 -F /dev/mapper/arch-root
mount /dev/mapper/arch-root /mnt
swapon /dev/mapper/arch-swap
mkdir /mnt/efi
mkfs.fat -F32 "${DEVEFI}"
mount "${DEVEFI}" /mnt/efi

# --- base system ------------------------------------------------------------

log 'pacstrap base system (this takes a while)'
pacstrap /mnt base base-devel linux linux-firmware lvm2 dhcpcd net-tools \
  wireless_tools dialog wpa_supplicant efibootmgr vim git grub ansible iwd \
  openssh sudo

log 'Generating /etc/fstab'
genfstab -U -p /mnt >> /mnt/etc/fstab
grep -q '/dev/mapper/arch-root' /mnt/etc/fstab \
  || err 'fstab generation failed (no root entry)'

# --- hand off values to the chroot stage ------------------------------------

# printf %q keeps arbitrary passwords safe to source; the file is chmod 600
# in the ISO environment and shredded at the end of the chroot stage.
{
  printf 'INSTALL_HOSTNAME=%q\n' "${HOSTNAME_IN}"
  printf 'INSTALL_USERNAME=%q\n' "${USERNAME_IN}"
  printf 'INSTALL_TIMEZONE=%q\n' "${TIMEZONE_IN}"
  printf 'INSTALL_DISK=%q\n' "${DISK}"
  printf 'INSTALL_DEVEFI=%q\n' "${DEVEFI}"
  printf 'INSTALL_DEVCRYPT=%q\n' "${DEVCRYPT}"
  printf 'INSTALL_LUKS_PASSPHRASE=%q\n' "${LUKS_PASSPHRASE}"
  printf 'INSTALL_ROOT_PASSWORD=%q\n' "${ROOT_PASSWORD}"
  printf 'INSTALL_USER_PASSWORD=%q\n' "${USER_PASSWORD}"
} > /mnt/.install-env
chmod 600 /mnt/.install-env

# The chroot stage runs via `arch-chroot /mnt bash /arch-chroot-stage.sh`,
# so it needs no shebang; the shellcheck directive keeps it lintable.
cat > /mnt/arch-chroot-stage.sh <<'__CHROOT_STAGE__'
#__CHROOT_BEGIN__
# shellcheck shell=bash
# Chroot stage of arch-install.sh — runs inside the new system (arch-chroot).
set -euo pipefail
trap 'echo "ERROR: chroot configuration failed at line $LINENO" >&2' ERR

log() { printf '\n==> %s\n' "$*"; }

set -a
# shellcheck disable=SC1091  # /.install-env is generated at install time
. /.install-env
set +a

log "Locale and timezone (${INSTALL_TIMEZONE})"
# glibc >= 2.33 ships a real en_SE locale; the en_DK symlink is only the
# fallback for older systems (INSTALL.md's original trick).
[[ -e /usr/share/i18n/locales/en_SE ]] \
  || ln -s /usr/share/i18n/locales/en_DK /usr/share/i18n/locales/en_SE
printf 'en_US.UTF-8 UTF-8\nen_SE.UTF-8 UTF-8\n' >> /etc/locale.gen
locale-gen
printf 'LANG=en_US.UTF-8\nLC_TIME=en_SE.UTF-8\n' > /etc/locale.conf
ln -fs "/usr/share/zoneinfo/${INSTALL_TIMEZONE}" /etc/localtime
hwclock --systohc --utc

log "Hostname: ${INSTALL_HOSTNAME}"
echo "${INSTALL_HOSTNAME}" > /etc/hostname
systemctl enable dhcpcd.service

log 'Root and regular user accounts'
printf 'root:%s\n' "${INSTALL_ROOT_PASSWORD}" | chpasswd
useradd -m -G wheel "${INSTALL_USERNAME}"
printf '%s:%s\n' "${INSTALL_USERNAME}" "${INSTALL_USER_PASSWORD}" | chpasswd
printf '%%wheel ALL=(ALL) ALL\n' > /etc/sudoers.d/01_wheel
chmod 440 /etc/sudoers.d/01_wheel
visudo -cf /etc/sudoers.d/01_wheel >/dev/null

log 'mkinitcpio: encrypt/lvm2 hooks + LUKS keyfile'
# Match commented defaults (#HOOKS=(...)/#FILES=()) as well as uncommented ones.
sed -i -e 's|^HOOKS=.*|HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block encrypt lvm2 resume filesystems fsck)|' \
       -e 's|^#HOOKS=.*|HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block encrypt lvm2 resume filesystems fsck)|' \
       /etc/mkinitcpio.conf
grep -q '^HOOKS=.*encrypt' /etc/mkinitcpio.conf \
  || echo 'HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block encrypt lvm2 resume filesystems fsck)' >> /etc/mkinitcpio.conf

dd bs=512 count=8 if=/dev/urandom of=/crypto_keyfile.bin status=none
printf '%s' "${INSTALL_LUKS_PASSPHRASE}" \
  | cryptsetup luksAddKey -q -d - "${INSTALL_DEVCRYPT}" /crypto_keyfile.bin
chmod 000 /crypto_keyfile.bin

sed -i -e 's|^FILES=.*|FILES=(/crypto_keyfile.bin)|' \
       -e 's|^#FILES=.*|FILES=(/crypto_keyfile.bin)|' /etc/mkinitcpio.conf
grep -q '^FILES=(/crypto_keyfile.bin)' /etc/mkinitcpio.conf \
  || echo 'FILES=(/crypto_keyfile.bin)' >> /etc/mkinitcpio.conf

mkinitcpio -P

log 'GRUB: encrypted /boot, UEFI + legacy BIOS'
grep -q '^GRUB_ENABLE_CRYPTODISK=y' /etc/default/grub \
  || echo 'GRUB_ENABLE_CRYPTODISK=y' >> /etc/default/grub
ROOTUUID=$(blkid -s UUID -o value "${INSTALL_DEVCRYPT}")
sed -i "s|^GRUB_CMDLINE_LINUX=.*|GRUB_CMDLINE_LINUX=\"cryptdevice=UUID=${ROOTUUID}:lvm:allow-discards root=/dev/mapper/arch-root resume=/dev/mapper/arch-swap\"|" /etc/default/grub
grub-install --target=x86_64-efi --efi-directory=/efi --bootloader-id=GRUB --recheck --removable
grub-install --target=i386-pc --recheck "${INSTALL_DISK}"
grub-mkconfig -o /boot/grub/grub.cfg
chmod -R g-rwx,o-rwx /boot

log "Pre-cloning my-configuration for ${INSTALL_USERNAME}"
runuser -u "${INSTALL_USERNAME}" -- \
  git -C "/home/${INSTALL_USERNAME}" clone \
  https://github.com/floatingman/my-configuration.git \
  || echo 'warning: pre-clone failed — clone the repo manually after reboot'

shred -u /.install-env
echo 'Chroot stage complete.'
#__CHROOT_END__
__CHROOT_STAGE__

log 'Running chroot configuration stage'
arch-chroot /mnt bash /arch-chroot-stage.sh
rm -f /mnt/arch-chroot-stage.sh

# --- done -------------------------------------------------------------------

log 'Unmounting'
umount -R /mnt

cat <<EOF

Install complete. Next steps:

  1. reboot (remove the USB stick). The GRUB/disk passphrase is your LUKS
     passphrase.
  2. Log in as ${USERNAME_IN} and run the playbook:

         cd ~/my-configuration
         make setup && exec \$SHELL -l
         make install
         cp group_vars/templates/desktop.yml group_vars/all/local.yml
         make configure

EOF
