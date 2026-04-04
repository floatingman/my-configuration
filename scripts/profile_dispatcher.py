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
  sync-playbook Compare profile-derived roles against play.yml roles section
"""

import argparse
import json
import sys
import yaml
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
class RoleEntry:
    """
    A role entry from a profile with its condition annotations.

    Attributes:
        role: Role name
        tags: List of tags
        when: Jinja2 condition string (may be empty for unconditional roles)
    """
    role: str
    tags: List[str]
    when: str


def translate_condition(role_annotation: Dict[str, Any]) -> str:
    """
    Translate profile role annotations to Jinja2 condition string.

    Handles:
    - os: archlinux → "_is_arch"
    - os: debian → "not _is_arch"
    - requires_display: true → "_has_display"
    - requires_config: {display_manager: lightdm} → "_dm == 'lightdm'"
    - config_check: "..." → use as-is (backward compatibility)

    Special handling for desktop environment roles:
    - gnome, i3, hyprland, awesomewm, kde use _is_* flags instead of _dm comparisons
    - DE flags already imply display, so _has_display is not added separately

    Args:
        role_annotation: A single role dict from a profile's roles list

    Returns:
        Jinja2 condition string suitable for play.yml when: clause.
        Returns empty string for unconditional roles.

    Examples:
        >>> translate_condition({"role": "base", "tags": ["base"], "os": "archlinux"})
        "_is_arch"
        >>> translate_condition({"role": "fonts", "tags": ["fonts"], "requires_display": true})
        "_has_display"
        >>> translate_condition({"role": "lightdm", "requires_config": {"display_manager": "lightdm"}})
        "_dm == 'lightdm'"
    """
    role_name = role_annotation.get("role", "")
    conditions: List[str] = []

    # Desktop environment roles: map to _is_* flags
    de_role_mapping = {
        "gnome": "_is_gnome",
        "i3": "_is_i3",
        "hyprland": "_is_hyprland",
        "awesomewm": "_is_awesomewm",
        "kde": "_is_kde",
    }

    # Check if this is a DE-specific role with requires_config for display_manager
    requires_config = role_annotation.get("requires_config")
    is_de_role = role_name in de_role_mapping

    if is_de_role and requires_config and isinstance(requires_config, dict):
        # For DE roles with display_manager config, use the _is_* flag
        # The _is_* flag already implies display, so skip _has_display
        dm_value = requires_config.get("display_manager")
        if dm_value:
            conditions.append(de_role_mapping[role_name])
            # Skip processing requires_display for DE roles (already implied)
            # Continue to process OS and config_check conditions
            role_annotation = dict(role_annotation)  # Make a copy to modify
            role_annotation.pop("requires_display", None)
    else:
        # Non-DE roles: process requires_config normally
        if requires_config and isinstance(requires_config, dict):
            for key, value in requires_config.items():
                if key == "display_manager":
                    conditions.append(f"_dm == '{value}'")

    # OS condition
    os_val = role_annotation.get("os")
    if os_val == "archlinux":
        conditions.append("_is_arch")
    elif os_val == "debian":
        conditions.append("not _is_arch")

    # Display condition (only if not already handled as DE role)
    if role_annotation.get("requires_display"):
        conditions.append("_has_display")

    # Legacy config_check: use as-is
    config_check = role_annotation.get("config_check")
    if config_check:
        conditions.append(config_check)

    # Join all conditions with " and "
    if conditions:
        return " and ".join(conditions)
    return ""


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


def _extract_roles_from_playbook(playbook_path: str) -> Dict[str, RoleEntry]:
    """
    Extract role entries from play.yml roles section.

    Args:
        playbook_path: Path to play.yml

    Returns:
        Dict mapping role name to RoleEntry

    Raises:
        ValueError: If playbook cannot be parsed or roles section is missing
    """
    playbook = Path(playbook_path)
    if not playbook.exists():
        raise ValueError(f"Playbook not found: {playbook_path}")

    with open(playbook) as f:
        data = yaml.safe_load(f)

    if not data or not isinstance(data, list):
        raise ValueError(f"Playbook must be a list, got {type(data)}")

    # Get first play (there's only one in our setup)
    play = data[0]
    roles_section = play.get("roles")
    if not roles_section:
        raise ValueError("Playbook missing 'roles' section")

    roles: Dict[str, RoleEntry] = {}
    for item in roles_section:
        # Handle both dict and string formats
        if isinstance(item, str):
            role_name = item
            tags = []
            when = ""
        elif isinstance(item, dict):
            role_name = item.get("role")
            if not role_name:
                continue
            tags_raw = item.get("tags", [])
            # Handle both "tags: [tag1, tag2]" and "tags: tag1" formats
            if isinstance(tags_raw, list):
                tags = tags_raw
            else:
                tags = [tags_raw] if tags_raw else []
            # Extract when condition, normalizing to string
            when = item.get("when", "")
            # Handle boolean when values
            if isinstance(when, bool):
                when = "true" if when else "false"
        else:
            continue

        roles[role_name] = RoleEntry(role=role_name, tags=tags, when=when)

    return roles


def _build_expected_roles(profiles_dir: str) -> Dict[str, RoleEntry]:
    """
    Build expected role entries from all profile YAML files.

    Loads all profiles, translates their role annotations to Jinja2 conditions,
    and deduplicates by role name (last profile wins).

    Args:
        profiles_dir: Directory containing profile YAML files

    Returns:
        Dict mapping role name to RoleEntry with translated conditions
    """
    profile_names = list_profiles(profiles_dir)
    expected_roles: Dict[str, RoleEntry] = {}

    # Desktop environment roles that should use the profile's DE flag
    de_roles = {
        "i3": "_is_i3",
        "hyprland": "_is_hyprland",
        "gnome": "_is_gnome",
        "awesomewm": "_is_awesomewm",
        "kde": "_is_kde",
    }

    # Profile-specific roles that should be gated by the profile's DE flag
    # These roles appear in a specific profile's YAML and should only run when that DE is active
    hyprland_specific_roles = {
        "wayland", "widgets", "qt_gtk_toolkit", "uv_python_packages",
        "oneui4_icons", "screencapture", "microtex",
    }
    i3_specific_roles = {"x"}

    for profile_name in profile_names:
        profile_data = load_profile(profiles_dir, profile_name)
        roles_list = profile_data.get("roles", [])
        profile_de = profile_data.get("desktop_environment", "")

        for role_item in roles_list:
            # Handle both dict and string formats
            if isinstance(role_item, str):
                role_name = role_item
                tags = []
                when = ""
            elif isinstance(role_item, dict):
                role_name = role_item.get("role")
                if not role_name:
                    continue
                tags_raw = role_item.get("tags", [])
                if isinstance(tags_raw, list):
                    tags = tags_raw
                else:
                    tags = [tags_raw] if tags_raw else []

                # Translate condition annotations to Jinja2
                when = translate_condition(role_item)

                # Special handling: DE-specific roles in their own profile
                # If the role has no explicit condition and matches the profile's DE,
                # add the appropriate _is_* flag
                if role_name in de_roles and not when:
                    when = de_roles[role_name]

            else:
                continue

            # Special handling: profile-specific roles
            # These roles should be gated by the profile's DE flag even if they have other conditions
            if profile_de == "hyprland" and role_name in hyprland_specific_roles:
                if when:
                    when = f"{when} and _is_hyprland"
                else:
                    when = "_is_hyprland"
            elif profile_de == "i3" and role_name in i3_specific_roles:
                if when:
                    when = f"{when} and _is_i3"
                else:
                    when = "_is_i3"

            # Store role entry (later profiles override earlier ones for same role)
            expected_roles[role_name] = RoleEntry(role=role_name, tags=tags, when=when)

    return expected_roles


def _normalize_condition(condition: str) -> str:
    """
    Normalize a Jinja2 condition string for comparison.

    Normalizations:
    1. Remove redundant | bool filters
    2. Remove redundant _has_display when _dm == 'xxx' is present (dm implies display)
    3. Normalize whitespace
    4. Sort condition parts (A and B -> B and A) for order-independent comparison

    Args:
        condition: Jinja2 condition string

    Returns:
        Normalized condition string
    """
    if not condition:
        return ""

    # Remove all | bool filters
    normalized = condition.replace("| bool", "")

    # Remove redundant _has_display when _dm == 'xxx' is present
    # The _dm variable being set already implies display
    if "_dm ==" in normalized and "_has_display" in normalized:
        parts = [p.strip() for p in normalized.split(" and ")]
        filtered = [p for p in parts if p != "_has_display"]
        normalized = " and ".join(filtered)

    # Normalize whitespace
    normalized = " ".join(normalized.split())

    return normalized.strip()


def _build_all_expected_roles(profiles_dir: str) -> Dict[str, set]:
    """
    Build ALL expected role entries from all profile YAML files.

    Unlike _build_expected_roles() which deduplicates (last wins),
    this returns ALL conditions for each role across all profiles.

    Args:
        profiles_dir: Directory containing profile YAML files

    Returns:
        Dict mapping role name to set of all possible conditions
    """
    profile_names = list_profiles(profiles_dir)
    all_roles: Dict[str, set] = {}

    # Desktop environment roles that should use the profile's DE flag
    de_roles = {
        "i3": "_is_i3",
        "hyprland": "_is_hyprland",
        "gnome": "_is_gnome",
        "awesomewm": "_is_awesomewm",
        "kde": "_is_kde",
    }

    # Profile-specific roles that should be gated by the profile's DE flag
    hyprland_specific_roles = {
        "wayland", "widgets", "qt_gtk_toolkit", "uv_python_packages",
        "oneui4_icons", "screencapture", "microtex",
    }
    i3_specific_roles = {"x"}

    for profile_name in profile_names:
        profile_data = load_profile(profiles_dir, profile_name)
        roles_list = profile_data.get("roles", [])
        profile_de = profile_data.get("desktop_environment", "")

        for role_item in roles_list:
            # Handle both dict and string formats
            if isinstance(role_item, str):
                role_name = role_item
                tags = []
                when = ""
            elif isinstance(role_item, dict):
                role_name = role_item.get("role")
                if not role_name:
                    continue
                tags_raw = role_item.get("tags", [])
                if isinstance(tags_raw, list):
                    tags = tags_raw
                else:
                    tags = [tags_raw] if tags_raw else []

                # Translate condition annotations to Jinja2
                when = translate_condition(role_item)

                # Special handling: DE-specific roles in their own profile
                # If the role has no explicit condition and matches the profile's DE,
                # add the appropriate _is_* flag
                if role_name in de_roles and not when:
                    when = de_roles[role_name]

            else:
                continue

            # Special handling: profile-specific roles
            # These roles should be gated by the profile's DE flag even if they have other conditions
            if profile_de == "hyprland" and role_name in hyprland_specific_roles:
                if when:
                    when = f"{when} and _is_hyprland"
                else:
                    when = "_is_hyprland"
            elif profile_de == "i3" and role_name in i3_specific_roles:
                if when:
                    when = f"{when} and _is_i3"
                else:
                    when = "_is_i3"

            # Add to the set of conditions for this role
            if role_name not in all_roles:
                all_roles[role_name] = set()
            all_roles[role_name].add(_normalize_condition(when))

    return all_roles


def _compare_roles(actual: Dict[str, RoleEntry], expected: Dict[str, RoleEntry]) -> Dict[str, Any]:
    """
    Compare actual vs expected role entries.

    A role matches if:
    1. It exists in both actual and expected
    2. The actual condition matches ANY of the expected conditions for that role
       (because a role may appear in multiple profiles with different conditions)

    Args:
        actual: Roles extracted from play.yml
        expected: Roles generated from profile annotations (unused, we rebuild from profiles)

    Returns:
        Dict with keys: "missing", "extra", "mismatches"
    """
    # Rebuild expected roles to get ALL possible conditions per role
    all_expected = _build_all_expected_roles(str(Path(__file__).parent.parent / "profiles"))

    actual_names = set(actual.keys())
    expected_names = set(all_expected.keys())

    missing = expected_names - actual_names
    extra = actual_names - expected_names

    # Check for condition mismatches
    mismatches: Dict[str, Dict[str, str]] = {}
    for role_name in actual_names & expected_names:
        actual_when = _normalize_condition(actual[role_name].when)
        expected_when_set = all_expected.get(role_name, set())

        # Special case: empty actual condition matches empty expected condition
        if not actual_when and "" in expected_when_set:
            continue

        # Check if actual condition matches any expected condition
        if actual_when not in expected_when_set:
            # Format the expected conditions for display
            expected_list = sorted([w for w in expected_when_set])
            if len(expected_list) == 1:
                expected_str = expected_list[0]
            else:
                expected_str = " or ".join(expected_list)
            mismatches[role_name] = {
                "expected": expected_str,
                "actual": actual_when,
            }

    return {
        "missing": sorted(missing),
        "extra": sorted(extra),
        "mismatches": mismatches,
    }


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


def _cmd_sync_playbook(args: argparse.Namespace) -> int:
    """
    Sync-check between profile YAMLs and play.yml.

    In normal mode: outputs diff for developer review.
    In --check mode: exits 1 on drift, exits 0 if in sync (CI gate).
    """
    try:
        actual_roles = _extract_roles_from_playbook(args.playbook)
        expected_roles = _build_expected_roles(args.profiles_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    comparison = _compare_roles(actual_roles, expected_roles)

    # Check if there are any differences
    has_drift = bool(
        comparison["missing"] or
        comparison["extra"] or
        comparison["mismatches"]
    )

    # Build output
    output_lines = []

    if comparison["missing"]:
        output_lines.append("Missing roles (in profiles but not in play.yml):")
        for role in comparison["missing"]:
            expected_entry = expected_roles[role]
            when_clause = f" when: {expected_entry.when}" if expected_entry.when else ""
            output_lines.append(f"  - {role}{when_clause}")
        output_lines.append("")

    if comparison["extra"]:
        output_lines.append("Extra roles (in play.yml but not in profiles):")
        for role in comparison["extra"]:
            actual_entry = actual_roles[role]
            when_clause = f" when: {actual_entry.when}" if actual_entry.when else ""
            output_lines.append(f"  - {role}{when_clause}")
        output_lines.append("")

    if comparison["mismatches"]:
        output_lines.append("Condition mismatches:")
        for role, diff in comparison["mismatches"].items():
            output_lines.append(f"  - {role}:")
            output_lines.append(f"      expected: {diff['expected']}")
            output_lines.append(f"      actual:   {diff['actual']}")
        output_lines.append("")

    # Print output
    if has_drift:
        print("\n".join(output_lines))
    elif not args.check:
        # Only print "in sync" message in non-check mode
        print("play.yml is in sync with profiles")

    # In check mode, exit 1 on drift
    if args.check and has_drift:
        return 1

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

    # --- sync-playbook ---
    p_sync = subparsers.add_parser(
        "sync-playbook",
        help="Compare profile-derived roles against play.yml roles section.",
    )
    p_sync.add_argument(
        "--profiles-dir", dest="profiles_dir", default=_DEFAULT_PROFILES_DIR
    )
    p_sync.add_argument(
        "--playbook",
        default=str(Path(__file__).parent.parent / "play.yml"),
        help="Path to play.yml (default: ../play.yml)",
    )
    p_sync.add_argument(
        "--check",
        action="store_true",
        help="CI mode: exit 1 on drift, no output changes",
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
        "sync-playbook": _cmd_sync_playbook,
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
