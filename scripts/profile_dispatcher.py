#!/usr/bin/env python3
"""
Profile Dispatcher - Core Resolver and CLI

Pure function for resolving Ansible profile configuration into boolean flags.
Supports both profile mode (profile name) and manual mode (explicit variables).

This is a standalone Python module with no Ansible dependency,
making the dispatch logic unit-testable.

CLI subcommands:
  resolve              Resolve a profile to JSON (for Ansible script module)
  resolve-manifest     Resolve profile to manifest JSON with OS detection (for Ansible)
  resolve-role-manifest Resolve a complete role manifest with computed conditions
  resolve-overlays     Resolve overlays against host facts and output JSON
  sync-playbook        Compare play.yml roles with profile-derived expected roles
  validate             Validate all profiles and overlays in a directory (for CI)
  list-profiles        List available profile names or a human-readable table
  make-args            Output -e flag string for Makefile consumption
"""

import argparse
import json
import sys
import yaml
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

import jinja2

# Default profiles directory relative to this script's location
_DEFAULT_PROFILES_DIR = str(Path(__file__).parent.parent / "profiles")

# Allowed values for profile fields
ALLOWED_DISPLAY_MANAGERS = {"", "lightdm", "gdm", "sddm"}
ALLOWED_DESKTOP_ENVIRONMENTS = {"", "i3", "hyprland", "gnome", "awesomewm", "kde"}


# ---------------------------------------------------------------------------
# Condition Translator Protocol (Slice 1 - Issue #104)
# ---------------------------------------------------------------------------


class ConditionTranslator(Protocol):
    """Protocol for translating role annotations to Jinja2 conditions.

    This protocol enables test doubles and alternative implementations
    for condition translation. The default implementation is
    AnsibleConditionTranslator which wraps the existing translate_condition()
    logic.

    Methods:
        translate_annotation: Convert role annotations to Jinja2 condition
        translate_profile_gate: Compute profile-gating conditions
        combine_conditions: Combine annotation and profile-gate conditions
    """

    def translate_annotation(
        self,
        annotation: str | dict[str, Any],
        host_vars: dict,
    ) -> str:
        """Translate role annotations to a Jinja2 condition string.

        Args:
            annotation: Role entry as either a plain role name string or a role
                        dict with annotations (role, tags, os, requires_display,
                        requires_config, config_check)
            host_vars: Host variables dict for config_check evaluation

        Returns:
            Jinja2 condition string (empty string if no condition)
        """
        ...

    def translate_profile_gate(
        self,
        role_name: str,
        member_profiles: list[str],
        all_profiles: list[str],
        de_profile_map: dict[str, str],
    ) -> str:
        """Translate profile membership into a Jinja2 condition.

        For roles that are exclusive to certain desktop environment profiles,
        this generates the appropriate profile-gating condition (e.g., _is_i3).

        Args:
            role_name: The role name
            member_profiles: List of profile names that include this role
            all_profiles: List of all valid profile names
            de_profile_map: Mapping of desktop environment names to profile names

        Returns:
            Jinja2 condition string for profile-gating (empty string if no gate)

        Note:
            In Slice 1, this is a pass-through that returns empty string.
            Profile-gating logic will be implemented in Slice 3.
        """
        ...

    def combine_conditions(
        self,
        annotation_condition: str,
        profile_gate: str,
    ) -> str:
        """Combine annotation and profile-gating conditions with AND.

        Args:
            annotation_condition: Condition from translate_annotation (may be empty)
            profile_gate: Condition from translate_profile_gate (may be empty)

        Returns:
            Combined Jinja2 condition (AND of both, or whichever is non-empty,
            or empty string if both are empty)
        """
        ...


