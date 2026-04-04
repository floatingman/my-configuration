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
from typing import Optional

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


# ---------------------------------------------------------------------------
# sync-playbook helpers
# ---------------------------------------------------------------------------

def _translate_os_condition(os_value: str) -> str:
    """Translate os: archlinux/debian to Jinja2 condition."""
    if os_value == "archlinux":
        return "_is_arch"
    elif os_value == "debian":
        return "not _is_arch"
    else:
        return f"_os_{os_value}"  # Fallback for other values


def _translate_requires_config(requires_config: dict) -> str:
    """Translate requires_config to Jinja2 condition."""
    if "display_manager" in requires_config:
        dm = requires_config["display_manager"]
        return f"_has_display and _dm == '{dm}'"
    # Fallback: join all conditions with 'and'
    parts = []
    for key, value in requires_config.items():
        if key == "display_manager":
            parts.append(f"_has_display and _dm == '{value}'")
        else:
            parts.append(f"{key} == {repr(value)}")
    return " and ".join(parts)


_DE_ROLES = {"i3", "hyprland", "gnome", "awesomewm", "kde"}


def _translate_role_entry(role_entry: dict | str, profile_de: str | None = None) -> dict:
    """
    Translate a profile role entry to a play.yml role entry with 'when' condition.

    Args:
        role_entry: Role entry from profile YAML (dict or string)
        profile_de: Desktop environment of the profile (i3, hyprland, etc.) if DE-specific

    Returns:
        Dict with 'role' and optional 'tags', 'when' keys
    """
    if isinstance(role_entry, str):
        role_entry = {"role": role_entry}

    result = {"role": role_entry["role"]}
    if "tags" in role_entry:
        result["tags"] = role_entry["tags"]

    conditions = []

    # Special handling for DE-specific roles - use _is_* flags
    role_name = role_entry["role"]
    if role_name in _DE_ROLES:
        de_flag = f"_is_{role_name}"
        conditions.append(de_flag)
    else:
        # For non-DE roles, build condition from attributes
        if "os" in role_entry:
            conditions.append(_translate_os_condition(role_entry["os"]))

        if role_entry.get("requires_display"):
            conditions.append("_has_display")

        if "config_check" in role_entry:
            conditions.append(role_entry["config_check"])

        if "requires_config" in role_entry:
            conditions.append(_translate_requires_config(role_entry["requires_config"]))

        # If in a DE-specific profile and no explicit conditions, inherit DE condition
        if profile_de and not conditions:
            conditions.append(f"_is_{profile_de}")

    if conditions:
        result["when"] = " and ".join(conditions)

    return result


def _parse_playbook_roles(playbook_path: str) -> dict:
    """
    Parse play.yml and extract role entries.

    Args:
        playbook_path: Path to play.yml

    Returns:
        Dict mapping role name to role entry dict (with 'when', 'tags')
    """
    with open(playbook_path) as f:
        playbook = yaml.safe_load(f)

    roles_dict = {}
    for play in playbook:
        if "roles" not in play:
            continue
        for entry in play["roles"]:
            # Handle both dict and string role entries
            if isinstance(entry, str):
                name = entry
                roles_dict[name] = {"role": name}
            elif isinstance(entry, dict):
                name = entry["role"]
                roles_dict[name] = entry
    return roles_dict


