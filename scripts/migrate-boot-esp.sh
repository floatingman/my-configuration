#!/usr/bin/env bash
#
# scripts/migrate-boot-esp.sh — one-reboot migration from the pre-themed-boot
# disk layout to the current one, automating the "Migrating an existing
# machine" runbook in INSTALL.md.
#
# From: /boot on the encrypted root, GRUB cryptodisk unlocking it with a LUKS
#       keyfile (/crypto_keyfile.bin) embedded in the initramfs; ESP at /efi.
# To:   /boot on the ESP, no cryptodisk, no keyfile. After the reboot, run the
#       playbook (grub role) to converge plymouth, the theme, and
#       `quiet splash`.
#
# Usage — on the running machine to migrate, from a checkout of this repo
# (the installer's pre-cloned ~/my-configuration works):
#   # sudo bash ~/my-configuration/scripts/migrate-boot-esp.sh [--dry-run]
#
# --dry-run runs every read-only preflight (device walk, keyslot discovery,
# free-space check) and prints the plan without mutating anything; it may be
# run as a regular user (keyslot discovery is skipped without root).
#
# The script never sees the LUKS passphrase: cryptsetup luksKillSlot prompts
# for it directly. Safe to re-run after a mid-migration failure — preflights
# tolerate already-completed steps. The pre-migration /boot survives as
# /boot.old inside the encrypted root and is the only rollback while the
# migration is unverified: delete it only after the new layout has booted
# successfully. Recovery from a failed reboot: installer ISO, unlock,
# chroot (INSTALL.md).

set -euo pipefail
trap 'echo "ERROR: migration failed at line $LINENO" >&2' ERR

err()  { printf 'error: %s\n' "$*" >&2; exit 1; }
log()  { printf '\n==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }

DRY_RUN=0
case ${1:-} in
  --dry-run) DRY_RUN=1 ;;
  '') ;;
  *) err "unknown argument: $1 (only --dry-run is supported)" ;;
esac

if (( DRY_RUN )); then
  [[ ${EUID} -eq 0 ]] || warn 'not root: keyslot discovery is skipped in this dry run'
else
  [[ ${EUID} -eq 0 ]] || err 'run this as root: sudo bash scripts/migrate-boot-esp.sh'
fi
[[ -t 0 ]] || err 'run this from an interactive terminal (confirmation and passphrase prompts)'

for cmd in findmnt lsblk cryptsetup mkinitcpio grub-install grub-mkconfig df du awk cp sed; do
  command -v "$cmd" >/dev/null 2>&1 || err "$cmd not found — run on the Arch machine being migrated"
done

KEYFILE=/crypto_keyfile.bin
MKINITCPIO_CONF=/etc/mkinitcpio.conf
GRUB_DEFAULT=/etc/default/grub
FSTAB=/etc/fstab

# --- preflight --------------------------------------------------------------

log 'Preflight: layout checks'

if findmnt -n /boot >/dev/null; then
  if [[ $(findmnt -no FSTYPE /boot) == vfat ]]; then
    if compgen -G '/boot/vmlinuz-*' >/dev/null && [[ -f /boot/grub/grub.cfg ]]; then
      err '/boot is already a vfat ESP mount with kernels and grub.cfg — this machine looks fully migrated; delete /boot.old only after a successful reboot, if it lingers'
    fi
    err '/boot is a vfat ESP mount without kernels/grub.cfg — an earlier migration did not complete. Keep /boot.old (it holds the only kernels) and finish the runbook in INSTALL.md: mount the ESP at /boot, copy vmlinuz-* from /boot.old, rebuild the initramfs, reinstall GRUB, regenerate grub.cfg'
  fi
  err '/boot is an unexpected mountpoint; refusing'
fi
[[ -e /boot.old ]] \
  && err '/boot.old exists — resolve it first (delete it only after a verified boot, or finish the partial migration per INSTALL.md)'

if ! findmnt -n /efi >/dev/null; then
  err 'the ESP is not mounted at /efi — mount it (mount /efi) and re-run'
fi
[[ $(findmnt -no FSTYPE /efi) == vfat ]] || err '/efi is mounted but not vfat — not the EFI partition'
awk '$2 == "/efi" { found = 1 } END { exit !found }' "$FSTAB" \
  || err 'no /efi entry in /etc/fstab — cannot repoint it to /boot'

