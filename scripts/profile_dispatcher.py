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
from typing import List, Optional, Protocol, Tuple

import jinja2

# Default profiles directory relative to this script's location
_DEFAULT_PROFILES_DIR = str(Path(__file__).parent.parent / "profiles")

# Allowed values for profile fields
ALLOWED_DISPLAY_MANAGERS = {"", "lightdm", "gdm", "sddm"}
ALLOWED_DESKTOP_ENVIRONMENTS = {"", "i3", "hyprland", "gnome", "awesomewm", "kde"}


# ---------------------------------------------------------------------------
# Overlay data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedOverlayRole:
    """
    Result of overlay role resolution.

    Attributes:
        role: Role name
        tags: Tuple of tags for this role
        applies: Whether this role applies (based on OS-specific conditions)
    """
    role: str
    tags: Tuple[str, ...]
    applies: bool


@dataclass(frozen=True)
class ResolvedOverlay:
    """
    Result of overlay resolution with per-role applies status.

    Attributes:
        overlay: The loaded overlay data
        applies: Whether the overlay-level applies_when evaluated to True
        resolved_roles: List of tuples (role_entry, applies) where applies is per-role boolean
    """
    overlay: "Overlay"
    applies: bool
    resolved_roles: Tuple[tuple[RoleEntry, bool], ...]


@dataclass(frozen=True)
class OverlayDefinition:
    """
    Parsed overlay YAML file.

    Attributes:
        name: Overlay name from YAML
        description: Optional description from YAML
        applies_when: Jinja2 condition string for when this overlay applies
        roles: List of role entries (each is a dict with 'role' key and optional annotations)
    """
    name: str
    description: Optional[str]
    applies_when: str
    roles: List[dict]


# ---------------------------------------------------------------------------
# Expression Evaluation
# ---------------------------------------------------------------------------


class EvaluationError(Exception):
    """Raised when an expression cannot be evaluated.

    This typically indicates a syntax error in the expression or
    an undefined variable that cannot be resolved.
    """
    pass


class ConditionEvaluator(Protocol):
    """Protocol for condition expression evaluation.

    Any class implementing evaluate() can be used as a condition evaluator,
    enabling test injection and zero-dependency mocks.
    """

    def evaluate(self, expression: str, context: dict) -> bool:
        """Evaluate a condition expression against a context dict.

        Args:
            expression: A condition expression (e.g., "laptop", "x is defined", "x.enabled")
            context: Dictionary of variables available to the expression

        Returns:
            True if the expression evaluates to truthy, False otherwise

        Raises:
            EvaluationError: If the expression cannot be parsed or evaluated
        """
        ...


class Jinja2Evaluator:
    """Evaluates conditions using Jinja2 template syntax.

    Supports the full range of Jinja2 expressions:
    - Variable existence: "laptop", "bluetooth is defined"
    - Default values: "laptop | default(false)"
    - Boolean operators: "laptop and not (desktop | default(false))"
    - Nested dict access: "bluetooth.disable", "laptop.hardware.trackpad"
    - Parenthesized expressions: "(laptop or desktop) and gui"

    This evaluator is used in production to evaluate overlay conditions.
    """

    def __init__(self) -> None:
        # Use StrictUndefined to catch missing variables explicitly
        # (rather than rendering them as empty strings)
        self._env = jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            autoescape=False,
        )

    def evaluate(self, expression: str, context: dict) -> bool:
        """Evaluate a Jinja2 condition expression.

        Wraps the expression in an if-else template to extract a boolean result.

        Args:
            expression: Jinja2 condition expression
            context: Variables available to the expression

        Returns:
            True if the expression is truthy, False otherwise

        Raises:
            EvaluationError: If the expression cannot be parsed or contains
                            undefined variables (without default filters)
        """
        # Wrap expression in a template that outputs __TRUE__ or __FALSE__
        template_str = (
            "{% if " + expression + " %}__TRUE__{% else %}__FALSE__{% endif %}"
        )

        try:
            template = self._env.from_string(template_str)
            result = template.render(**context)
        except (jinja2.TemplateError, jinja2.UndefinedError) as exc:
            raise EvaluationError(
                f"Failed to evaluate expression '{expression}': {exc}"
            ) from exc

        return result.strip() == "__TRUE__"


