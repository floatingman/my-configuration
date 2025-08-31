# uv_python_packages

Install Python packages using the uv package manager with support for both isolated tools and shared virtual environments.

This role mimics the functionality of the `install-python-packages` from the end-4/dots-hyprland repository but uses the modern `uv` package manager instead of pip. It supports two modes:

1. **Tool mode**: Installs Python packages as isolated tools using `uv tool install`
2. **Pip mode**: Installs packages in a shared virtual environment using `uv pip install`

## Requirements

- `uv` package manager must be installed and available in the system PATH
- Python 3.8 or higher

## Role Variables

### Main Variables

- `uv_python_packages_mode`: Installation mode - "tool" or "pip" (default: `"tool"`)
- `uv_python_packages_list`: A list of Python packages to install (default: `[]`)
- `uv_python_packages_requirements_file`: Path or URL to requirements file (default: `""`)
- `uv_python_packages_venv_path`: Virtual environment path for pip mode (default: `"~/.local/share/uv-python-packages"`)
- `uv_python_packages_enabled`: Whether to enable the role (default: `true`)
- `uv_python_packages_update_shell`: Whether to update shell PATH after installation (default: `true`)

### uv Tool Options (for tool mode)

- `uv_python_packages_tool_options.force`: Force installation even if already installed (default: `false`)
- `uv_python_packages_tool_options.quiet`: Use quiet output (default: `false`)
- `uv_python_packages_tool_options.verbose`: Use verbose output (default: `false`)
- `uv_python_packages_tool_options.upgrade`: Upgrade packages if they already exist (default: `false`)
- `uv_python_packages_tool_options.python`: Python interpreter to use (default: `""`)
- `uv_python_packages_tool_options.with_requirements`: Additional requirements files (default: `[]`)
- `uv_python_packages_tool_options.constraints`: Constraints files to use (default: `[]`)
- `uv_python_packages_tool_options.overrides`: Override files to use (default: `[]`)

### uv Pip Options (for pip mode)

- `uv_python_packages_pip_options.quiet`: Use quiet output (default: `false`)
- `uv_python_packages_pip_options.verbose`: Use verbose output (default: `false`)
- `uv_python_packages_pip_options.upgrade`: Upgrade packages if they already exist (default: `false`)
- `uv_python_packages_pip_options.python`: Python interpreter to use (default: `""`)
- `uv_python_packages_pip_options.index_url`: Index URL to use (default: `""`)
- `uv_python_packages_pip_options.extra_index_url`: Extra index URLs (default: `[]`)

## Dependencies

None. However, the `uv` package manager must be installed on the target system.

## Example Playbook

### Tool Mode - Individual Tools (Default)

```yaml
---
- hosts: localhost
  vars:
    uv_python_packages_mode: "tool"
    uv_python_packages_list:
      - "black"
      - "flake8"
      - "pytest"
      - "jupyterlab"
      - "httpie"
      - "molecule[docker]"
  roles:
    - uv_python_packages
```

### Pip Mode - Requirements File (end-4/dots-hyprland)

```yaml
---
- hosts: localhost
  vars:
    uv_python_packages_mode: "pip"
    uv_python_packages_requirements_file: "https://github.com/end-4/dots-hyprland/raw/main/scriptdata/requirements.txt"
    uv_python_packages_venv_path: "~/.local/share/dots-hyprland-env"
  roles:
    - uv_python_packages
```

### Pip Mode - Individual Packages

```yaml
---
- hosts: localhost
  vars:
    uv_python_packages_mode: "pip"
    uv_python_packages_list:
      - "material-color-utilities==0.2.1"
      - "materialyoucolor==2.0.10"
      - "pillow==11.1.0"
      - "psutil==6.1.1"
    uv_python_packages_venv_path: "~/.local/share/my-python-env"
  roles:
    - uv_python_packages
```

### Advanced Tool Mode with Options

```yaml
---
- hosts: localhost
  vars:
    uv_python_packages_mode: "tool"
    uv_python_packages_list:
      - "black"
      - "ruff"
      - "pytest"
      - "jupyterlab"
    uv_python_packages_tool_options:
      force: true
      verbose: true
      upgrade: true
    uv_python_packages_update_shell: true
  roles:
    - uv_python_packages
```

### Conditional Installation

```yaml
---
- hosts: localhost
  vars:
    uv_python_packages_mode: "tool"
    uv_python_packages_list:
      - "black"
      - "pytest"
    uv_python_packages_enabled: "{{ ansible_os_family == 'Archlinux' }}"
  roles:
    - uv_python_packages
```

## Package Examples

Common packages that work well with uv tool install:

- **Code Formatters**: `black`, `ruff`, `isort`
- **Linters**: `flake8`, `pylint`, `mypy`
- **Testing**: `pytest`, `tox`, `coverage`
- **Development**: `jupyterlab`, `ipython`, `molecule[docker]`
- **CLI Tools**: `httpie`, `awscli`, `speedtest-cli`
- **System Tools**: `thefuck`, `gitlabber`, `s4cmd`

## Features

- **Fast Installation**: Uses uv's fast resolver and installer
- **Isolated Environments**: Each tool gets its own virtual environment
- **Automatic PATH Updates**: Tools are automatically added to PATH
- **Idempotent**: Won't reinstall packages that are already installed
- **Flexible Configuration**: Supports all major uv tool install options
- **Error Handling**: Graceful handling of installation failures
- **Informative Output**: Shows installation progress and results

## How it Works

1. Checks if uv is installed on the system
2. Iterates through the list of packages in `uv_python_packages`
3. Installs each package using `uv tool install` with specified options
4. Updates shell PATH to include uv tools directory
5. Provides feedback on installation status

## Comparison with pip

| Feature | uv tool install | pip install --user |
|---------|----------------|-------------------|
| Speed | Very Fast | Moderate |
| Isolation | Full isolation per tool | Shared user environment |
| Dependency conflicts | Avoided | Possible |
| PATH management | Automatic | Manual |
| Uninstallation | Clean removal | May leave dependencies |

## Troubleshooting

### uv not found
If you get an error that uv is not found, install it first:

```bash
# On Arch Linux
sudo pacman -S uv

# Using pip
pip install uv

# Using curl
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Permission Issues
This role runs without `become: true` by default, installing tools in the user's home directory. If you need system-wide installation, you may need to modify the role.

### Package Not Found
Some packages may not be available or may have different names. Check the package name on PyPI.

## License

MIT

## Author Information

Created for DevOps automation and infrastructure management, inspired by the end-4/dots-hyprland repository's install-python-packages functionality.
