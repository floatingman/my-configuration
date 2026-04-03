#!/usr/bin/env python3
"""
Profile Dispatcher - Core Resolver and CLI

Pure function for resolving Ansible profile configuration into boolean flags.
Supports both profile mode (profile name) and manual mode (explicit variables).

This is a standalone Python module with no Ansible dependency,
making the dispatch logic unit-testable.

CLI subcommands:
  resolve       Resolve a profile to JSON (for Ansible script module)
  validate      Validate all profiles in a directory (for CI)
  list-profiles List available profile names or a human-readable table
  make-args     Output -e flag string for Makefile consumption
"""

import argparse
import json
import sys
import yaml
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# Default profiles directory relative to this script's location
_DEFAULT_PROFILES_DIR = str(Path(__file__).parent.parent / "profiles")

# Allowed values for profile fields
ALLOWED_DISPLAY_MANAGERS = {"", "lightdm", "gdm", "sddm"}
ALLOWED_DESKTOP_ENVIRONMENTS = {"", "i3", "hyprland", "gnome", "awesomewm", "kde"}


@dataclass(frozen=True)
class ResolvedProfile:
    """
    Immutable result of profile resolution.

    Attributes:
        profile: The profile name that was resolved (or 'manual' for manual mode)
        display_manager: The display manager to use ('gdm', 'lightdm', or None)
        has_display: Whether this machine has any display/GUI
        desktop_environment: The desktop environment name (or None for headless/dual-desktop)
        is_i3: Whether to install i3 window manager
        is_hyprland: Whether to install Hyprland compositor
        is_gnome: Whether to install GNOME desktop
        is_awesomewm: Whether to install AwesomeWM window manager
        is_kde: Whether to install KDE Plasma desktop
    """
    profile: str
    display_manager: Optional[str]
    has_display: bool
    desktop_environment: Optional[str]
    is_i3: bool
    is_hyprland: bool
    is_gnome: bool
    is_awesomewm: bool
    is_kde: bool


@dataclass(frozen=True)
class RoleCondition:
    """
    A single role entry with its computed Jinja2 condition.

    Attributes:
        role: Role name
        tags: Tuple of tags associated with this role
        condition: Jinja2 when: expression (or empty string for no condition)
        source: Name of the source (profile or overlay) that provided this role
    """
    role: str
    tags: Tuple[str, ...]
    condition: str
    source: str


@dataclass(frozen=True)
class ResolvedManifest:
    """
    Complete role manifest with computed conditions.

    Combines profile roles and overlay roles into a deduplicated list
    with Jinja2 when: conditions pre-computed from annotations.

    Attributes:
        profile: The profile name that was resolved
        display_manager: The display manager to use
        has_display: Whether this machine has any display/GUI
        profile_flags: Dict of profile boolean flags (_is_arch, _is_i3, etc.)
        overlay_flags: Dict of overlay boolean flags (_overlay_laptop, _overlay_bluetooth, etc.)
        roles: List of RoleCondition entries (deduplicated by role name)
    """
    profile: str
    display_manager: Optional[str]
    has_display: bool
    profile_flags: Dict[str, bool]
    overlay_flags: Dict[str, bool]
    roles: Tuple[RoleCondition, ...]


def load_profile(profiles_dir: str, name: str) -> dict:
    """
    Load a profile by name, merging its extends chain.

    Child values override parent values for scalar fields.
    Role lists are concatenated (parent roles first, child roles appended).

    Args:
        profiles_dir: Directory containing profile YAML files
        name: Profile name with or without .yml extension (e.g. 'i3' or 'i3.yml')

    Returns:
        Merged profile data as a dict

    Raises:
        ValueError: If the profile file does not exist, a cycle is detected,
                    or the name contains path separators
    """
    return _load_profile_inner(profiles_dir, name, visited=frozenset())


