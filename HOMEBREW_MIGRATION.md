# Package Migration: Binaries to Homebrew

This document explains the changes made to migrate from binary downloads to Homebrew package management.

## Overview

Previously, the configuration used the `ansible-role-binaries` role to download and install many development tools and CLI utilities by fetching binaries directly from GitHub releases or other sources. This approach, while functional, had several drawbacks:

- Version management was manual (hardcoded version variables)
- Different installation methods for different tools
- No easy update mechanism
- Potential compatibility issues across distributions

With this update, we now use **Homebrew** (Linuxbrew on Linux) as the primary package manager for most development tools, providing:

- Unified package management across Arch and Debian systems
- Easy updates with `brew upgrade`
- Automatic dependency resolution
- Access to the vast Homebrew ecosystem

## Packages Migrated to Homebrew

The following packages are now installed via Homebrew (56 packages total):

### Container & Kubernetes Tools
- argocd
- dive
- docker-compose
- helm
- k6
- k9s
- kind
- kops
- kube-linter
- kubectl
- kubectx (includes kubens)
- kubeseal
- kubeval
- kustomize
- nova
- polaris (fairwindsops/tap/polaris)
- popeye (derailed/popeye/popeye)
- stern

### Version Control & Development
- gh (GitHub CLI)
- glab (GitLab CLI)
- gitui
- git-delta

### System Utilities
- bat
- bottom (btm)
- broot
- direnv
- doctl
- dog
- dua-cli
- duf
- dust
- dyff
- eza (replaces deprecated exa)
- fd
- jq
- lazygit
- lf
- logcli
- mdbook
- nnn
- pet
- ripgrep
- scc
- sd
- tectonic
- texlab
- tflint
- tokei
- viddy
- xsv
- yazi
- yq

## Packages Remaining in Binary Installation

These packages are still installed via direct binary download because they're not available in Homebrew or are better obtained from their official sources:

- **hey** - Load testing tool (not in Homebrew)
- **awless** - AWS CLI (archived project, not in Homebrew)
- **aws-iam-authenticator** - AWS authentication (better from AWS directly)
- **bit** - Git helper (not widely available in Homebrew)
- **gh-md-toc** - GitHub markdown TOC generator (shell script)
- **git-quick-stats** - Git statistics (shell script)
- **highlight-pointer** - Screen pointer highlighter (not in Homebrew)
- **mgitstatus** - Multi-git status (shell script)
- **prettyping** - Enhanced ping (shell script)
- **rke** - Rancher Kubernetes Engine (not in Homebrew)
- **slack-term** - Slack terminal client (not in Homebrew)
- **tfswitch** - Terraform version switcher (not in Homebrew)

## Configuration Changes

### Template Files Updated

Both `group_vars/all.yml.desktop.template` and `group_vars/all.yml.server.template` now include:

```yaml
# Homebrew packages - applications installed via Homebrew
homebrew_packages:
  - argocd
  - bat
  - bottom
  # ... (full list)

# Binaries to install via direct download (not available in Homebrew)
binaries:
  - name: hey
    url: "..."
  # ... (reduced list)
```

### Playbook Changes

The `play.yml` now includes the homebrew role:

```yaml
- {
    role: homebrew,
    tags: ["homebrew"],
    when: ansible_os_family == "Archlinux" or ansible_os_family == "Debian",
  }
```

This role runs before the `ansible-role-binaries` role, ensuring Homebrew packages are installed first.

## Benefits

1. **Consistency**: Same packages and versions across Arch and Debian systems
2. **Easier Updates**: `brew upgrade` updates all Homebrew packages
3. **Better Dependency Management**: Homebrew handles dependencies automatically
4. **Reduced Configuration**: No need to track version numbers for each package
5. **Broader Ecosystem**: Access to thousands of Homebrew formulas
6. **Cleaner Binaries List**: Only truly custom/special packages remain

## Migration Path

When updating from the old configuration:

1. Run the playbook with the `homebrew` tag to install Homebrew and packages
2. The binaries role will still run but will only install the reduced set of packages
3. Old binaries installed by the previous system won't be removed automatically
4. You can manually clean up old binaries from `~/.local/bin` if desired

## Future Considerations

- Consider migrating more packages to Homebrew as they become available
- Regularly review the binaries list for packages that might now be in Homebrew
- Consider using Homebrew taps for specialized packages
