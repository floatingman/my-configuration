# network_shares

Manages NFS (and CIFS) network shares as systemd mount units. Two modes:

- **`trusted-network`** (default, laptops): automount pairs armed by a
  NetworkManager dispatcher while a trusted connection — e.g. the home WiFi —
  is active, cleanly unmounted when the machine leaves that network. Never
  enabled at boot, so an off-home boot never touches the NFS servers.
- **`persistent`** (always-on servers): plain `.mount` units enabled at boot
  via `WantedBy=multi-user.target`, no NetworkManager requirement, no idle
  unmount. Shares are mounted as soon as the network target allows.

## How it works

1. Each `shares` entry renders a systemd-escaped `<path>.mount` named from
   the mount path (e.g. `/mnt/media` → `mnt-media.mount`;
   `/srv/media` → `srv-media.mount`). In `trusted-network` mode it is paired
   with a `<path>.automount` unit (mount-on-first-access, idle unmount after
   `network_shares_idle_timeout`); in `persistent` mode the `.mount` unit is
   enabled at boot instead.
2. Trusted-network mode installs
   `/etc/NetworkManager/dispatcher.d/90-network-shares`, which runs on every
   NM event: while any trusted connection (wifi or wired) is active it starts
   the `.automount` units; otherwise it stops them and force-unmounts the
   `.mount` units so no stale NFS handles survive a network change.
   Persistent mode installs no dispatcher and removes a leftover one.
3. Any legacy `/etc/fstab` entry for a managed path is removed — the role
   owns those mount points.

Trusted-network mode requires NetworkManager (`nmcli`). NFS needs
`nfs-utils`/`nfs-common`, CIFS needs `cifs-utils` — all installed by the role.


## Variables

| Variable                                     | Default            | Purpose                                                     |
| -------------------------------------------- | ------------------ | ----------------------------------------------------------- |
| `network_shares_mode`                        | `trusted-network`  | `trusted-network` (NM-gated automounts) or `persistent` (boot-enabled server mounts) |
| `network_shares_config.trusted_connections`  | `[]`               | NM connection names that count as home (`nmcli -g NAME con show --active`) — required in trusted-network mode |
| `network_shares_config.shares`               | `[]`               | Shares: `name`, `src`, `path`, `fstype` (nfs/cifs), `options` |
| `network_shares_idle_timeout`                | `600`              | Seconds idle before an automounted share unmounts (trusted-network mode) |

An empty `shares` list disables the role entirely.

## Example

```yaml
network_shares_config:
  trusted_connections: [abode]

  shares:
    - name: Media
      src: "192.168.0.6:/volume1/Media"
      path: /mnt/media
      fstype: nfs
      options: "vers=3,soft,timeo=100,noatime"
    - name: Downloads       # no NFS export on the NAS (yet) — stays CIFS
      src: "//192.168.0.6/Downloads"
      path: /mnt/downloads
      fstype: cifs
      options: "credentials=/etc/samba/credentials/perceptor,uid=1000,gid=1000,rw"
```

CIFS credentials files are secrets: create them out-of-band (`chmod 600`,
owned by root) and reference them from `options`. The role never writes
credentials.

## Switching a CIFS share to NFS

Add the NFS export on the server, then flip the share entry to
`fstype: nfs` and an NFS `src`/`options`. Note NFS has no per-connection
credential mapping: files appear owned by their server-side numeric UID,
so client write access depends on server-side export/ownership settings
(all_squash / anonuid on a Synology, `no_root_squash` + matching UIDs
elsewhere).

## Operations

```sh
journalctl -t network-shares            # dispatcher decisions
systemctl status mnt-media.automount    # current gate state
sudo /etc/NetworkManager/dispatcher.d/90-network-shares --apply   # re-evaluate now
```

Removing a share from `shares` stops managing its units but does not
delete them — remove stale `/etc/systemd/system/mnt-*.{mount,automount}`
files by hand, then `systemctl daemon-reload`.
