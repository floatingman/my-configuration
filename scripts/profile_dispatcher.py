#!/usr/bin/env python3
"""
Profile Dispatcher - Core Resolver

Pure function for resolving Ansible profile configuration into boolean flags.
Supports both profile mode (profile name) and manual mode (explicit variables).

This is a standalone Python module with no Ansible dependency,
making the dispatch logic unit-testable.
"""

from dataclasses import dataclass
from typing import Optional


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


def resolve(
    profile: Optional[str] = None,
    display_manager: Optional[str] = None,
    desktop_environment: Optional[str] = None,
    disable_i3: bool = False,
    disable_hyprland: bool = False,
    disable_gnome: bool = False,
    disable_awesomewm: bool = False,
    disable_kde: bool = False,
    profiles_dir: str = "profiles",
) -> ResolvedProfile:
    """
    Resolve profile configuration into boolean flags.

    Args:
        profile: Profile name ('headless', 'i3', 'hyprland', 'gnome', 'awesomewm', 'kde')
                or None for manual mode
        display_manager: Display manager name ('gdm', 'lightdm') or None
        desktop_environment: Desktop environment name or None
        disable_i3: Suppress i3 in manual mode
        disable_hyprland: Suppress Hyprland in manual mode
        disable_gnome: Suppress GNOME in manual mode
        disable_awesomewm: Suppress AwesomeWM in manual mode
        disable_kde: Suppress KDE in manual mode
        profiles_dir: Directory containing profile YAML files (default: "profiles").
            Reserved for future profile YAML-based profile discovery; not yet implemented.

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
        valid_profiles = {'headless', 'i3', 'hyprland', 'gnome', 'awesomewm', 'kde'}
        if normalized not in valid_profiles:
            raise ValueError(
                f"Unknown profile '{normalized}'. "
                f"Available profiles: {', '.join(sorted(valid_profiles))}"
            )

    # Profile mode: use predefined profile settings
    # Use profile mode when effective_profile is a real profile (not 'manual')
    if effective_profile != 'manual':
        return _resolve_profile_mode(effective_profile)

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


def _resolve_profile_mode(profile: str) -> ResolvedProfile:
    """
    Resolve in profile mode - all settings come from the profile definition.
    """
    # Headless profile - no display at all
    if profile == 'headless':
        return ResolvedProfile(
            profile='headless',
            display_manager=None,
            has_display=False,
            desktop_environment=None,
            is_i3=False,
            is_hyprland=False,
            is_gnome=False,
            is_awesomewm=False,
            is_kde=False
        )

    # GNOME profile - uses GDM
    if profile == 'gnome':
        return ResolvedProfile(
            profile='gnome',
            display_manager='gdm',
            has_display=True,
            desktop_environment='gnome',
            is_i3=False,
            is_hyprland=False,
            is_gnome=True,
            is_awesomewm=False,
            is_kde=False
        )

    # KDE profile - uses lightdm (can also use sddm)
    if profile == 'kde':
        return ResolvedProfile(
            profile='kde',
            display_manager='lightdm',
            has_display=True,
            desktop_environment='kde',
            is_i3=False,
            is_hyprland=False,
            is_gnome=False,
            is_awesomewm=False,
            is_kde=True
        )

    # AwesomeWM profile - uses lightdm
    if profile == 'awesomewm':
        return ResolvedProfile(
            profile='awesomewm',
            display_manager='lightdm',
            has_display=True,
            desktop_environment='awesomewm',
            is_i3=False,
            is_hyprland=False,
            is_gnome=False,
            is_awesomewm=True,
            is_kde=False
        )

    # i3 profile - uses lightdm
    if profile == 'i3':
        return ResolvedProfile(
            profile='i3',
            display_manager='lightdm',
            has_display=True,
            desktop_environment='i3',
            is_i3=True,
            is_hyprland=False,
            is_gnome=False,
            is_awesomewm=False,
            is_kde=False
        )

    # Hyprland profile - uses lightdm
    if profile == 'hyprland':
        return ResolvedProfile(
            profile='hyprland',
            display_manager='lightdm',
            has_display=True,
            desktop_environment='hyprland',
            is_i3=False,
            is_hyprland=True,
            is_gnome=False,
            is_awesomewm=False,
            is_kde=False
        )

    # Should never reach here due to validation in resolve()
    raise ValueError(f"Unhandled profile: {profile}")


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

    # If desktop_environment is explicitly set, use it
    # Otherwise None (enables dual-desktop for i3+hyprland)
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