def _load_profile_inner(profiles_dir: str, name: str, visited: frozenset) -> dict:
    """Internal recursive loader that tracks the visited chain to detect cycles."""
    name = name.removesuffix(".yml")

    # Guard against path traversal: reject names with separators or parent references
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(
            f"Profile name '{name}' contains invalid path characters. "
            "Profile names must not include path separators or '..'."
        )

    if name in visited:
        cycle_path = " -> ".join([*sorted(visited), name])
        raise ValueError(f"Circular extends detected: {cycle_path}")

    profiles_root = Path(profiles_dir).resolve()
    profile_path = profiles_root / f"{name}.yml"

    # Enforce the path stays inside profiles_dir even after resolution
    try:
        profile_path.resolve().relative_to(profiles_root)
    except ValueError:
        raise ValueError(
            f"Profile '{name}' resolves outside the profiles directory."
        )

    if not profile_path.exists():
        raise ValueError(f"Profile '{name}' not found at {profile_path}")

    with open(profile_path) as f:
        data = yaml.safe_load(f) or {}

    extends = data.get("extends")
    if not extends:
        return data

    parent_name = str(extends).removesuffix(".yml")
    parent_data = _load_profile_inner(profiles_dir, parent_name, visited | {name})
    return _merge_profile_data(parent_data, data)


def _merge_profile_data(parent: dict, child: dict) -> dict:
    """Merge two profile dicts. Child scalars override parent; role lists are concatenated."""
    result = dict(parent)
    for key, value in child.items():
        if key == "extends":
            continue
        if key == "roles" and isinstance(result.get("roles"), list) and isinstance(value, list):
            result["roles"] = result["roles"] + value
        else:
            result[key] = value
    return result


def discover_overlays(profiles_dir: str) -> List[str]:
    """
    Discover all available overlay names in profiles/overlays/.

    Scans for *.yml files in profiles/overlays/, returning sorted names.
    Excludes files starting with '_'.

    Args:
        profiles_dir: Directory containing profile YAML files

    Returns:
        Sorted list of overlay names (without .yml extension)
    """
    overlays_root = Path(profiles_dir) / "overlays"
    if not overlays_root.exists():
        return []

    overlays = [
        p.stem
        for p in overlays_root.glob("*.yml")
        if not p.stem.startswith("_")
    ]
    return sorted(overlays)


def load_overlay(profiles_dir: str, name: str) -> dict:
    """
    Load an overlay by name from profiles/overlays/.

    Args:
        profiles_dir: Directory containing profile YAML files
        name: Overlay name with or without .yml extension

    Returns:
        Overlay data as a dict

    Raises:
        ValueError: If the overlay file does not exist
    """
    name = name.removesuffix(".yml")
    overlays_root = Path(profiles_dir).resolve() / "overlays"
    overlay_path = overlays_root / f"{name}.yml"

    # Enforce the path stays inside overlays_dir
    try:
        overlay_path.resolve().relative_to(overlays_root.resolve())
    except ValueError:
        raise ValueError(
            f"Overlay '{name}' resolves outside the overlays directory."
        )

    if not overlay_path.exists():
        raise ValueError(f"Overlay '{name}' not found at {overlay_path}")

    with open(overlay_path) as f:
        return yaml.safe_load(f) or {}