class DictEvaluator:
    """Evaluates conditions by looking them up in a dictionary.

    Returns the mapped boolean value if the expression is a key in the dict,
    otherwise returns False. This is useful in tests that want to isolate
    resolution logic from expression evaluation semantics.

    Example:
        evaluator = DictEvaluator({"laptop": True, "desktop": False})
        evaluator.evaluate("laptop", {})  # Returns True
        evaluator.evaluate("desktop", {})  # Returns False
        evaluator.evaluate("unknown", {})  # Returns False
    """

    def __init__(self, mapping: dict[str, bool]) -> None:
        """Initialize with a mapping of expression strings to boolean results.

        Args:
            mapping: Dictionary mapping expression strings to their evaluation results
        """
        self._mapping = dict(mapping)

    def evaluate(self, expression: str, context: dict) -> bool:
        """Evaluate an expression by looking it up in the mapping.

        Args:
            expression: Expression string to look up
            context: Ignored (kept for protocol compatibility)

        Returns:
            The mapped boolean value, or False if the expression is not in the mapping
        """
        return self._mapping.get(expression, False)


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


# ---------------------------------------------------------------------------
# Overlay Data Model (Slice 2)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoleEntry:
    """
    A single role within an overlay with optional annotations.

    Attributes:
        role: The role name (e.g., 'laptop', 'bluetooth')
        tags: List of tags to apply when this role is activated
        os: OS family constraint ('archlinux', 'debian', or None for any OS)
        requires_display: Whether this role requires a display server
    """
    role: str
    tags: Tuple[str, ...]
    os: Optional[str] = None
    requires_display: bool = False


@dataclass(frozen=True)
class Overlay:
    """
    An overlay loaded from a YAML file.

    Attributes:
        name: Human-readable name for the overlay
        description: Free-form description
        applies_when: Jinja2 expression string to evaluate against facts
        roles: Tuple of role entries with their annotations
    """
    name: str
    description: str
    applies_when: str
    roles: Tuple[RoleEntry, ...]


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


# ---------------------------------------------------------------------------
# Overlay Discovery and Loading (Slice 2)
# ---------------------------------------------------------------------------

def _discover_overlays(profiles_dir: str) -> list[Path]:
    """
    Discover all overlay YAML files in profiles/overlays/ subdirectory.

    Args:
        profiles_dir: Root profiles directory

    Returns:
        List of overlay file paths, sorted alphabetically
    """
    overlays_root = Path(profiles_dir) / "overlays"
    if not overlays_root.exists():
        return []

    return sorted(
        p for p in overlays_root.glob("*.yml") if not p.stem.startswith("_")
    )


