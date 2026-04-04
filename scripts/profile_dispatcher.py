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
  sync-playbook Compare play.yml roles section against profile-derived roles
"""

import argparse
import json
import sys
import yaml
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Dict, List, Any, Set

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


# ---------------------------------------------------------------------------
# Role condition translation and sync
# ---------------------------------------------------------------------------

def translate_condition(role_entry: dict) -> Optional[str]:
    """
    Translate a profile role entry's conditions to a Jinja2 expression string.

    Converts profile annotations (os, requires_display, requires_config, etc.)
    into the equivalent Jinja2 expression that would be used in play.yml.

    Args:
        role_entry: A single role dict from a profile's roles list

    Returns:
        Jinja2 condition string (without "when:" prefix) or None if no conditions

    Examples:
        {role: "base", os: archlinux} → "_is_arch"
        {role: "fonts", requires_display: true, os: archlinux} → "_is_arch and _has_display"
        {role: "dotfiles", config_check: "dotfiles is defined"} → "dotfiles is defined"
    """
    conditions = []

    # OS condition
    os_val = role_entry.get("os")
    if os_val:
        if os_val == "archlinux":
            conditions.append("_is_arch")
        elif os_val == "debian":
            conditions.append("not _is_arch")
        else:
            # Unknown OS spec - include as-is for safety
            conditions.append(f"ansible_facts['os_family'] == '{os_val}'")

    # Display condition
    if role_entry.get("requires_display"):
        conditions.append("_has_display")

    # Config check condition
    config_check = role_entry.get("config_check")
    if config_check:
        conditions.append(config_check)

    # Special: requires_config with display_manager value
    requires_config = role_entry.get("requires_config", {})
    if isinstance(requires_config, dict):
        dm_val = requires_config.get("display_manager")
        if dm_val:
            # e.g., {requires_config: {display_manager: lightdm}} → "_dm == 'lightdm'"
            conditions.append(f'_dm == "{dm_val}"')

    return " and ".join(conditions) if conditions else None


def normalize_condition(condition: Any) -> Optional[str]:
    """
    Normalize a play.yml condition string to canonical form for comparison.

    Removes unnecessary quotes, normalizes boolean expressions, normalizes
    quote styles, and handles different formatting styles to ensure semantic
    equivalence is recognized.

    Args:
        condition: A when clause value from play.yml (str, bool, or None)

    Returns:
        Normalized condition string or None

    Examples:
        "_has_display and _is_arch" → "_has_display and _is_arch"
        '"_has_display and _is_arch"' → "_has_display and _is_arch"
        "_dm == 'lightdm'" → '_dm == "lightdm"' (normalize to double quotes)
        "_has_display | bool" → "_has_display" (| bool is redundant for boolean vars)
        true → None (unconditional)
        None → None
    """
    if not condition or condition is True:
        return None

    # Convert to string
    cond_str = str(condition).strip()

    # Remove surrounding quotes if present
    if (cond_str.startswith('"') and cond_str.endswith('"')) or \
       (cond_str.startswith("'") and cond_str.endswith("'")):
        cond_str = cond_str[1:-1].strip()

    # Normalize single quotes to double quotes for string comparisons
    # This handles: _dm == 'lightdm' → _dm == "lightdm"
    import re
    cond_str = re.sub(r"(\w+)\s*==\s*'([^']*)'", r'\1 == "\2"', cond_str)

    # Remove | bool filter (redundant for boolean variables like _has_display, _is_arch)
    # In Jinja2, boolean variables don't need | bool - they're already booleans
    # This normalization allows semantic equivalence to be recognized
    cond_str = re.sub(r'\s*\|\s*bool(?=\s*(?:and|or|\)|$))', '', cond_str)

    return cond_str if cond_str else None


def extract_roles_from_playbook(playbook_path: str) -> Dict[str, dict]:
    """
    Extract all role entries from play.yml and return as a dict keyed by role name.

    Args:
        playbook_path: Path to play.yml

    Returns:
        Dict mapping role name → role entry dict with 'when' condition

    Raises:
        FileNotFoundError: If playbook_path doesn't exist
        yaml.YAMLError: If playbook is not valid YAML
    """
    with open(playbook_path) as f:
        playbook = yaml.safe_load(f)

    # Extract roles from the first play
    roles_section = playbook[0].get("roles", [])

    result = {}
    for role_entry in roles_section:
        # Normalize role entry: might be string or dict
        if isinstance(role_entry, str):
            role_name = role_entry
            role_when = None
        else:
            # Dict format: {role: name, when: condition, tags: [...]}
            role_name = role_entry.get("role")
            role_when = role_entry.get("when")

        if role_name:
            result[role_name] = {
                "name": role_name,
                "when": normalize_condition(role_when),
            }

    return result


def generate_expected_roles(profiles_dir: str) -> Dict[str, dict]:
    """
    Generate expected role entries from all profile YAML files.

    Loads each profile independently and collects all roles with their
    translated conditions. For roles that appear in multiple profiles,
    tracks the most restrictive condition (the one that must be satisfied
    for all profiles that use the role).

    Args:
        profiles_dir: Directory containing profile YAML files

    Returns:
        Dict mapping role name → role entry dict with 'when' condition
    """
    result = {}

    # Get all profile names
    profile_names = list_profiles(profiles_dir)

    # Also include _base if it exists
    try:
        load_profile(profiles_dir, "_base")
        profile_names = ["_base"] + [n for n in profile_names if n != "_base"]
    except ValueError:
        pass

    # Process each profile independently
    for profile_name in profile_names:
        try:
            profile_data = load_profile(profiles_dir, profile_name)
            roles_list = profile_data.get("roles", [])
        except (ValueError, yaml.YAMLError):
            continue

        for role_entry in roles_list:
            if isinstance(role_entry, dict):
                role_name = role_entry.get("role")
            else:
                role_name = str(role_entry)

            if not role_name:
                continue

            # Compute condition for this role from this profile
            if isinstance(role_entry, dict):
                condition = translate_condition(role_entry)
            else:
                condition = None

            # Track the most restrictive condition
            # None is least restrictive, then simple conditions, then complex ones
            if role_name not in result:
                result[role_name] = {
                    "name": role_name,
                    "when": condition,
                }
            else:
                existing_cond = result[role_name]["when"]
                # Update to the new condition if:
                # - old is None and new is not None (conditional is more restrictive)
                # - new has more parts than old (more specific)
                if existing_cond is None and condition is not None:
                    result[role_name]["when"] = condition
                elif existing_cond is not None and condition is not None:
                    # Both have conditions - keep the one with more constraints
                    existing_parts = len(existing_cond.split(" and "))
                    new_parts = len(condition.split(" and "))
                    if new_parts > existing_parts:
                        result[role_name]["when"] = condition

    return result


def compare_roles(expected: Dict[str, dict], actual: Dict[str, dict]) -> dict:
    """
    Compare expected and actual role entries.

    Returns a dict with keys:
        missing: roles in expected but not in actual
        extra: roles in actual but not in expected
        mismatch: roles with different conditions
    """
    expected_roles = set(expected.keys())
    actual_roles = set(actual.keys())

    missing = expected_roles - actual_roles
    extra = actual_roles - expected_roles

    # Check for condition mismatches
    mismatch = {}
    common = expected_roles & actual_roles
    for role_name in common:
        expected_when = expected[role_name]["when"]
        actual_when = actual[role_name]["when"]

        # Normalize both for comparison
        expected_norm = normalize_condition(expected_when) or ""
        actual_norm = normalize_condition(actual_when) or ""

        # Check if actual condition is a superset or matches expected
        # A playbook condition can be broader than the profile condition
        # e.g., if profile expects "_is_arch", playbook "_is_arch and _has_display" is valid
        if expected_norm and expected_norm not in actual_norm:
            # Expected condition is not a subset of actual condition
            # We need to check if actual is actually equivalent or broader
            if not _is_condition_superset(actual_norm, expected_norm):
                mismatch[role_name] = {
                    "expected": expected_when,
                    "actual": actual_when,
                }
        elif not expected_norm and actual_norm:
            # Profile says unconditional, but playbook has a condition
            # This could be valid if the role is DE-specific in other profiles
            # We'll allow it for now to avoid false positives
            pass

    return {
        "missing": sorted(missing),
        "extra": sorted(extra),
        "mismatch": mismatch,
    }


def _is_condition_superset(actual: str, expected: str) -> bool:
    """
    Check if actual condition is a superset of expected condition.

    This handles cases where the playbook condition is broader than
    the profile condition, which is valid.

    Args:
        actual: The normalized playbook condition
        expected: The normalized profile condition

    Returns:
        True if actual implies expected (actual is a superset or equivalent)
    """
    # Simple substring check for now
    # e.g., "_is_arch and _has_display" is a superset of "_is_arch"
    # This works for most cases but might need more sophisticated logic
    if expected in actual:
        return True

    # Check for logical equivalence with different ordering
    # Split by " and " and check if all expected parts are in actual
    expected_parts = [p.strip() for p in expected.split(" and ")]
    actual_parts = [p.strip() for p in actual.split(" and ")]

    return all(part in actual_parts for part in expected_parts)


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
    """Compare play.yml roles against profile-derived roles; exit 1 on drift in check mode."""
    try:
        # Generate expected roles from profiles
        expected = generate_expected_roles(args.profiles_dir)

        # Extract actual roles from playbook
        actual = extract_roles_from_playbook(args.playbook)

        # Compare
        diff = compare_roles(expected, actual)

        # Check if there are any differences
        has_drift = bool(diff["missing"] or diff["extra"] or diff["mismatch"])

        if not has_drift:
            if not args.check:
                print("✓ play.yml is in sync with profiles")
            return 0

        # There is drift - report it
        if args.check:
            # CI mode: exit 1 with minimal output
            print("play.yml is out of sync with profiles. Run 'make sync-playbook' to see diff.", file=sys.stderr)
            return 1

        # Developer mode: show detailed diff
        print("play.yml is out of sync with profiles:\n")

        if diff["missing"]:
            print("Missing roles (in profiles but not in play.yml):")
            for role in diff["missing"]:
                cond = expected[role]["when"]
                if cond:
                    print(f"  - {role}  # when: {cond}")
                else:
                    print(f"  - {role}")
            print()

        if diff["extra"]:
            print("Extra roles (in play.yml but not in any profile):")
            for role in diff["extra"]:
                cond = actual[role]["when"]
                if cond:
                    print(f"  - {role}  # when: {cond}")
                else:
                    print(f"  - {role}")
            print()

        if diff["mismatch"]:
            print("Roles with mismatched conditions:")
            for role, details in diff["mismatch"].items():
                print(f"  - {role}")
                print(f"      Expected: when: {details['expected']}")
                print(f"      Actual:   when: {details['actual']}")
            print()

        return 1

    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (yaml.YAMLError, ValueError) as exc:
        print(f"Error parsing YAML: {exc}", file=sys.stderr)
        return 1


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
        help="Compare play.yml roles against profile-derived roles.",
    )
    p_sync.add_argument(
        "--profiles-dir", dest="profiles_dir", default=_DEFAULT_PROFILES_DIR
    )
    p_sync.add_argument(
        "--playbook",
        default=str(Path(__file__).parent.parent / "play.yml"),
        help="Path to play.yml (default: ../play.yml)"
    )
    p_sync.add_argument(
        "--check",
        action="store_true",
        help="CI mode: exit 1 on drift, minimal output"
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