def translate_condition(
    role_entry: dict,
    host_vars: dict,
    os_family: str,
    evaluator: Any = None
) -> str:
    """
    Translate role annotations into a Jinja2 when: condition string.

    Maps role annotations (os, requires_display, requires_config, config_check)
    into Jinja2 expressions using facts like _is_arch, _has_display, _dm, etc.

    Args:
        role_entry: Role dict with annotations (role, tags, os, requires_display, etc.)
        host_vars: Host variables dict for config_check evaluation
        os_family: OS family ('Archlinux' or 'Debian')
        evaluator: Optional evaluator protocol for config_check expressions

    Returns:
        Jinja2 condition string (empty string if no condition)
    """
    conditions: List[str] = []

    # Normalize role_entry: handle both string "role" and dict {"role": "..."}
    if isinstance(role_entry, str):
        role_name = role_entry
        role_dict = {}
    else:
        role_name = role_entry.get("role", "")
        role_dict = role_entry

    # OS condition: os: archlinux → _is_arch, os: debian → not _is_arch
    os_spec = role_dict.get("os")
    if os_spec:
        if os_spec == "archlinux":
            conditions.append("_is_arch")
        elif os_spec == "debian":
            conditions.append("not _is_arch")

    # Display condition: requires_display: true → _has_display
    if role_dict.get("requires_display"):
        conditions.append("_has_display")

    # Config condition: requires_config: {display_manager: lightdm} → _dm == 'lightdm'
    requires_config = role_dict.get("requires_config")
    if requires_config and isinstance(requires_config, dict):
        if "display_manager" in requires_config:
            dm_value = requires_config["display_manager"]
            conditions.append(f"_dm == '{dm_value}'")

    # config_check: evaluate the expression and return boolean result
    config_check = role_dict.get("config_check")
    if config_check:
        if evaluator:
            # Evaluate config_check against host_vars using the evaluator
            try:
                result = evaluator.evaluate(config_check, host_vars)
                # config_check becomes a boolean in the condition
                conditions.append("true" if result else "false")
            except Exception:
                # If evaluation fails, use false to be safe
                conditions.append("false")
        else:
            # No evaluator provided - fall back to string evaluation
            # This is a simplified path for basic cases
            try:
                # Handle simple "dotfiles is defined" style checks
                if " is defined" in config_check:
                    var_name = config_check.split()[0]
                    is_defined = var_name in host_vars and host_vars[var_name] is not None
                    conditions.append("true" if is_defined else "false")
                elif " is defined" not in config_check and " or " not in config_check and " and " not in config_check:
                    # Simple boolean check
                    var_path = config_check.split(".")
                    value = host_vars
                    exists = True
                    for key in var_path:
                        if isinstance(value, dict) and key in value:
                            value = value[key]
                        else:
                            exists = False
                            break
                    # For enabled flags like cursor_theme.enabled
                    if isinstance(value, bool):
                        conditions.append("true" if value else "false")
                    elif isinstance(value, dict) and "enabled" in value:
                        conditions.append("true" if value["enabled"] else "false")
                    else:
                        conditions.append("true" if exists and value else "false")
                else:
                    # Complex expression - keep as-is for Jinja2 to evaluate
                    conditions.append(config_check)
            except Exception:
                # On any error, be conservative and include the role
                conditions.append("true")

    # Join all conditions with AND (implicit in Jinja2 when: list)
    if conditions:
        return " and ".join(conditions)

    return ""


