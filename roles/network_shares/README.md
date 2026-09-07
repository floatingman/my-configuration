# network_shares

Automounts NFS (and CIFS) network shares on laptops while a trusted
NetworkManager connection — e.g. the home WiFi — is active, and cleanly
unmounts them when the machine leaves that network. Shares are systemd
`.mount`/`.automount` pairs armed by a NetworkManager dispatcher script;
they are never enabled at boot, so an off-home boot never touches the NFS
servers.

## How it works

1. Each `shares` entry renders a systemd-escaped `<path>.mount` +
   `<path>.automount` unit pair named from the mount path (e.g.
   `/mnt/media` → `mnt-media.mount`; `/srv/media` → `srv-media.mount`),
   mount-on-first-access, idle unmount after `network_shares_idle_timeout`.
2. `/etc/NetworkManager/dispatcher.d/90-network-shares` runs on every NM
   event. While any trusted connection (wifi or wired) is active it starts
   the `.automount` units; otherwise it stops them and force-unmounts the
   `.mount` units so no stale NFS handles survive a network change.
3. Any legacy `/etc/fstab` entry for a managed path is removed — the role
   owns those mount points.

Requires NetworkManager (`nmcli`). NFS needs `nfs-utils`/`nfs-common`,
CIFS needs `cifs-utils` — all installed by the role.

## Variables

| Variable                                     | Default | Purpose                                                     |
| -------------------------------------------- | ------- | ----------------------------------------------------------- |
| `network_shares_config.trusted_connections`  | `[]`    | NM connection names that count as home (`nmcli -g NAME con show --active`) |
| `network_shares_config.shares`               | `[]`    | Shares: `name`, `src`, `path`, `fstype` (nfs/cifs), `options` |
| `network_shares_idle_timeout`                | `600`   | Seconds idle before an automounted share unmounts           |

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