def _load_overlay(path: Path) -> Overlay:
    """
    Load a single overlay from a YAML file.

    Args:
        path: Path to overlay YAML file

    Returns:
        Overlay dataclass instance

    Raises:
        ValueError: If the file cannot be parsed or has invalid structure
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        raise ValueError(f"Failed to load overlay '{path}': {exc}")

    # Validate required fields
    if "name" not in data:
        raise ValueError(f"Overlay '{path}': missing required field 'name'")
    if "applies_when" not in data:
        raise ValueError(f"Overlay '{path}': missing required field 'applies_when'")
    if "roles" not in data:
        raise ValueError(f"Overlay '{path}': missing required field 'roles'")

    # Validate applies_when is a string
    applies_when = data["applies_when"]
    if not isinstance(applies_when, str) or not applies_when.strip():
        raise ValueError(
            f"Overlay '{path}': 'applies_when' must be a non-empty string, "
            f"got {type(applies_when).__name__}"
        )

    # Validate roles is a list
    roles_raw = data["roles"]
    if not isinstance(roles_raw, list):
        raise ValueError(
            f"Overlay '{path}': 'roles' must be a list, got {type(roles_raw).__name__}"
        )

    # Parse role entries
    roles = []
    for i, role_entry in enumerate(roles_raw):
        if not isinstance(role_entry, dict):
            raise ValueError(
                f"Overlay '{path}': role entry {i} must be a dict, "
                f"got {type(role_entry).__name__}"
            )

        if "role" not in role_entry:
            raise ValueError(
                f"Overlay '{path}': role entry {i} missing required field 'role'"
            )

        role_name = role_entry["role"]
        if not isinstance(role_name, str):
            raise ValueError(
                f"Overlay '{path}': role entry {i} 'role' must be a string, "
                f"got {type(role_name).__name__}"
            )

        # Validate tags (required)
        if "tags" not in role_entry:
            raise ValueError(
                f"Overlay '{path}': role entry {i} missing required field 'tags'"
            )

        tags = role_entry["tags"]
        if not isinstance(tags, list):
            raise ValueError(
                f"Overlay '{path}': role entry {i} 'tags' must be a list, "
                f"got {type(tags).__name__}"
            )

        for j, tag in enumerate(tags):
            if not isinstance(tag, str):
                raise ValueError(
                    f"Overlay '{path}': role entry {i} 'tags[{j}]' must be a string, "
                    f"got {type(tag).__name__}"
                )

        # Parse optional annotations
        allowed_os = {"archlinux", "debian"}
        os_constraint = role_entry.get("os")
        if os_constraint is not None:
            if not isinstance(os_constraint, str):
                raise ValueError(
                    f"Overlay '{path}': role entry {i} 'os' must be a string or null, "
                    f"got {type(os_constraint).__name__}"
                )
            if os_constraint not in allowed_os:
                raise ValueError(
                    f"Overlay '{path}': role entry {i} 'os' must be one of "
                    f"{sorted(allowed_os)}, got '{os_constraint}'"
                )

        requires_display = role_entry.get("requires_display", False)
        if not isinstance(requires_display, bool):
            raise ValueError(
                f"Overlay '{path}': role entry {i} 'requires_display' must be a bool, "
                f"got {type(requires_display).__name__}"
            )

        roles.append(RoleEntry(
            role=role_name,
            tags=tuple(tags),
            os=os_constraint,
            requires_display=requires_display,
        ))

    return Overlay(
        name=data["name"],
        description=data.get("description", ""),
        applies_when=applies_when,
        roles=tuple(roles),
    )


# ---------------------------------------------------------------------------
# Overlay Resolution and Validation (Slice 3)
# ---------------------------------------------------------------------------

def resolve_overlays(
    facts: dict,
    has_display: bool,
    is_arch: bool,
    profiles_dir: str = _DEFAULT_PROFILES_DIR,
    evaluator: Optional[ConditionEvaluator] = None,
) -> list[ResolvedOverlay]:
    """
    Discover and resolve overlays against host facts.

    Args:
        facts: Dictionary of host facts (e.g., from group_vars/all/local.yml)
        has_display: Whether this machine has a display server
        is_arch: Whether this is an Arch Linux system
        profiles_dir: Directory containing profiles/ subdirectory
        evaluator: ConditionEvaluator instance (defaults to Jinja2Evaluator)

    Returns:
        Sorted list of ResolvedOverlay instances with per-role applies status

    Raises:
        ValueError: If an overlay fails to load or contains invalid expressions
    """
    if evaluator is None:
        evaluator = Jinja2Evaluator()

    overlay_paths = _discover_overlays(profiles_dir)
    results = []

    for path in overlay_paths:
        overlay = _load_overlay(path)

        # Evaluate overlay-level applies_when
        try:
            overlay_applies = evaluator.evaluate(overlay.applies_when, facts)
        except (ValueError, EvaluationError) as exc:
            raise ValueError(
                f"Overlay '{overlay.name}': failed to evaluate applies_when: {exc}"
            )

        # Resolve each role with per-role conditions
        resolved_roles = []
        for role_entry in overlay.roles:
            # Per-role applies = AND of:
            # 1. Overlay-level applies result
            # 2. OS constraint (if specified)
            # 3. requires_display constraint (if specified)
            role_applies = overlay_applies

            # Check OS constraint
            if role_entry.os is not None:
                expected_os = "archlinux" if is_arch else "debian"
                if role_entry.os != expected_os:
                    role_applies = False

            # Check requires_display constraint
            if role_entry.requires_display and not has_display:
                role_applies = False

            resolved_roles.append((role_entry, role_applies))

        results.append(ResolvedOverlay(
            overlay=overlay,
            applies=overlay_applies,
            resolved_roles=tuple(resolved_roles),
        ))

    results.sort(key=lambda resolved: resolved.overlay.name)
    return results


def validate_overlays(
    profiles_dir: str = _DEFAULT_PROFILES_DIR,
) -> list[tuple[str, list[str]]]:
    """
    Validate all overlay YAML files in profiles/overlays/.

    Checks:
    - Overlay files can be parsed as YAML
    - Required fields present (name, applies_when, roles)
    - applies_when is a non-empty string
    - roles is a list
    - Each role entry has required fields (role, tags) with correct types

    Args:
        profiles_dir: Directory containing profiles/ subdirectory

    Returns:
        List of (overlay_name, errors) tuples. Empty error list means valid.
    """
    overlay_paths = _discover_overlays(profiles_dir)
    results = []

    for path in overlay_paths:
        overlay_name = path.stem  # filename without .yml
        errors = []

        try:
            # Attempt to load the overlay - this validates all fields
            _load_overlay(path)
        except ValueError as exc:
            errors.append(str(exc))

        results.append((overlay_name, errors))

    return results


# ---------------------------------------------------------------------------
# Overlay name-based discovery and loading (from main)
# ---------------------------------------------------------------------------

def _discover_overlay_names(profiles_dir: str) -> List[str]:
    """
    Discover all overlay names in profiles_dir/overlays/.

    Scans for *.yml files in the overlays subdirectory,
    excludes files starting with '_', and returns sorted stem names.

    Args:
        profiles_dir: Directory containing profile YAML files

    Returns:
        Sorted list of overlay names (without .yml extension)
    """
    overlays_path = Path(profiles_dir) / "overlays"
    if not overlays_path.exists():
        return []

    overlay_names = [
        p.stem
        for p in overlays_path.glob("*.yml")
        if not p.stem.startswith("_")
    ]
    return sorted(overlay_names)


def load_overlay(profiles_dir: str, name: str) -> "OverlayDefinition":
    """
    Load an overlay by name from profiles_dir/overlays/.

    Args:
        profiles_dir: Directory containing the overlays subdirectory
        name: Overlay name with or without .yml extension (e.g. 'laptop' or 'laptop.yml')

    Returns:
        OverlayDefinition with parsed overlay data

    Raises:
        ValueError: If the overlay file does not exist, the name contains path separators,
                    or required fields are missing (name, applies_when, roles)
    """
    name = name.removesuffix(".yml")

    # Guard against path traversal
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError(
            f"Overlay name '{name}' contains invalid path characters. "
            "Overlay names must not include path separators or '..'."
        )

    profiles_root = Path(profiles_dir).resolve()
    overlay_path = profiles_root / "overlays" / f"{name}.yml"

    # Enforce the path stays inside profiles_dir/overlays
    try:
        overlay_path.resolve().relative_to(profiles_root)
    except ValueError:
        raise ValueError(
            f"Overlay '{name}' resolves outside the overlays directory."
        )

    if not overlay_path.exists():
        raise ValueError(
            f"Overlay '{name}' not found at {overlay_path}"
        )

    with open(overlay_path) as f:
        data = yaml.safe_load(f) or {}

    # Validate required fields
    required_fields = ["name", "applies_when", "roles"]
    missing = [field for field in required_fields if field not in data]
    if missing:
        raise ValueError(
            f"Overlay '{name}' is missing required fields: {', '.join(missing)}"
        )

    return OverlayDefinition(
        name=data["name"],
        description=data.get("description"),
        applies_when=data["applies_when"],
        roles=data["roles"]
    )



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
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