def resolve_manifest(
    profile: Optional[str] = None,
    display_manager: Optional[str] = None,
    desktop_environment: Optional[str] = None,
    disable_i3: bool = False,
    disable_hyprland: bool = False,
    disable_gnome: bool = False,
    disable_awesomewm: bool = False,
    disable_kde: bool = False,
    host_vars: Optional[dict] = None,
    os_family: str = "Archlinux",
    profiles_dir: str = _DEFAULT_PROFILES_DIR,
    evaluator: Any = None,
) -> ResolvedManifest:
    """
    Resolve a complete role manifest from profile configuration.

    Combines profile roles and overlay roles into a deduplicated list
    with pre-computed Jinja2 when: conditions.

    Args:
        profile: Profile name or None for manual mode
        display_manager: Display manager for manual mode
        desktop_environment: Desktop environment for manual mode
        disable_i3: Suppress i3 in manual mode
        disable_hyprland: Suppress Hyprland in manual mode
        disable_gnome: Suppress GNOME in manual mode
        disable_awesomewm: Suppress AwesomeWM in manual mode
        disable_kde: Suppress KDE in manual mode
        host_vars: Host variables dict for config_check evaluation
        os_family: OS family ('Archlinux' or 'Debian')
        profiles_dir: Directory containing profile YAML files
        evaluator: Optional evaluator for config_check expressions

    Returns:
        ResolvedManifest with all roles and conditions
    """
    if host_vars is None:
        host_vars = {}

    # Resolve profile to get flags
    resolved = resolve(
        profile=profile,
        display_manager=display_manager,
        desktop_environment=desktop_environment,
        disable_i3=disable_i3,
        disable_hyprland=disable_hyprland,
        disable_gnome=disable_gnome,
        disable_awesomewm=disable_awesomewm,
        disable_kde=disable_kde,
        profiles_dir=profiles_dir,
    )

    # Build profile flags dict
    profile_flags = {
        "_is_arch": os_family == "Archlinux",
        "_is_i3": resolved.is_i3,
        "_is_hyprland": resolved.is_hyprland,
        "_is_gnome": resolved.is_gnome,
        "_is_awesomewm": resolved.is_awesomewm,
        "_is_kde": resolved.is_kde,
        "_has_display": resolved.has_display,
        "_dm": resolved.display_manager or "",
    }

    # Collect all roles from profile chain
    profile_roles: List[dict] = []
    if resolved.profile != "manual":
        profile_data = load_profile(profiles_dir, resolved.profile)
        profile_roles = profile_data.get("roles", [])

    # Discover and evaluate overlays
    overlay_flags: Dict[str, bool] = {}
    overlay_roles: List[dict] = []

    overlays = discover_overlays(profiles_dir)
    for overlay_name in overlays:
        try:
            overlay_data = load_overlay(profiles_dir, overlay_name)
            applies_when = overlay_data.get("applies_when")
            if not applies_when:
                continue

            # Evaluate applies_when expression (simplified)
            # laptop | default(false) → check if laptop is truthy in host_vars
            # bluetooth is defined and not (bluetooth.disable | default(false))
            #   → check if bluetooth exists and not disabled

            applies = False
            overlay_var = host_vars.get(overlay_name)

            if " is defined " in applies_when:
                # Handle "var is defined" pattern
                if overlay_var is not None:
                    # Check for "not (var.disable | default(false))" pattern
                    if "disable" in applies_when:
                        if isinstance(overlay_var, dict):
                            is_disabled = overlay_var.get("disable", False)
                            applies = not is_disabled
                        else:
                            applies = True
                    else:
                        applies = True
            elif " default(false)" in applies_when:
                # Handle "var | default(false)" pattern
                # An empty dict or False should not apply, but True or non-empty dict should
                if isinstance(overlay_var, dict):
                    # Empty dict doesn't apply, non-empty dict applies
                    applies = bool(overlay_var)
                elif overlay_var is True:
                    applies = True
                else:
                    applies = False
            else:
                # Fallback: check if overlay variable is truthy
                applies = bool(overlay_var)

            if applies:
                overlay_flags[f"_overlay_{overlay_name}"] = True
                overlay_roles.extend(overlay_data.get("roles", []))
        except (ValueError, yaml.YAMLError):
            # Skip invalid overlays
            continue

    # Combine roles from profile and overlays
    all_roles = profile_roles + overlay_roles

    # Build manifest: translate conditions and deduplicate by role name
    role_map: Dict[str, RoleCondition] = {}

    for role_entry in all_roles:
        # Get role name
        if isinstance(role_entry, str):
            role_name = role_entry
        else:
            role_name = role_entry.get("role", "")

        if not role_name:
            continue

        # Get tags
        if isinstance(role_entry, str):
            tags = ()
        else:
            tags_list = role_entry.get("tags", [])
            tags = tuple(tags_list) if isinstance(tags_list, list) else ()

        # Determine source
        source = resolved.profile  # Default to profile

        # Check if this role is from an overlay
        # (In a full implementation, we'd track source during collection)
        # For now, assume all roles are from profile
        # TODO: Track source during role collection

        # Translate condition
        condition = translate_condition(role_entry, host_vars, os_family, evaluator)

        # Deduplicate: OR conditions if role already exists
        if role_name in role_map:
            existing = role_map[role_name]
            # Combine conditions with OR
            if existing.condition and condition:
                # Both have conditions - OR them
                combined_condition = f"({existing.condition}) or ({condition})"
                role_map[role_name] = RoleCondition(
                    role=role_name,
                    tags=tags,
                    condition=combined_condition,
                    source=f"{existing.source}+overlay",
                )
            elif condition:
                # Use new condition (existing has no condition)
                role_map[role_name] = RoleCondition(
                    role_name=role_name,
                    tags=tags,
                    condition=condition,
                    source=source,
                )
            # Otherwise: existing has condition and new doesn't, or neither has condition
            # In both cases, keep the existing role_map entry unchanged
        else:
            # New role
            role_map[role_name] = RoleCondition(
                role=role_name,
                tags=tags,
                condition=condition,
                source=source,
            )

    # Convert to sorted tuple
    roles_tuple = tuple(role_map.values())

    return ResolvedManifest(
        profile=resolved.profile,
        display_manager=resolved.display_manager,
        has_display=resolved.has_display,
        profile_flags=profile_flags,
        overlay_flags=overlay_flags,
        roles=roles_tuple,
    )


