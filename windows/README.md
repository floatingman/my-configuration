# Windows configuration

Windows machines are configured from this subtree with **WinGet
Configuration** (`winget configure`), not Ansible. Desired state is
declarative and idempotent: applying twice changes nothing the second time.
The manifest targets the documented stable schema (`configuration-dsc-schema/0.2`).

| File               | Purpose                                                |
| ------------------ | ------------------------------------------------------ |
| `config.dsc.yaml`  | Desired state: packages (winget + msstore sources)     |
| `bootstrap.ps1`    | Entrypoint: apply (`-Test` = drift check, no changes)  |
| `from-export.ps1`  | Converts `winget export` JSON to manifest blocks; `-Diff` report |

The Ansible/profile machinery in the repo root does not touch this subtree:
no `play.yml`, no `make` targets, not covered by `make check-sync` or
`generate-playbook`. CI (`windows-validate` job) only schema-validates
`config.dsc.yaml` on a windows runner; nothing is applied in CI.

## One-time prerequisites

1. `winget` present (ships as **App Installer**; on a fresh box open
   `ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1`, install, reopen the
   terminal).
2. Clone this repo, then from the repo root:

```powershell
.\windows\bootstrap.ps1            # apply desired state
.\windows\bootstrap.ps1 -Test      # drift check only
```

## Adding a package

Find the exact ID, then append a resource block to `config.dsc.yaml`:

```powershell
winget search <name>                        # winget source: use the Id column
winget search --source msstore --name <app> # store apps: use the 9... ID
```

```yaml
- resource: Microsoft.WinGet.DSC/WinGetPackage
  id: my-app                     # short unique name for the resource
  directives:
    description: Install My App
  settings:
    id: <winget-or-msstore-id>
    source: winget               # or: msstore
```

## Syncing with what is actually installed

Dump the machine, then let the converter do the YAML:

```powershell
winget export -o "$env:TEMP\apps.json" --accept-source-agreements
.\windows\from-export.ps1 "$env:TEMP\apps.json" -Diff      # three-group report
.\windows\from-export.ps1 "$env:TEMP\apps.json"            # blocks for installed-but-undeclared apps
```

`-Diff` prints declared+installed, declared-but-missing, and
installed-but-undeclared. The block output only covers the undeclared set;
the export is full of noise (frameworks, runtimes, OEM packages), so review
before pasting blocks into `config.dsc.yaml`. Do not commit the raw export.

## UniGet policy

UniGet (and the Store app) stay the **ad-hoc lane**: fine for trying things
out. Anything you want reproducible must land in `config.dsc.yaml`.
`bootstrap.ps1 -Test` checks the declared resources; `from-export.ps1
<export.json> -Diff` additionally reveals packages installed outside the
manifest.

Account-bound or paid Store apps cannot install headless via winget:
install those once manually (Store/UniGet) and record them in the list
below instead of the manifest.

### Deliberately NOT in the manifest (from the blurr export, 2026-11-13)

- **Runtimes and system components** (installed as dependencies; leave to winget/Windows):
  VCRedist family, .NET runtimes and SDKs, Microsoft.UI.Xaml, VCLibs, WindowsAppRuntime,
  DirectX, GameInput, XNA Redist, App Installer, Edge, OneDrive, 365 Copilot, Outlook,
  Office 2010 Filter Packs, Intelligent Terminal, Epic Online Services, VS Build Tools,
  Windows SDK, WinFsp, Dokan.
- **Hardware/driver-tied** (only meaningful on machines with that hardware):
  Logitech G HUB and Camera Settings, Kensington Works, Focusrite Control, NVIDIA CUDA,
  Nsight, PhysX and PhysX Legacy, Apple Application Support / Software Update / QuickTime,
  OpenAL, Oracle JRE.
- **Licensed / account-bound**: Synergy, TextExpander, Grammarly, IsoBuster,
  Guitar Pro 8, RescueTime, Kali Linux (WSL distro).
- **Ad-hoc utilities** (kept in the UniGet lane): CPU-Z, HWiNFO, DiskCheckup, KillDisk,
  AllDup, Folder Size, CompactGUI, Glary Utilities, SageThumbs, QuickPar, FotoSketcher,
  Screenbox, MediaMonkey 4, Python 3.11, .NET SDK 3.1, IG Client, DSH Desktop, RED beta,
  Unsloth (managed in a Python environment instead).

## Updating

`winget upgrade --all` moves versions out of band; the manifest pins
presence, not versions. Re-running `bootstrap.ps1` after OS reinstalls or
new machines is the reproducible path.