# Walk from the mounted root up to the LUKS partition and its disk. Parents
# come from sysfs, not `lsblk -no PKNAME`: that column is empty for stacked
# device-mapper (LVM LV on a crypt dm) on util-linux 2.42.
kernel_name() { basename "$(readlink -f "$1")"; }
is_partition() { [[ -f /sys/class/block/$(kernel_name "$1")/partition ]]; }
parent_of() {
  local kname slave
  kname=$(kernel_name "$1")
  if [[ -d /sys/class/block/$kname/slaves ]]; then          # stacked dm (LVM on crypt)
    for slave in "/sys/class/block/$kname/slaves"/*; do
      slave=${slave##*/}
      if [[ -b /dev/$slave ]]; then printf '/dev/%s\n' "$slave"; return 0; fi
    done
    return 1
  fi
  if is_partition "$1"; then                                 # partition -> its disk
    printf '/dev/%s\n' "$(basename "$(dirname "$(readlink -f "/sys/class/block/$kname")")")"
    return 0
  fi
  return 1
}
cur=$(findmnt -no SOURCE /)
DEVCRYPT=
for _ in 1 2 3 4 5 6 7 8; do
  if is_partition "$cur"; then DEVCRYPT=$cur; break; fi
  prev=$cur
  cur=$(parent_of "$prev") || err "cannot walk from $prev up to a partition"
done
[[ -n $DEVCRYPT ]] || err "could not find the partition backing $(findmnt -no SOURCE /)"
[[ $(lsblk -dno FSTYPE "$DEVCRYPT") == crypto_LUKS ]] \
  || err "$DEVCRYPT is not the LUKS partition (fstype: $(lsblk -dno FSTYPE "$DEVCRYPT"))"
DISK=$(parent_of "$DEVCRYPT") || err "cannot find the disk behind $DEVCRYPT"
[[ $(lsblk -dno TYPE "$DISK") == disk ]] || err "$DISK is not a whole disk"

# Keyfile state (tolerates re-runs after the strip/kill already happened).
keyfile_in_conf=0
if grep -Eq '^FILES=.*crypto_keyfile\.bin' "$MKINITCPIO_CONF"; then keyfile_in_conf=1; fi
have_keyfile=0
if [[ -f $KEYFILE ]]; then have_keyfile=1; fi
if (( ! keyfile_in_conf && ! have_keyfile )); then
  warn 'no crypto_keyfile.bin reference or file found — keyslot surgery already done? Continuing with the layout move only'
fi