def validate_profile(profiles_dir: str, name: str) -> list:
    """
    Validate a profile, returning a list of error strings.

    Checks: required fields present, extends chain resolvable,
    display_manager_default in allowed set, desktop_environment in known set.

    Args:
        profiles_dir: Directory containing profile YAML files
        name: Profile name (with or without .yml extension)

    Returns:
        List of error strings. Empty list means the profile is valid.
    """
    try:
        profile = load_profile(profiles_dir, name)
    except (ValueError, yaml.YAMLError, RecursionError) as exc:
        return [f"Failed to load profile '{name}': {exc}"]

    errors = []

    for field in ("display_manager_default", "desktop_environment"):
        if field not in profile:
            errors.append(f"Missing required field: {field}")

    if "display_manager_default" in profile:
        dm = profile["display_manager_default"]
        if not isinstance(dm, str):
            errors.append(
                f"Field 'display_manager_default' must be a string, got {type(dm).__name__}"
            )
        elif dm not in ALLOWED_DISPLAY_MANAGERS:
            errors.append(
                f"display_manager_default '{dm}' not in allowed set: "
                f"{sorted(ALLOWED_DISPLAY_MANAGERS)}"
            )

    if "desktop_environment" in profile:
        de = profile["desktop_environment"]
        if not isinstance(de, str):
            errors.append(
                f"Field 'desktop_environment' must be a string, got {type(de).__name__}"
            )
        elif de not in ALLOWED_DESKTOP_ENVIRONMENTS:
            errors.append(
                f"desktop_environment '{de}' not in known set: "
                f"{sorted(ALLOWED_DESKTOP_ENVIRONMENTS)}"
            )

    return errors


def list_profiles(profiles_dir: str) -> list:
    """
    Discover all valid profile names in profiles_dir, excluding _base.

    Scans for *.yml files directly in profiles_dir (not subdirectories),
    excludes files starting with '_', and filters to only profiles that
    pass validation (parseable, required fields present, allowed values).

    Args:
        profiles_dir: Directory containing profile YAML files

    Returns:
        Sorted list of valid profile names (without .yml extension)
    """
    profiles_path = Path(profiles_dir)
    candidates = [
        p.stem
        for p in profiles_path.glob("*.yml")
        if not p.stem.startswith("_")
    ]
    valid = [
        name for name in candidates
        if validate_profile(profiles_dir, name) == []
    ]
    return sorted(valid)


def resolve(
    profile: Optional[str] = None,
    display_manager: Optional[str] = None,
    desktop_environment: Optional[str] = None,
    disable_i3: bool = False,
    disable_hyprland: bool = False,
    disable_gnome: bool = False,
    disable_awesomewm: bool = False,
    disable_kde: bool = False,
    profiles_dir: str = _DEFAULT_PROFILES_DIR,
) -> ResolvedProfile:
    """
    Resolve profile configuration into boolean flags.

    Args:
        profile: Profile name ('headless', 'i3', 'hyprland', 'gnome', 'awesomewm', 'kde')
                or None for manual mode
        display_manager: Display manager name ('gdm', 'lightdm', 'sddm') or None
        desktop_environment: Desktop environment name or None
        disable_i3: Suppress i3 in manual mode
        disable_hyprland: Suppress Hyprland in manual mode
        disable_gnome: Suppress GNOME in manual mode
        disable_awesomewm: Suppress AwesomeWM in manual mode
        disable_kde: Suppress KDE in manual mode
        profiles_dir: Directory containing profile YAML files

    Returns:
        ResolvedProfile with all flags computed

    Raises:
        ValueError: If profile name is unknown
    """
    # Normalize profile: strip whitespace, treat empty/whitespace/'manual' as manual mode
    normalized = profile.strip() if profile else ''
    if normalized == 'manual':
        normalized = ''
    effective_profile = normalized or 'manual'

    # Validate profile exists (only in profile mode)
    if normalized:
        profile_file = Path(profiles_dir) / f"{normalized}.yml"
        if not profile_file.exists():
            # File not found → unknown profile; list valid ones for a helpful message
            valid_profiles = list_profiles(profiles_dir)
            raise ValueError(
                f"Unknown profile '{normalized}'. "
                f"Available profiles: {', '.join(sorted(valid_profiles))}"
            )
        # File exists → proceed; _resolve_profile_mode will validate and surface errors

    # Profile mode: load settings from YAML
    if effective_profile != 'manual':
        return _resolve_profile_mode(effective_profile, profiles_dir)

    # Manual mode: derive from explicit variables
    return _resolve_manual_mode(
        display_manager=display_manager,
        desktop_environment=desktop_environment,
        disable_i3=disable_i3,
        disable_hyprland=disable_hyprland,
        disable_gnome=disable_gnome,
        disable_awesomewm=disable_awesomewm,
        disable_kde=disable_kde
    )