class AnsibleConditionTranslator:
    """Concrete implementation of ConditionTranslator that wraps translate_condition().

    This class wraps the existing translate_condition() function to implement
    the ConditionTranslator protocol, preserving proven behavior while enabling
    test injection and future extensibility.
    """

    def __init__(
        self,
        os_family: str = "Archlinux",
        evaluator: Any = None,
        preserve_config_check: bool = False,
    ) -> None:
        """Initialize the translator.

        Args:
            os_family: OS family ('Archlinux' or 'Debian')
            evaluator: Optional evaluator for config_check expressions
            preserve_config_check: Keep config_check as raw Jinja2 (for static comparison)
        """
        self._os_family = os_family
        self._evaluator = evaluator
        self._preserve_config_check = preserve_config_check

    def translate_annotation(
        self,
        annotation: str | dict[str, Any],
        host_vars: dict,
    ) -> str:
        """Translate role annotations to a Jinja2 condition string."""
        return translate_condition(
            role_entry=annotation,
            host_vars=host_vars,
            os_family=self._os_family,
            evaluator=self._evaluator,
            preserve_config_check=self._preserve_config_check,
        )

    def translate_profile_gate(
        self,
        role_name: str,
        member_profiles: list[str],
        all_profiles: list[str],
        de_profile_map: dict[str, str],
    ) -> str:
        """Translate profile membership into a Jinja2 condition.

        Note: This is a pass-through implementation for Slice 1.
        Profile-gating logic will be implemented in Slice 3.
        """
        # Slice 1: Pass-through (profile-gating not implemented yet)
        return ""

    def combine_conditions(
        self,
        annotation_condition: str,
        profile_gate: str,
    ) -> str:
        """Combine annotation and profile-gating conditions with AND."""
        if annotation_condition and profile_gate:
            return f"{annotation_condition} and {profile_gate}"
        elif annotation_condition:
            return annotation_condition
        elif profile_gate:
            return profile_gate
        else:
            return ""


class DefaultTranslator(AnsibleConditionTranslator):
    """Convenience default translator with Ansible semantics.

    This preserves the existing constructor-style API while ensuring the
    CapWords name refers to an actual class rather than a factory function.
    Inherits all behavior from AnsibleConditionTranslator with default settings.
    """

    def __init__(
        self,
        os_family: str = "Archlinux",
        evaluator: Any = None,
        preserve_config_check: bool = False,
    ) -> None:
        """Initialize the default Ansible translator.

        Args:
            os_family: OS family ('Archlinux' or 'Debian')
            evaluator: Optional evaluator for config_check expressions
            preserve_config_check: Keep config_check as raw Jinja2
        """
        super().__init__(
            os_family=os_family,
            evaluator=evaluator,
            preserve_config_check=preserve_config_check,
        )


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
    resolved_roles: Tuple[tuple["RoleEntry", bool], ...]


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


@dataclass(frozen=True)
class Manifest:
    """
    Complete manifest for Ansible playbook execution.

    Combines profile resolution with OS detection into a single payload.

    Attributes:
        profile: The profile name that was resolved (or 'manual' for manual mode)
        display_manager: The display manager to use ('gdm', 'lightdm', 'sddm', or None)
        has_display: Whether this machine has any display/GUI
        is_i3: Whether to install i3 window manager
        is_hyprland: Whether to install Hyprland compositor
        is_gnome: Whether to install GNOME desktop
        is_awesomewm: Whether to install AwesomeWM window manager
        is_kde: Whether to install KDE Plasma desktop
        is_arch: Whether the OS is Arch Linux (computed from os_family)
    """
    profile: str
    display_manager: Optional[str]
    has_display: bool
    is_i3: bool
    is_hyprland: bool
    is_gnome: bool
    is_awesomewm: bool
    is_kde: bool
    is_arch: bool


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
    profile_flags: Dict[str, Any]
    overlay_flags: Dict[str, bool]
    roles: Tuple[RoleCondition, ...]


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