# Discover which LUKS keyslot(s) the keyfile opens (read-only).
probed=0
SLOTS=()
if (( have_keyfile && EUID == 0 )) && [[ -r $KEYFILE ]]; then
  probed=1
  log "Preflight: probing LUKS keyslots against $KEYFILE"
  for s in $(seq 0 31); do
    if cryptsetup open --test-passphrase --key-slot "$s" --key-file "$KEYFILE" "$DEVCRYPT" >/dev/null 2>&1; then
      SLOTS+=("$s")
    fi
  done
  if (( ${#SLOTS[@]} == 0 )); then
    warn "$KEYFILE opens no keyslot (already killed?); it will simply be deleted"
  fi
elif (( have_keyfile )); then
  warn "cannot read $KEYFILE as this user — keyslot discovery needs root"
fi

# Free-space check: everything that must live on the ESP afterwards. /boot is
# root-only on the old layout (chmod o-rwx), so a user dry run skips this.
need_kb=0
esp_avail_kb=0
if [[ -r /boot ]]; then
  boot_files=()
  for f in /boot/vmlinuz-* /boot/initramfs-*.img /boot/*-ucode.img; do
    if [[ -f $f ]]; then boot_files+=("$f"); fi
  done
  (( ${#boot_files[@]} > 0 )) || err 'no kernel or initramfs images found in /boot'
  need_kb=$(du -ck "${boot_files[@]}" | awk 'END { print $1 }')
  esp_avail_kb=$(df --output=avail /efi | awk 'NR == 2 { print $1 }')
  if (( need_kb + 51200 > esp_avail_kb )); then   # 50MiB margin
    err "ESP too small: ~$((need_kb / 1024))MiB of boot files + 50MiB margin vs $((esp_avail_kb / 1024))MiB free — shrink /boot (stale fallback initramfs?) or grow the ESP first"
  fi
else
  warn 'cannot read /boot as this user — space check skipped (run as root for the full plan)'
fi

grep -q '^HOOKS=.*encrypt' "$MKINITCPIO_CONF" \
  || warn 'no encrypt hook in HOOKS — the playbook will skip plymouth insertion on this machine'

# --- plan + confirmation ----------------------------------------------------

log 'Migration plan'
printf '  root device:     %s\n' "$(findmnt -no SOURCE /)"
printf '  LUKS partition:  %s\n' "$DEVCRYPT"
printf '  whole disk:      %s\n' "$DISK"
if (( need_kb > 0 )); then
  printf '  ESP:             %s at /efi -> /boot (vfat, %sMiB free)\n' "$(findmnt -no SOURCE /efi)" "$((esp_avail_kb / 1024))"
  printf '  boot files:      %sMiB (kernels + initramfs + microcode)\n' "$((need_kb / 1024))"
else
  printf '  ESP:             %s at /efi -> /boot (vfat)\n' "$(findmnt -no SOURCE /efi)"
fi
if (( ${#SLOTS[@]} )); then
  printf '  keyfile slots:   %s\n' "${SLOTS[*]}"
elif (( have_keyfile )); then
  if (( probed )); then printf '  keyfile slots:   none found (already killed?)\n'
  else printf '  keyfile slots:   not probed (needs root)\n'; fi
fi
printf '  steps: strip FILES=, kill keyslot(s) + delete %s, move /boot onto\n' "$KEYFILE"
printf '         the ESP, drop GRUB_ENABLE_CRYPTODISK, rebuild initramfs,\n'
printf '         reinstall GRUB (UEFI + BIOS), regenerate grub.cfg\n'
printf '  rollback:        /boot.old kept on the encrypted root\n'

if (( DRY_RUN )); then
  log 'dry run complete — no changes were made'
  exit 0
fi

printf '\nThis rewrites how this machine boots. Type YES to continue: '
read -r reply
[[ $reply == YES ]] || err 'aborted, nothing was changed'

# --- migration --------------------------------------------------------------

log '1/8 strip the keyfile from mkinitcpio.conf'
sed -i -e 's|^FILES=.*|FILES=()|' -e 's|^#FILES=.*|FILES=()|' "$MKINITCPIO_CONF"
grep -q '^FILES=()' "$MKINITCPIO_CONF" || err 'failed to reset FILES= in mkinitcpio.conf'

if (( have_keyfile )); then
  if (( ${#SLOTS[@]} )); then
    for s in "${SLOTS[@]}"; do
      log "2/8 kill LUKS keyslot $s (enter your LUKS passphrase when prompted)"
      cryptsetup luksKillSlot "$DEVCRYPT" "$s"
      if cryptsetup open --test-passphrase --key-slot "$s" --key-file "$KEYFILE" "$DEVCRYPT" >/dev/null 2>&1; then
        err "keyslot $s still opens with the keyfile — kill it by hand before rebooting"
      fi
    done
  else
    log '2/8 no keyslot to kill (none probed)'
  fi
  rm -f "$KEYFILE"
else
  log '2/8 keyfile already gone'
fi

log '3/8 move /boot onto the ESP'
umount /efi
mv /boot /boot.old
mkdir /boot
sed -i -E 's|^([[:space:]]*[^#[:space:]]+)[[:space:]]+/efi([[:space:]])|\1 /boot\2|' "$FSTAB"
awk '$2 == "/boot" { found = 1 } END { exit !found }' "$FSTAB" \
  || err 'fstab edit failed — point the ESP line at /boot by hand (watch leading whitespace), mount /boot, then continue from the kernel-copy step of the runbook in INSTALL.md (kernels, initramfs, GRUB)'
rmdir /efi 2>/dev/null || warn 'could not remove the now-empty /efi directory — remove it manually'
mount /boot
[[ $(findmnt -no FSTYPE /boot) == vfat ]] || err '/boot did not mount as vfat — check the fstab line'

log '4/8 copy kernels + microcode onto the ESP (never the old initramfs: it embeds the keyfile)'
cp -a /boot.old/vmlinuz-* /boot/
for f in /boot.old/*-ucode.img; do
  if [[ -f $f ]]; then cp -a "$f" /boot/; fi
done

log '5/8 drop the cryptodisk switch and rebuild the initramfs (keyfile-free, onto the ESP)'
sed -i '/^GRUB_ENABLE_CRYPTODISK=/d' "$GRUB_DEFAULT"
mkinitcpio -P
esp_free_kb=$(df --output=avail /boot | awk 'NR == 2 { print $1 }')
(( esp_free_kb > 51200 )) \
  || warn "only $((esp_free_kb / 1024))MiB free on the ESP — future kernel updates will be tight"

log '6/8 reinstall GRUB (UEFI)'
# Unconditional, matching install.sh: --removable targets the fallback loader
# path on the ESP and does not touch NVRAM, so it needs no EFI runtime vars
# and refreshes the UEFI boot path even when this session booted legacy BIOS.
grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB --recheck --removable

log '7/8 reinstall GRUB (legacy BIOS)'
grub-install --target=i386-pc --recheck "$DISK"

log '8/8 regenerate grub.cfg'
grub-mkconfig -o /boot/grub/grub.cfg

log 'Migration done. Next:'
echo '  1. reboot: the GRUB menu is still unthemed and the passphrase prompt is'
echo '     on the console (the plymouth hook is not in place yet)'
echo '  2. set grub_theme and grub_kernel_parameters in group_vars/all/local.yml'
echo '     (Boot section of the machine templates), then run make configure —'
echo '     the grub role converges plymouth, the theme, and quiet splash'
echo '  3. only after that reboot succeeds, reclaim space with: rm -rf /boot.old'
echo '  recovery, if the reboot fails: installer ISO, unlock, chroot (INSTALL.md)'