def _resolve_profile_mode(profile: str, profiles_dir: str) -> ResolvedProfile:
    """
    Resolve in profile mode - settings come from YAML profile file.
    """
    errors = validate_profile(profiles_dir, profile)
    if errors:
        raise ValueError(
            f"Profile '{profile}' is invalid:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    profile_data = load_profile(profiles_dir, profile)

    # Map display_manager_default → display_manager (empty string becomes None)
    dm_raw = profile_data["display_manager_default"]
    dm = dm_raw if dm_raw else None

    de_raw = profile_data["desktop_environment"]
    de = de_raw if de_raw else None

    has_display = dm is not None

    return ResolvedProfile(
        profile=profile,
        display_manager=dm,
        has_display=has_display,
        desktop_environment=de,
        is_i3=(de == "i3"),
        is_hyprland=(de == "hyprland"),
        is_gnome=(de == "gnome"),
        is_awesomewm=(de == "awesomewm"),
        is_kde=(de == "kde"),
    )


def _resolve_manual_mode(
    display_manager: Optional[str],
    desktop_environment: Optional[str],
    disable_i3: bool,
    disable_hyprland: bool,
    disable_gnome: bool,
    disable_awesomewm: bool,
    disable_kde: bool
) -> ResolvedProfile:
    """
    Resolve in manual mode - derive flags from explicit variables.

    This matches the Jinja2 ternary logic in play.yml:
    - has_display is true if display_manager is set
    - Desktop flags are derived from desktop_environment
    - i3/hyprland have special dual-desktop behavior
    - All DEs respect their disable_* flags
    """
    # Normalize empty string to None
    dm = display_manager if display_manager else None
    de = desktop_environment if desktop_environment else None

    # has_display: true if display manager is set
    has_display = dm is not None

    # Desktop environment flags
    # For i3 and hyprland: enabled unless explicitly disabled or DE set to something else
    # For gnome/awesomewm/kde: only enabled if DE matches
    is_i3 = (
        has_display and
        not disable_i3 and
        (de is None or de == 'i3')
    )
    is_hyprland = (
        has_display and
        not disable_hyprland and
        (de is None or de == 'hyprland')
    )
    is_gnome = (
        not disable_gnome and
        de == 'gnome'
    )
    is_awesomewm = (
        not disable_awesomewm and
        de == 'awesomewm'
    )
    is_kde = (
        not disable_kde and
        de == 'kde'
    )

    return ResolvedProfile(
        profile='manual',
        display_manager=dm,
        has_display=has_display,
        desktop_environment=de,
        is_i3=is_i3,
        is_hyprland=is_hyprland,
        is_gnome=is_gnome,
        is_awesomewm=is_awesomewm,
        is_kde=is_kde
    )


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------

def _cmd_resolve(args: argparse.Namespace) -> int:
    """Output ResolvedProfile as JSON to stdout; exit 1 on error."""
    try:
        result = resolve(
            profile=args.profile,
            display_manager=args.display_manager,
            desktop_environment=args.desktop_environment,
            disable_i3=args.disable_i3,
            disable_hyprland=args.disable_hyprland,
            disable_gnome=args.disable_gnome,
            disable_awesomewm=args.disable_awesomewm,
            disable_kde=args.disable_kde,
            profiles_dir=args.profiles_dir,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(asdict(result)))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate all profiles; write errors to stderr; exit 1 on any failure."""
    profiles_path = Path(args.profiles_dir)
    all_names = [
        p.stem
        for p in profiles_path.glob("*.yml")
        if not p.stem.startswith("_")
    ]

    any_invalid = False
    for name in sorted(all_names):
        errors = validate_profile(args.profiles_dir, name)
        if errors:
            any_invalid = True
            for error in errors:
                print(f"{name}: {error}", file=sys.stderr)

    return 1 if any_invalid else 0


def _cmd_list_profiles(args: argparse.Namespace) -> int:
    """List profiles as space-separated names or a human-readable table."""
    names = list_profiles(args.profiles_dir)

    if args.format == "names":
        print(" ".join(names))
        return 0

    # pretty format: table with name, description, display_manager, desktop_environment
    col_widths = {"name": 14, "description": 40, "display_manager": 16, "desktop_environment": 20}
    header = (
        f"{'NAME':<{col_widths['name']}}"
        f"{'DESCRIPTION':<{col_widths['description']}}"
        f"{'DISPLAY_MANAGER':<{col_widths['display_manager']}}"
        f"DESKTOP_ENVIRONMENT"
    )
    print(header)
    print("-" * len(header))

    for name in names:
        try:
            data = load_profile(args.profiles_dir, name)
        except (ValueError, yaml.YAMLError):
            continue
        description = str(data.get("description", "")).splitlines()[0] if data.get("description") else ""
        dm = str(data.get("display_manager_default", "") or "")
        de = str(data.get("desktop_environment", "") or "")
        print(
            f"{name:<{col_widths['name']}}"
            f"{description:<{col_widths['description']}}"
            f"{dm:<{col_widths['display_manager']}}"
            f"{de}"
        )

    return 0


def _cmd_make_args(args: argparse.Namespace) -> int:
    """Output an Ansible -e flag string suitable for Makefile consumption; exit 1 on error."""
    try:
        result = resolve(profile=args.profile, profiles_dir=args.profiles_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parts = [f"profile={result.profile}"]
    if result.desktop_environment:
        parts.append(f"desktop_environment={result.desktop_environment}")
    if result.display_manager:
        parts.append(f"display_manager={result.display_manager}")

    print(f'-e "{" ".join(parts)}"')
    return 0


def _cmd_resolve_manifest(args: argparse.Namespace) -> int:
    """Output ResolvedManifest as JSON to stdout; exit 1 on error."""
    try:
        # Parse host_vars JSON
        host_vars = {}
        if args.host_vars:
            try:
                host_vars = json.loads(args.host_vars)
            except json.JSONDecodeError as exc:
                print(f"Invalid JSON in --host-vars: {exc}", file=sys.stderr)
                return 1

        result = resolve_manifest(
            profile=args.profile,
            display_manager=args.display_manager,
            desktop_environment=args.desktop_environment,
            disable_i3=args.disable_i3,
            disable_hyprland=args.disable_hyprland,
            disable_gnome=args.disable_gnome,
            disable_awesomewm=args.disable_awesomewm,
            disable_kde=args.disable_kde,
            host_vars=host_vars,
            os_family=args.os_family,
            profiles_dir=args.profiles_dir,
            evaluator=None,  # No evaluator in CLI mode
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Convert to dict for JSON serialization
    output = {
        "profile": result.profile,
        "display_manager": result.display_manager,
        "has_display": result.has_display,
        "profile_flags": result.profile_flags,
        "overlay_flags": result.overlay_flags,
        "roles": [
            {
                "role": r.role,
                "tags": list(r.tags),
                "condition": r.condition,
                "source": r.source,
            }
            for r in result.roles
        ],
    }

    print(json.dumps(output, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile_dispatcher.py",
        description="Profile Dispatcher: resolve and inspect Ansible profiles.",
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # --- resolve ---
    p_resolve = subparsers.add_parser(
        "resolve",
        help="Resolve a profile to JSON (suitable for Ansible script module).",
    )
    p_resolve.add_argument("--profile", default=None, help="Profile name (e.g. i3, headless)")
    p_resolve.add_argument("--display-manager", dest="display_manager", default=None)
    p_resolve.add_argument("--desktop-environment", dest="desktop_environment", default=None)
    p_resolve.add_argument("--disable-i3", dest="disable_i3", action="store_true")
    p_resolve.add_argument("--disable-hyprland", dest="disable_hyprland", action="store_true")
    p_resolve.add_argument("--disable-gnome", dest="disable_gnome", action="store_true")
    p_resolve.add_argument("--disable-awesomewm", dest="disable_awesomewm", action="store_true")
    p_resolve.add_argument("--disable-kde", dest="disable_kde", action="store_true")
    p_resolve.add_argument(
        "--profiles-dir", dest="profiles_dir", default=_DEFAULT_PROFILES_DIR
    )

    # --- validate ---
    p_validate = subparsers.add_parser(
        "validate",
        help="Validate all profiles; exit 1 if any are invalid.",
    )
    p_validate.add_argument(
        "--profiles-dir", dest="profiles_dir", default=_DEFAULT_PROFILES_DIR
    )

    # --- list-profiles ---
    p_list = subparsers.add_parser(
        "list-profiles",
        help="List available profile names.",
    )
    p_list.add_argument(
        "--format",
        choices=["names", "pretty"],
        default="names",
        help="Output format: 'names' (space-separated) or 'pretty' (table).",
    )
    p_list.add_argument(
        "--profiles-dir", dest="profiles_dir", default=_DEFAULT_PROFILES_DIR
    )

    # --- make-args ---
    p_make_args = subparsers.add_parser(
        "make-args",
        help='Output -e "profile=X ..." string for Makefile consumption.',
    )
    p_make_args.add_argument("--profile", required=True, help="Profile name")
    p_make_args.add_argument(
        "--profiles-dir", dest="profiles_dir", default=_DEFAULT_PROFILES_DIR
    )

    # --- resolve-manifest ---
    p_manifest = subparsers.add_parser(
        "resolve-manifest",
        help="Resolve a complete role manifest with computed conditions.",
    )
    p_manifest.add_argument("--profile", default=None, help="Profile name (e.g. i3, headless)")
    p_manifest.add_argument("--display-manager", dest="display_manager", default=None)
    p_manifest.add_argument("--desktop-environment", dest="desktop_environment", default=None)
    p_manifest.add_argument("--disable-i3", dest="disable_i3", action="store_true")
    p_manifest.add_argument("--disable-hyprland", dest="disable_hyprland", action="store_true")
    p_manifest.add_argument("--disable-gnome", dest="disable_gnome", action="store_true")
    p_manifest.add_argument("--disable-awesomewm", dest="disable_awesomewm", action="store_true")
    p_manifest.add_argument("--disable-kde", dest="disable_kde", action="store_true")
    p_manifest.add_argument(
        "--host-vars",
        dest="host_vars",
        default=None,
        help="Host variables as JSON string for config_check evaluation",
    )
    p_manifest.add_argument(
        "--os-family",
        dest="os_family",
        default="Archlinux",
        choices=["Archlinux", "Debian"],
        help="OS family for condition translation",
    )
    p_manifest.add_argument(
        "--profiles-dir", dest="profiles_dir", default=_DEFAULT_PROFILES_DIR
    )

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse calls sys.exit(0) for --help and sys.exit(2) for parse errors.
        # Re-raise for --help (exit code 0); convert parse errors to return 1.
        if exc.code == 0:
            return 0
        parser.print_usage(sys.stderr)
        return 1

    if args.subcommand is None:
        parser.print_usage(sys.stderr)
        return 1

    dispatch = {
        "resolve": _cmd_resolve,
        "validate": _cmd_validate,
        "list-profiles": _cmd_list_profiles,
        "make-args": _cmd_make_args,
        "resolve-manifest": _cmd_resolve_manifest,
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
