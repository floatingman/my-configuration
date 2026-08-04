#!/usr/bin/env bash
#
# bootstrap-pipx.sh — install pipx and put its app dir (~/.local/bin) on PATH.
#
# On a fresh headless Ubuntu/WSL server, `make bootstrap` cannot run because it
# requires pipx to already exist. This script removes that chicken-and-egg step:
#
#   bash scripts/bootstrap-pipx.sh
#
# It installs pipx via the system package manager (apt on Debian/Ubuntu,
# pacman on Arch), runs `pipx ensurepath` so future shells pick up
# ~/.local/bin, and exports that dir for the current process so `pipx install`
# works immediately afterwards.
#
# After running this, open a new login shell (or `exec $SHELL -l`) and run:
#   make bootstrap        # installs ansible via pipx
#   make install          # installs ansible roles/collections
#   make configure        # runs the playbook
set -euo pipefail

have() { command -v "$1" >/dev/null 2>&1; }

echo ">> Checking for pipx..."
if ! have pipx; then
  echo ">> pipx not found; installing via system package manager..."
  if have apt-get; then
    sudo apt-get update -y
    # python3-pip is required because some Ubuntu pipx packages defer bootstrap
    # to pip; pipx itself ships in the archive on Ubuntu 22.04+.
    sudo apt-get install -y python3-pip pipx
  elif have pacman; then
    sudo pacman -S --noconfirm python-pipx
  else
    echo "ERROR: unsupported distribution — cannot find apt-get or pacman." >&2
    echo "       Please install pipx manually, then run 'make bootstrap'." >&2
    exit 1
  fi
else
  echo ">> pipx already installed."
fi

# Make ~/.local/bin available to future login/interactive shells.
echo ">> Ensuring ~/.local/bin is on PATH for future shells..."
pipx ensurepath >/dev/null 2>&1 || true

# Make ~/.local/bin usable in THIS process so a chained `pipx install ansible`
# (e.g. via `make setup`) finds the installed binaries right away.
export PATH="$HOME/.local/bin:$PATH"

echo ""
echo ">> pipx is ready."
echo ">> If ansible is not installed yet, run:  make bootstrap"
echo ">> NOTE: open a new shell or run 'exec \$SHELL -l' so the new PATH takes effect."