def _build_expected_roles(profiles_dir: str) -> dict:
    """
    Build expected role entries from all profiles.

    Args:
        profiles_dir: Directory containing profile YAML files

    Returns:
        Dict mapping role name to role entry dict (with 'when', 'tags')
    """
    profiles_path = Path(profiles_dir)

    # Track which DE profiles have each role WITHOUT explicit conditions (from direct roles only)
    role_de_profiles = {}  # role_name -> set of DE values (only for roles without explicit conditions)
    profile_de_map = {}  # profile_name -> desktop_environment

    # First pass: collect which DE profiles have roles without explicit conditions
    for profile_file in profiles_path.glob("*.yml"):
        # Skip underscore files (like _base.yml) and subdirectories (overlays/)
        if profile_file.stem.startswith("_") or profile_file.parent != profiles_path:
            continue

        profile_name = profile_file.stem

        # Load the profile's direct file to get only the roles it defines (not inherited)
        with open(profile_file) as f:
            direct_data = yaml.safe_load(f) or {}

        profile_de = direct_data.get("desktop_environment")
        if profile_de == "":
            profile_de = None
        profile_de_map[profile_name] = profile_de

        # Only track direct roles (not inherited from _base) in DE profiles
        direct_roles = direct_data.get("roles", [])
        if profile_de and profile_de in _DE_ROLES:
            for role_entry in direct_roles:
                # Check if role has explicit conditions
                entry_dict = role_entry if isinstance(role_entry, dict) else {}
                has_explicit = any(
                    k in entry_dict for k in ["os", "requires_display", "config_check", "requires_config"]
                )

                if not has_explicit:
                    # Role has no explicit conditions - track it for DE inheritance
                    role_name = role_entry["role"] if isinstance(role_entry, dict) else role_entry
                    if role_name not in role_de_profiles:
                        role_de_profiles[role_name] = set()
                    role_de_profiles[role_name].add(profile_de)

    # Second pass: build expected roles from merged profile data
    expected = {}
    for profile_file in profiles_path.glob("*.yml"):
        if profile_file.stem.startswith("_") or profile_file.parent != profiles_path:
            continue

        profile_name = profile_file.stem

        try:
            profile_data = load_profile(profiles_dir, profile_name)
        except (ValueError, yaml.YAMLError):
            continue

        if "roles" not in profile_data:
            continue

        profile_de = profile_de_map[profile_name]

        for role_entry in profile_data["roles"]:
            role_name = role_entry["role"] if isinstance(role_entry, dict) else role_entry

            # Determine the appropriate DE condition for this role
            if role_name in role_de_profiles:
                # Role is directly defined in one or more DE profiles without explicit conditions
                des = role_de_profiles[role_name]
                if len(des) == 1:
                    # Single DE profile - inherit that DE
                    role_de = list(des)[0]
                    translated = _translate_role_entry(role_entry, profile_de=role_de)
                else:
                    # Multiple DE profiles - use OR of DE conditions
                    result = _translate_role_entry(role_entry, profile_de=None)
                    # Override the 'when' with the OR condition
                    de_conditions = [f"_is_{de}" for de in sorted(des)]
                    if de_conditions:
                        result["when"] = " or ".join(de_conditions)
                    translated = result
            else:
                # Role has explicit conditions or is from _base/non-DE profile - no DE inheritance
                translated = _translate_role_entry(role_entry, profile_de=None)

            # Later entries override earlier ones (last write wins)
            expected[role_name] = translated

    return expected


def _normalize_condition(condition: str | None) -> str | None:
    """
    Normalize a condition string for comparison.

    Sorts AND terms for commutative comparison (ignores ordering differences).
    """
    if not condition:
        return None
    # Split by ' and ' and sort
    terms = [t.strip() for t in condition.split(" and ")]
    return " and ".join(sorted(terms))


def _compare_roles(actual: dict, expected: dict) -> dict:
    """
    Compare actual vs expected role entries.

    Returns:
        Dict with 'missing', 'extra', 'mismatch' keys
    """
    actual_names = set(actual.keys())
    expected_names = set(expected.keys())

    missing = expected_names - actual_names
    extra = actual_names - expected_names

    mismatch = []
    common = actual_names & expected_names
    for name in sorted(common):
        actual_when = _normalize_condition(actual[name].get("when"))
        expected_when = _normalize_condition(expected[name].get("when"))
        if actual_when != expected_when:
            mismatch.append({
                "role": name,
                "expected_when": expected_when,
                "actual_when": actual_when,
            })

    return {
        "missing": sorted(missing),
        "extra": sorted(extra),
        "mismatch": mismatch,
    }


def _cmd_sync_playbook(args: argparse.Namespace) -> int:
    """Sync playbook check; exit 1 on drift, 0 if in sync."""
    profiles_dir = args.profiles_dir
    playbook_path = args.playbook
    check_mode = args.check

    try:
        actual = _parse_playbook_roles(playbook_path)
    except (FileNotFoundError, yaml.YAMLError) as exc:
        print(f"Error reading playbook: {exc}", file=sys.stderr)
        return 1

    expected = _build_expected_roles(profiles_dir)
    comparison = _compare_roles(actual, expected)

    has_drift = bool(comparison["missing"] or comparison["extra"] or comparison["mismatch"])

    if not has_drift:
        if not check_mode:
            print("play.yml is in sync with profiles")
        return 0

    # Report drift
    if comparison["missing"]:
        print("Missing roles (in profiles but not in play.yml):")
        for role in comparison["missing"]:
            print(f"  - {role}")
        print()

    if comparison["extra"]:
        print("Extra roles (in play.yml but not in profiles):")
        for role in comparison["extra"]:
            print(f"  - {role}")
        print()

    if comparison["mismatch"]:
        print("Roles with condition mismatches:")
        for item in comparison["mismatch"]:
            print(f"  - {item['role']}")
            print(f"      Expected: when: {repr(item['expected_when'])}")
            print(f"      Actual:   when: {repr(item['actual_when'])}")
        print()

    return 1 if check_mode else 0


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
        help="Compare play.yml roles against profiles; report drift.",
    )
    p_sync.add_argument(
        "--profiles-dir",
        dest="profiles_dir",
        default=_DEFAULT_PROFILES_DIR,
        help="Directory containing profile YAML files",
    )
    p_sync.add_argument(
        "--playbook",
        default="play.yml",
        help="Path to play.yml (default: play.yml)",
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