def translate_condition(
    role_entry: dict,
    host_vars: dict,
    os_family: str,
    evaluator: Any = None,
    preserve_config_check: bool = False,
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
        preserve_config_check: When True, keep config_check as a raw Jinja2
            expression instead of evaluating it.  Use this for static comparison
            (e.g., sync-playbook) where host_vars are not available.

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

    # Config condition: requires_config: {display_manager: lightdm} → _has_display and _dm == 'lightdm'
    requires_config = role_dict.get("requires_config")
    if requires_config and isinstance(requires_config, dict):
        if "display_manager" in requires_config:
            dm_value = requires_config["display_manager"]
            conditions.append("_has_display")
            conditions.append(f"_dm == '{dm_value}'")

    # config_check: evaluate the expression and return boolean result
    config_check = role_dict.get("config_check")
    if config_check:
        if preserve_config_check:
            # Keep as-is for static comparison (sync-playbook); don't evaluate
            conditions.append(config_check)
        elif evaluator:
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


def _normalize_condition(cond: Optional[str]) -> str:
    """Normalize a condition string for comparison.

    Strips '| bool' filters, sorts AND terms alphabetically
    so that semantically equivalent conditions compare equal.
    """
    if not cond:
        return ""
    s = cond.strip()
    # Strip Ansible '| bool' filter (semantically redundant for booleans)
    s = s.replace(" | bool", "")
    # Sort AND terms for commutativity
    parts = sorted(p.strip() for p in s.split(" and "))
    return " and ".join(parts)


def resolve_role_manifest(
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
    preserve_config_check: bool = False,
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
        preserve_config_check: When True, keep config_check as raw Jinja2
            expressions rather than evaluating them.

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
            # Support both dict (old API) and OverlayDefinition (new API)
            if isinstance(overlay_data, dict):
                applies_when = overlay_data.get("applies_when")
                overlay_roles_list = overlay_data.get("roles", [])
            else:
                applies_when = overlay_data.applies_when
                overlay_roles_list = overlay_data.roles
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
                # Also emit per-role flags for consistency with resolve-overlays
                for overlay_role in overlay_roles_list:
                    if isinstance(overlay_role, str):
                        rname = overlay_role
                    elif isinstance(overlay_role, dict):
                        rname = overlay_role.get("role", "")
                    else:
                        rname = getattr(overlay_role, "role", "")
                    if rname:
                        overlay_flags[f"_overlay_{rname}"] = True
                overlay_roles.extend(overlay_roles_list)
        except (ValueError, yaml.YAMLError):
            # Skip invalid overlays
            continue

    # Combine roles from profile and overlays
    all_roles = profile_roles + overlay_roles

    # Build manifest: translate conditions and deduplicate by role name
    role_map: Dict[str, RoleCondition] = {}
    # Track normalized OR-disjuncts per role to avoid duplicate terms on 3+ merges
    role_disjuncts: Dict[str, Set[str]] = {}

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
        condition = translate_condition(role_entry, host_vars, os_family, evaluator, preserve_config_check)

        # Deduplicate: merge conditions and union tags if role already exists
        norm_cond = _normalize_condition(condition)
        if role_name in role_map:
            existing = role_map[role_name]

            # Union tags from all sources
            merged_tags = tuple(sorted(set(existing.tags + tags)))

            # Merge conditions using tracked disjuncts to avoid duplicates
            disjuncts = role_disjuncts[role_name]
            merged_source = existing.source

            if condition and norm_cond not in disjuncts:
                # New condition term — add to disjunct set and OR into condition
                disjuncts.add(norm_cond)
                if existing.condition:
                    merged_condition = f"({existing.condition}) or ({condition})"
                    merged_source = f"{existing.source}+overlay"
                else:
                    merged_condition = condition
                    merged_source = source
            else:
                # Condition already tracked (or no new condition) — keep existing
                merged_condition = existing.condition

            # Update with merged data
            role_map[role_name] = RoleCondition(
                role=role_name,
                tags=merged_tags,
                condition=merged_condition,
                source=merged_source,
            )
        else:
            # New role
            role_map[role_name] = RoleCondition(
                role=role_name,
                tags=tags,
                condition=condition,
                source=source,
            )
            role_disjuncts[role_name] = {norm_cond} if norm_cond else set()

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


def resolve_manifest(
    profile: Optional[str] = None,
    display_manager: Optional[str] = None,
    desktop_environment: Optional[str] = None,
    disable_i3: bool = False,
    disable_hyprland: bool = False,
    disable_gnome: bool = False,
    disable_awesomewm: bool = False,
    disable_kde: bool = False,
    os_family: Optional[str] = None,
    profiles_dir: str = _DEFAULT_PROFILES_DIR,
) -> Manifest:
    """
    Resolve profile configuration into a complete manifest for Ansible.

    This is the single entry point for play.yml pre_tasks, combining profile
    resolution with OS detection into one JSON output.

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
        os_family: OS family ('Archlinux', 'Debian', etc.) - if None, defaults to 'Archlinux'
        profiles_dir: Directory containing profile YAML files

    Returns:
        Manifest with all flags computed for Ansible consumption

    Raises:
        ValueError: If profile name is unknown
    """
    # Resolve profile using existing logic
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

    # Compute is_arch from os_family (default to Archlinux for backward compatibility)
    is_arch = (os_family or 'Archlinux') == 'Archlinux'

    return Manifest(
        profile=resolved.profile,
        display_manager=resolved.display_manager,
        has_display=resolved.has_display,
        is_i3=resolved.is_i3,
        is_hyprland=resolved.is_hyprland,
        is_gnome=resolved.is_gnome,
        is_awesomewm=resolved.is_awesomewm,
        is_kde=resolved.is_kde,
        is_arch=is_arch,
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
# Playbook Generator (Slice 7)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlaybookRole:
    """
    A single role in a playbook with its condition.

    Attributes:
        role: Role name
        condition: Jinja2 when: expression (or None for no condition)
    """
    role: str
    condition: Optional[str]


@dataclass(frozen=True)
class SyncResult:
    """
    Result of comparing a playbook against profile-derived expectations.

    Attributes:
        in_sync: True if playbook matches expected roles exactly
        missing_roles: Roles in generated output but not in playbook
        extra_roles: Roles in playbook but not in generated output
        condition_mismatches: Roles with different conditions (dict with role, actual, expected)
    """
    in_sync: bool
    missing_roles: Tuple[PlaybookRole, ...]
    extra_roles: Tuple[PlaybookRole, ...]
    condition_mismatches: Tuple[Dict[str, Any], ...]


class PlaybookGenerator:
    """
    Generates playbook role sections from profile definitions.

    Produces the expected roles list for a given OS family and host vars,
    with conditions computed from profile/overlay annotations.
    """

    def __init__(
        self,
        profiles_dir: str = _DEFAULT_PROFILES_DIR,
        os_family: str = "Archlinux",
        host_vars: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the generator.

        Args:
            profiles_dir: Directory containing profile YAML files
            os_family: OS family for OS-specific role filtering
            host_vars: Host variables for overlay resolution (e.g. laptop, bluetooth).
                Note: generate() calls resolve_role_manifest with preserve_config_check=True,
                so config_check expressions are kept as raw Jinja2 rather than evaluated.
        """
        self.profiles_dir = profiles_dir
        self.os_family = os_family
        self.host_vars = host_vars or {}

        # Validate profiles_dir at construction time for clear error messages
        profiles_path = Path(self.profiles_dir)
        if not profiles_path.exists():
            raise ValueError(f"Profiles directory does not exist: {profiles_path}")
        if not profiles_path.is_dir():
            raise ValueError(f"Profiles path is not a directory: {profiles_path}")

    def generate(self) -> Tuple[PlaybookRole, ...]:
        """
        Generate the expected playbook role list.

        Resolves all profiles, builds the complete role manifest with
        computed conditions, and returns roles in a deterministic order.

        Returns:
            Tuple of PlaybookRole objects with role names and conditions
        """
        profile_names = list_profiles(self.profiles_dir)

        # DE profiles and their corresponding _is_<de> flags
        de_profiles = {"i3", "hyprland", "gnome", "awesomewm", "kde"}
        profile_to_flag = {
            "i3": "_is_i3",
            "hyprland": "_is_hyprland",
            "gnome": "_is_gnome",
            "awesomewm": "_is_awesomewm",
            "kde": "_is_kde",
        }

        # Track which profiles include each role AND build annotation conditions
        role_to_profiles: Dict[str, set] = {}
        role_map: Dict[str, Optional[str]] = {}

        for profile_name in profile_names:
            manifest = resolve_role_manifest(
                profile=profile_name,
                os_family=self.os_family,
                host_vars=self.host_vars,
                profiles_dir=self.profiles_dir,
                preserve_config_check=True,
            )

            for role_cond in manifest.roles:
                role_name = role_cond.role
                condition = role_cond.condition or None

                # Track profile membership
                role_to_profiles.setdefault(role_name, set()).add(profile_name)

                # Merge conditions across profiles (OR differing ones)
                if role_name not in role_map:
                    role_map[role_name] = condition
                    continue

                existing_condition = role_map[role_name]
                if existing_condition is None or condition is None:
                    role_map[role_name] = None
                elif existing_condition != condition:
                    role_map[role_name] = (
                        f"({existing_condition}) or ({condition})"
                    )

        # Apply profile-gating for roles with empty annotation conditions
        all_profile_set = set(profile_names)
        for role_name, profiles in role_to_profiles.items():
            existing = role_map.get(role_name)
            # Only add profile gate if annotation-based condition is empty
            if existing is not None:
                continue

            # Universal roles (in ALL profiles including headless) need no gate
            if profiles >= all_profile_set:
                continue

            de_members = profiles & de_profiles
            if not de_members:
                continue

            # Determine the profile gate expression
            if de_members == de_profiles:
                gate = "_has_display"
            elif len(de_members) == 1:
                gate = profile_to_flag[next(iter(de_members))]
            else:
                gate = " or ".join(
                    profile_to_flag[p] for p in sorted(de_members)
                )

            role_map[role_name] = gate

        # Convert to PlaybookRole tuple in sorted order for determinism
        return tuple(
            PlaybookRole(role=role, condition=cond)
            for role, cond in sorted(role_map.items())
        )

    def sync_check(self, playbook_path: str) -> SyncResult:
        """
        Compare a playbook against the generated expected roles.

        Parses the existing playbook, extracts roles and conditions,
        and compares them to the generated output.

        Args:
            playbook_path: Path to the playbook YAML file

        Returns:
            SyncResult with in_sync flag and lists of differences
        """
        playbook = Path(playbook_path)
        if not playbook.exists():
            raise ValueError(f"Playbook not found: {playbook_path}")

        # Load actual playbook
        with open(playbook) as f:
            playbook_data = yaml.safe_load(f)

        # Validate playbook_data is usable (empty file yields None)
        if playbook_data is None:
            playbook_data = []

        # Extract roles from playbook (handle list of plays format)
        if isinstance(playbook_data, list):
            plays = playbook_data
        else:
            plays = [playbook_data]

        actual_roles: List[PlaybookRole] = []
        for play in plays:
            if not isinstance(play, dict):
                continue
            if "roles" in play:
                for role_entry in play["roles"]:
                    if isinstance(role_entry, str):
                        actual_roles.append(PlaybookRole(role=role_entry, condition=None))
                    elif isinstance(role_entry, dict):
                        role_name = role_entry.get("role")
                        if not role_name:
                            continue
                        condition = role_entry.get("when")
                        actual_roles.append(PlaybookRole(role=role_name, condition=condition))

        # Get expected roles
        expected_roles = self.generate()

        # Build role maps for comparison
        actual_role_map: Dict[str, Optional[str]] = {
            r.role: r.condition for r in actual_roles
        }
        expected_role_map: Dict[str, Optional[str]] = {
            r.role: r.condition for r in expected_roles
        }

        # Filter out overlay-based roles (dynamic, not in profiles)
        overlay_roles = {
            role for role, cond in actual_role_map.items()
            if cond and "_overlay_" in str(cond)
        }

        actual_roles_filtered = {r for r in actual_role_map if r not in overlay_roles}
        expected_roles_filtered = {r for r in expected_role_map if r not in overlay_roles}

        # Find differences
        missing_role_names = expected_roles_filtered - actual_roles_filtered
        extra_role_names = actual_roles_filtered - expected_roles_filtered
        common_role_names = actual_roles_filtered & expected_roles_filtered

        # Build PlaybookRole tuples for missing and extra
        missing_roles = tuple(
            PlaybookRole(role=name, condition=expected_role_map[name])
            for name in sorted(missing_role_names)
        )
        extra_roles = tuple(
            PlaybookRole(role=name, condition=actual_role_map[name])
            for name in sorted(extra_role_names)
        )

        # Check for condition mismatches
        condition_mismatches = []
        for role_name in sorted(common_role_names):
            actual_cond = actual_role_map[role_name]
            expected_cond = expected_role_map[role_name]

            actual_normalized = _normalize_condition(actual_cond)
            expected_normalized = _normalize_condition(expected_cond)

            if actual_normalized != expected_normalized:
                condition_mismatches.append({
                    "role": role_name,
                    "actual": actual_cond,
                    "expected": expected_cond,
                })

        # Check if in sync
        in_sync = (
            not missing_roles and
            not extra_roles and
            not condition_mismatches
        )

        return SyncResult(
            in_sync=in_sync,
            missing_roles=missing_roles,
            extra_roles=extra_roles,
            condition_mismatches=tuple(condition_mismatches),
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


def _cmd_resolve_manifest(args: argparse.Namespace) -> int:
    """Output Manifest as JSON to stdout; exit 1 on error."""
    try:
        result = resolve_manifest(
            profile=args.profile,
            display_manager=args.display_manager,
            desktop_environment=args.desktop_environment,
            disable_i3=args.disable_i3,
            disable_hyprland=args.disable_hyprland,
            disable_gnome=args.disable_gnome,
            disable_awesomewm=args.disable_awesomewm,
            disable_kde=args.disable_kde,
            os_family=args.os_family,
            profiles_dir=args.profiles_dir,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(asdict(result)))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate all profiles and overlays; write errors to stderr; exit 1 on any failure."""
    # Validate profiles
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
                print(f"profile {name}: {error}", file=sys.stderr)

    # Validate overlays
    overlay_results = validate_overlays(profiles_dir=args.profiles_dir)
    for overlay_name, errors in overlay_results:
        if errors:
            any_invalid = True
            for error in errors:
                print(f"overlay {overlay_name}: {error}", file=sys.stderr)

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

    # Also list overlays in pretty format
    overlay_names = _discover_overlay_names(args.profiles_dir)
    if overlay_names:
        print()
        print("Available overlays:")
        for name in overlay_names:
            try:
                overlay = load_overlay(args.profiles_dir, name)
            except (ValueError, yaml.YAMLError, OSError):
                continue
            description = str(overlay.description).splitlines()[0] if overlay.description else ""
            print(f"  {name}: {description}")

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


def _cmd_resolve_overlays(args: argparse.Namespace) -> int:
    """Resolve overlays and output JSON with overlays list and flat facts dict; exit 1 on error."""
    try:
        facts = json.loads(args.facts_json) if args.facts_json else {}
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in --facts-json: {exc}", file=sys.stderr)
        return 1

    if not isinstance(facts, dict):
        print(
            "Invalid --facts-json: top-level JSON value must be an object (mapping).",
            file=sys.stderr,
        )
        return 1

    try:
        resolved_list = resolve_overlays(
            facts=facts,
            has_display=args.has_display,
            is_arch=args.is_arch,
            profiles_dir=args.profiles_dir,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Convert ResolvedOverlay objects to dict format
    overlays_output = []
    flat_facts = {}

    for resolved in resolved_list:
        overlay_dict = {
            "name": resolved.overlay.name,
            "description": resolved.overlay.description,
            "applies": resolved.applies,
            "roles": []
        }

        for role_entry, applies in resolved.resolved_roles:
            role_dict = {
                "role": role_entry.role,
                "tags": list(role_entry.tags),
                "applies": applies,
                "os": role_entry.os,
                "requires_display": role_entry.requires_display,
            }
            overlay_dict["roles"].append(role_dict)

            # Add to flat facts with _overlay_ prefix
            fact_key = f"_overlay_{role_entry.role}"
            flat_facts[fact_key] = applies

        overlays_output.append(overlay_dict)

    output = {
        "overlays": overlays_output,
        "facts": flat_facts,
    }

    print(json.dumps(output, indent=2))
    return 0


def _cmd_resolve_role_manifest(args: argparse.Namespace) -> int:
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

        result = resolve_role_manifest(
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
            evaluator=Jinja2Evaluator(),
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



def _cmd_sync_playbook(args: argparse.Namespace) -> int:
    """
    Compare actual play.yml roles with profile-derived expected roles.

    Uses PlaybookGenerator.sync_check() to compare the playbook against
    all profile definitions. Outputs a human-readable diff on drift.

    Exits 1 on drift in --check mode; otherwise outputs diff to stdout.
    """
    try:
        generator = PlaybookGenerator(
            profiles_dir=args.profiles_dir,
            os_family="Archlinux",
            host_vars={},
        )
        result = generator.sync_check(args.playbook)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.in_sync:
        print("play.yml is in sync with profile definitions")
        return 0

    # Output the diff
    print("play.yml is out of sync with profile definitions:\n")

    if result.missing_roles:
        print("Missing roles (in profiles but not in play.yml):")
        for role in result.missing_roles:
            if role.condition:
                print(f"  - {role.role} (when: {role.condition})")
            else:
                print(f"  - {role.role}")
        print()

    if result.extra_roles:
        print("Extra roles (in play.yml but not in any profile):")
        for role in result.extra_roles:
            if role.condition:
                print(f"  - {role.role} (when: {role.condition})")
            else:
                print(f"  - {role.role}")
        print()

    if result.condition_mismatches:
        print("Condition mismatches:")
        for mismatch in result.condition_mismatches:
            print(f"  - {mismatch['role']}:")
            print(f"      actual:   {mismatch['actual']}")
            print(f"      expected: {mismatch['expected']}")
        print()

    if args.check:
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

    # --- resolve-manifest ---
    p_manifest = subparsers.add_parser(
        "resolve-manifest",
        help="Resolve profile to manifest JSON for Ansible (includes OS detection).",
    )
    p_manifest.add_argument("--profile", default=None, help="Profile name (e.g. i3, headless)")
    p_manifest.add_argument("--display-manager", dest="display_manager", default=None)
    p_manifest.add_argument("--desktop-environment", dest="desktop_environment", default=None)
    p_manifest.add_argument("--disable-i3", dest="disable_i3", action="store_true")
    p_manifest.add_argument("--disable-hyprland", dest="disable_hyprland", action="store_true")
    p_manifest.add_argument("--disable-gnome", dest="disable_gnome", action="store_true")
    p_manifest.add_argument("--disable-awesomewm", dest="disable_awesomewm", action="store_true")
    p_manifest.add_argument("--disable-kde", dest="disable_kde", action="store_true")
    p_manifest.add_argument("--os-family", dest="os_family", default=None,
                          help="OS family (e.g. Archlinux, Debian)")
    p_manifest.add_argument(
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

    # --- resolve-overlays ---
    p_resolve_overlays = subparsers.add_parser(
        "resolve-overlays",
        help="Resolve overlays against host facts and output JSON.",
    )
    p_resolve_overlays.add_argument(
        "--facts-json",
        default="{}",
        help='JSON string of host facts (e.g., \'{"laptop": true}\')',
    )
    p_resolve_overlays.add_argument(
        "--has-display",
        action="store_true",
        default=True,
        help="Whether this machine has a display server (default: True)",
    )
    p_resolve_overlays.add_argument(
        "--no-has-display",
        dest="has_display",
        action="store_false",
        help="This machine does not have a display server",
    )
    p_resolve_overlays.add_argument(
        "--is-arch",
        action="store_true",
        default=True,
        help="Whether this is an Arch Linux system (default: True)",
    )
    p_resolve_overlays.add_argument(
        "--no-is-arch",
        dest="is_arch",
        action="store_false",
        help="This is not an Arch Linux system (e.g., Debian)",
    )
    p_resolve_overlays.add_argument(
        "--profiles-dir", dest="profiles_dir", default=_DEFAULT_PROFILES_DIR
    )

    # --- resolve-role-manifest ---
    p_manifest = subparsers.add_parser(
        "resolve-role-manifest",
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

    # --- sync-playbook ---
    p_sync = subparsers.add_parser(
        "sync-playbook",
        help="Compare play.yml roles with profile-derived expected roles.",
    )
    p_sync.add_argument(
        "--playbook",
        default=str(Path(__file__).parent.parent / "play.yml"),
        help="Path to play.yml file",
    )
    p_sync.add_argument(
        "--check",
        action="store_true",
        help="CI mode: exit 1 on drift, no output changes",
    )
    p_sync.add_argument(
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
        "resolve-manifest": _cmd_resolve_manifest,
        "resolve-role-manifest": _cmd_resolve_role_manifest,
        "resolve-overlays": _cmd_resolve_overlays,
        "sync-playbook": _cmd_sync_playbook,
        "validate": _cmd_validate,
        "list-profiles": _cmd_list_profiles,
        "make-args": _cmd_make_args,
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
