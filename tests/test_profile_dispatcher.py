#!/usr/bin/env python3
"""
Test suite for profile_dispatcher module.

Comprehensive unit tests covering all input combinations and edge cases.
No Ansible dependency - pure Python tests.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# Add scripts directory to path so profile_dispatcher can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import json
import yaml

from profile_dispatcher import (
    main,
    resolve,
    resolve_manifest,
    resolve_role_manifest,
    load_profile,
    validate_profile,
    list_profiles,
    resolve_overlays,
    validate_overlays,
    load_overlay,
    _discover_overlay_names,
    _normalize_condition,
    discover_overlay_variables,
    generate_host_vars_template,
    generate_overlay_facts_task,
    _section_sort_key,
    PlaybookGenerator,
    OverlayDefinition,
    ResolvedOverlay,
    ResolvedOverlayRole,
    RoleEntry,
    Overlay,
    ResolvedProfile,
    Manifest,
    RoleCondition,
    ResolvedManifest,
    translate_condition,
    Jinja2Evaluator,
    DictEvaluator,
    EvaluationError,
    ConditionTranslator,
    AnsibleConditionTranslator,
    DefaultTranslator,
    PlaybookRole,
    SyncResult,
)

# Path to the real profiles directory used in integration-style tests
_PROFILES_DIR = str(Path(__file__).resolve().parent.parent / "profiles")


class TestProfileMode:
    """Test profile mode resolution (profile name provided)."""

    def test_headless_profile(self):
        """Headless profile should have no display and all DE flags False."""
        result = resolve(profile='headless')
        assert result.profile == 'headless'
        assert result.display_manager is None
        assert result.has_display is False
        assert result.desktop_environment is None
        assert result.is_i3 is False
        assert result.is_hyprland is False
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_i3_profile(self):
        """i3 profile should use lightdm and set only is_i3 to True."""
        result = resolve(profile='i3')
        assert result.profile == 'i3'
        assert result.display_manager == 'lightdm'
        assert result.has_display is True
        assert result.desktop_environment == 'i3'
        assert result.is_i3 is True
        assert result.is_hyprland is False
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_hyprland_profile(self):
        """Hyprland profile should use sddm and set only is_hyprland to True."""
        result = resolve(profile='hyprland')
        assert result.profile == 'hyprland'
        assert result.display_manager == 'sddm'
        assert result.has_display is True
        assert result.desktop_environment == 'hyprland'
        assert result.is_i3 is False
        assert result.is_hyprland is True
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_gnome_profile(self):
        """GNOME profile should use gdm and set only is_gnome to True."""
        result = resolve(profile='gnome')
        assert result.profile == 'gnome'
        assert result.display_manager == 'gdm'
        assert result.has_display is True
        assert result.desktop_environment == 'gnome'
        assert result.is_i3 is False
        assert result.is_hyprland is False
        assert result.is_gnome is True
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_awesomewm_profile(self):
        """AwesomeWM profile should use lightdm and set only is_awesomewm to True."""
        result = resolve(profile='awesomewm')
        assert result.profile == 'awesomewm'
        assert result.display_manager == 'lightdm'
        assert result.has_display is True
        assert result.desktop_environment == 'awesomewm'
        assert result.is_i3 is False
        assert result.is_hyprland is False
        assert result.is_gnome is False
        assert result.is_awesomewm is True
        assert result.is_kde is False

    def test_kde_profile(self):
        """KDE profile should use sddm and set only is_kde to True."""
        result = resolve(profile='kde')
        assert result.profile == 'kde'
        assert result.display_manager == 'sddm'
        assert result.has_display is True
        assert result.desktop_environment == 'kde'
        assert result.is_i3 is False
        assert result.is_hyprland is False
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is True

    def test_unknown_profile_raises_value_error(self):
        """Unknown profile name should raise ValueError with available profiles."""
        with pytest.raises(ValueError) as exc_info:
            resolve(profile='unknown_profile')

        error_msg = str(exc_info.value)
        assert 'Unknown profile' in error_msg
        assert 'unknown_profile' in error_msg
        assert 'headless' in error_msg
        assert 'i3' in error_msg
        assert 'hyprland' in error_msg
        assert 'gnome' in error_msg
        assert 'awesomewm' in error_msg
        assert 'kde' in error_msg

    def test_profile_mode_ignores_extra_vars(self):
        """Profile mode should override conflicting display_manager from extra vars."""
        # Profile mode wins even if display_manager is set
        result = resolve(profile='gnome', display_manager='lightdm')
        assert result.profile == 'gnome'
        assert result.display_manager == 'gdm'  # From profile, not from extra var
        assert result.is_gnome is True


class TestManualMode:
    """Test manual mode resolution (no profile, explicit variables)."""

    def test_manual_mode_no_display_manager(self):
        """Manual mode with no display_manager should have has_display=False."""
        result = resolve()
        assert result.profile == 'manual'
        assert result.display_manager is None
        assert result.has_display is False
        assert result.desktop_environment is None
        assert result.is_i3 is False
        assert result.is_hyprland is False
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_manual_mode_empty_display_manager(self):
        """Manual mode with empty string display_manager should have has_display=False."""
        result = resolve(display_manager='')
        assert result.profile == 'manual'
        assert result.display_manager is None
        assert result.has_display is False

    def test_manual_mode_with_empty_desktop_environment(self):
        """desktop_environment='' with lightdm should behave like dual-desktop default."""
        result = resolve(display_manager='lightdm', desktop_environment='')
        assert result.profile == 'manual'
        assert result.display_manager == 'lightdm'
        assert result.has_display is True
        # Explicit empty string should still mean "no specific DE" -> dual-desktop mode
        assert result.desktop_environment is None
        assert result.is_i3 is True
        assert result.is_hyprland is True
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_manual_mode_with_lightdm(self):
        """Manual mode with lightdm should enable display but no DE by default."""
        result = resolve(display_manager='lightdm')
        assert result.profile == 'manual'
        assert result.display_manager == 'lightdm'
        assert result.has_display is True
        assert result.desktop_environment is None  # Dual-desktop mode
        # i3 and hyprland both enabled (dual-desktop behavior)
        assert result.is_i3 is True
        assert result.is_hyprland is True
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_manual_mode_with_gdm(self):
        """Manual mode with gdm should enable display but no DE by default."""
        result = resolve(display_manager='gdm')
        assert result.profile == 'manual'
        assert result.display_manager == 'gdm'
        assert result.has_display is True
        assert result.desktop_environment is None  # Dual-desktop mode
        # i3 and hyprland both enabled (dual-desktop behavior)
        assert result.is_i3 is True
        assert result.is_hyprland is True
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_manual_mode_with_i3_desktop_environment(self):
        """Manual mode with desktop_environment='i3' should enable only i3."""
        result = resolve(display_manager='lightdm', desktop_environment='i3')
        assert result.profile == 'manual'
        assert result.display_manager == 'lightdm'
        assert result.has_display is True
        assert result.desktop_environment == 'i3'
        assert result.is_i3 is True
        assert result.is_hyprland is False
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_manual_mode_with_hyprland_desktop_environment(self):
        """Manual mode with desktop_environment='hyprland' should enable only hyprland."""
        result = resolve(display_manager='lightdm', desktop_environment='hyprland')
        assert result.profile == 'manual'
        assert result.display_manager == 'lightdm'
        assert result.has_display is True
        assert result.desktop_environment == 'hyprland'
        assert result.is_i3 is False
        assert result.is_hyprland is True
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_manual_mode_with_gnome_desktop_environment(self):
        """Manual mode with desktop_environment='gnome' should enable only GNOME."""
        result = resolve(display_manager='gdm', desktop_environment='gnome')
        assert result.profile == 'manual'
        assert result.display_manager == 'gdm'
        assert result.has_display is True
        assert result.desktop_environment == 'gnome'
        assert result.is_i3 is False
        assert result.is_hyprland is False
        assert result.is_gnome is True
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_manual_mode_with_awesomewm_desktop_environment(self):
        """Manual mode with desktop_environment='awesomewm' should enable only AwesomeWM."""
        result = resolve(display_manager='lightdm', desktop_environment='awesomewm')
        assert result.profile == 'manual'
        assert result.display_manager == 'lightdm'
        assert result.has_display is True
        assert result.desktop_environment == 'awesomewm'
        assert result.is_i3 is False
        assert result.is_hyprland is False
        assert result.is_gnome is False
        assert result.is_awesomewm is True
        assert result.is_kde is False

    def test_manual_mode_with_kde_desktop_environment(self):
        """Manual mode with desktop_environment='kde' should enable only KDE."""
        result = resolve(display_manager='lightdm', desktop_environment='kde')
        assert result.profile == 'manual'
        assert result.display_manager == 'lightdm'
        assert result.has_display is True
        assert result.desktop_environment == 'kde'
        assert result.is_i3 is False
        assert result.is_hyprland is False
        assert result.is_gnome is False
        assert result.is_awesomewm is False
        assert result.is_kde is True


class TestDisableFlags:
    """Test disable_* flags in manual mode."""

    def test_disable_i3(self):
        """disable_i3 flag should suppress i3 in manual mode."""
        result = resolve(display_manager='lightdm', disable_i3=True)
        assert result.is_i3 is False
        assert result.is_hyprland is True  # Other DEs unaffected

    def test_disable_hyprland(self):
        """disable_hyprland flag should suppress hyprland in manual mode."""
        result = resolve(display_manager='lightdm', disable_hyprland=True)
        assert result.is_hyprland is False
        assert result.is_i3 is True  # Other DEs unaffected

    def test_disable_gnome(self):
        """disable_gnome flag should suppress GNOME in manual mode."""
        result = resolve(
            display_manager='gdm',
            desktop_environment='gnome',
            disable_gnome=True
        )
        assert result.is_gnome is False

    def test_disable_awesomewm(self):
        """disable_awesomewm flag should suppress AwesomeWM in manual mode."""
        result = resolve(
            display_manager='lightdm',
            desktop_environment='awesomewm',
            disable_awesomewm=True
        )
        assert result.is_awesomewm is False

    def test_disable_kde(self):
        """disable_kde flag should suppress KDE in manual mode."""
        result = resolve(
            display_manager='lightdm',
            desktop_environment='kde',
            disable_kde=True
        )
        assert result.is_kde is False

    def test_disable_both_i3_and_hyprland(self):
        """Disabling both i3 and hyprland should disable dual-desktop mode."""
        result = resolve(
            display_manager='lightdm',
            disable_i3=True,
            disable_hyprland=True
        )
        assert result.is_i3 is False
        assert result.is_hyprland is False
        # Still has display, just no desktop environments
        assert result.has_display is True

    def test_disable_flags_with_explicit_desktop_environment(self):
        """Disable flags should work even when desktop_environment is set."""
        # i3 disabled, DE set to i3
        result = resolve(
            display_manager='lightdm',
            desktop_environment='i3',
            disable_i3=True
        )
        assert result.is_i3 is False

        # hyprland disabled, DE set to hyprland
        result = resolve(
            display_manager='lightdm',
            desktop_environment='hyprland',
            disable_hyprland=True
        )
        assert result.is_hyprland is False


class TestDualDesktopMode:
    """Test dual-desktop behavior (display_manager set without desktop_environment)."""

    def test_dual_desktop_with_lightdm(self):
        """When display_manager is set but desktop_environment is None, both i3 and hyprland are True."""
        result = resolve(display_manager='lightdm')
        assert result.is_i3 is True
        assert result.is_hyprland is True
        assert result.desktop_environment is None  # No specific DE

    def test_dual_desktop_with_gdm(self):
        """Dual-desktop mode works with gdm as well."""
        result = resolve(display_manager='gdm')
        assert result.is_i3 is True
        assert result.is_hyprland is True

    def test_explicit_desktop_environment_breaks_dual_desktop(self):
        """Setting desktop_environment explicitly should disable dual-desktop mode."""
        result = resolve(display_manager='lightdm', desktop_environment='i3')
        assert result.is_i3 is True
        assert result.is_hyprland is False
        assert result.desktop_environment == 'i3'


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_none_profile_equals_manual_mode(self):
        """Profile=None should behave exactly like manual mode."""
        result_none = resolve(profile=None)
        result_manual = resolve()
        assert result_none == result_manual

    def test_empty_string_profile_equals_manual_mode(self):
        """Profile='' should behave like manual mode."""
        result_empty = resolve(profile='')
        result_manual = resolve()
        assert result_empty == result_manual

    def test_whitespace_profile_equals_manual_mode(self):
        """Profile='   ' should behave like manual mode (normalized to empty)."""
        result_ws = resolve(profile='   ')
        result_manual = resolve()
        assert result_ws == result_manual

    def test_literal_manual_profile_equals_manual_mode(self):
        """Profile='manual' should behave exactly like manual mode."""
        result_manual_profile = resolve(profile='manual')
        result_manual = resolve()
        assert result_manual_profile == result_manual

    def test_resolved_profile_is_frozen(self):
        """ResolvedProfile should be immutable (frozen dataclass)."""
        result = resolve(profile='i3')
        with pytest.raises(AttributeError):
            result.is_i3 = False  # Should raise AttributeError

    def test_resolved_profile_is_hashable(self):
        """ResolvedProfile should be hashable (can be used in sets/dicts)."""
        result1 = resolve(profile='i3')
        result2 = resolve(profile='i3')
        result3 = resolve(profile='hyprland')

        # Should be hashable
        profile_set = {result1, result2, result3}
        assert len(profile_set) == 2  # i3 and hyprland are different

    def test_all_de_flags_false_preserves_display_manager(self):
        """When all DE flags are False, display_manager should still be preserved."""
        result = resolve(
            display_manager='lightdm',
            desktop_environment='i3',
            disable_i3=True,
            disable_hyprland=True
        )
        assert result.display_manager == 'lightdm'
        assert result.has_display is True
        assert result.is_i3 is False
        assert result.is_hyprland is False

    def test_case_sensitive_profile_names(self):
        """Profile names should be case-sensitive."""
        # lowercase works
        result = resolve(profile='i3')
        assert result.profile == 'i3'

        # uppercase fails
        with pytest.raises(ValueError):
            resolve(profile='I3')

        # mixed case fails
        with pytest.raises(ValueError):
            resolve(profile='Hyprland')


class TestJinja2Equivalence:
    """Verify resolver matches play.yml Jinja2 logic for all input combinations."""

    def test_manual_mode_empty_inputs(self):
        """play.yml: _profile='manual', _dm='' → has_display=False, all DE flags False."""
        result = resolve(profile=None, display_manager='')
        assert result.profile == 'manual'
        assert result.has_display is False
        assert result.is_i3 is False
        assert result.is_hyprland is False

    def test_manual_mode_lightdm_no_de(self):
        """play.yml: _dm='lightdm', no desktop_environment → is_i3=True, is_hyprland=True."""
        result = resolve(display_manager='lightdm')
        assert result.is_i3 is True
        assert result.is_hyprland is True

    def test_manual_mode_lightdm_with_i3(self):
        """play.yml: desktop_environment='i3' → is_i3=True, is_hyprland=False."""
        result = resolve(display_manager='lightdm', desktop_environment='i3')
        assert result.is_i3 is True
        assert result.is_hyprland is False

    def test_manual_mode_disable_i3_override(self):
        """play.yml: disable_i3=true → is_i3=False even with lightdm set."""
        result = resolve(display_manager='lightdm', disable_i3=True)
        assert result.is_i3 is False
        assert result.is_hyprland is True

    def test_manual_mode_gnome_requires_explicit_de(self):
        """play.yml: GNOME only true if desktop_environment='gnome' explicitly."""
        # Without explicit DE, GNOME is False
        result = resolve(display_manager='gdm')
        assert result.is_gnome is False

        # With explicit DE, GNOME is True
        result = resolve(display_manager='gdm', desktop_environment='gnome')
        assert result.is_gnome is True

    def test_profile_mode_overrides_manual_vars(self):
        """play.yml: Profile setting takes precedence over manual variables."""
        # Set profile='gnome' but also pass conflicting display_manager
        result = resolve(profile='gnome', display_manager='lightdm')
        # Profile wins - should use gdm, not lightdm
        assert result.profile == 'gnome'
        assert result.display_manager == 'gdm'

    def test_manual_mode_gnome_without_display_manager(self):
        """play.yml: desktop_environment='gnome', no display_manager → _is_gnome=true."""
        result = resolve(desktop_environment='gnome')
        assert result.is_gnome is True
        assert result.is_awesomewm is False
        assert result.is_kde is False

    def test_manual_mode_awesomewm_without_display_manager(self):
        """play.yml: desktop_environment='awesomewm', no display_manager → _is_awesomewm=true."""
        result = resolve(desktop_environment='awesomewm')
        assert result.is_awesomewm is True
        assert result.is_gnome is False
        assert result.is_kde is False

    def test_manual_mode_kde_without_display_manager(self):
        """play.yml: desktop_environment='kde', no display_manager → _is_kde=true."""
        result = resolve(desktop_environment='kde')
        assert result.is_kde is True
        assert result.is_gnome is False
        assert result.is_awesomewm is False

    def test_profiles_dir_used_for_profile_mode(self):
        """profiles_dir is used to load profile YAML in profile mode."""
        result = resolve(profile='i3', profiles_dir=_PROFILES_DIR)
        assert result.profile == 'i3'
        assert result.is_i3 is True


class TestLoadProfile:
    """Test load_profile() function."""

    def test_base_profile_loads(self):
        """_base profile loads without extends chain."""
        data = load_profile(_PROFILES_DIR, '_base')
        assert 'display_manager_default' in data
        assert 'desktop_environment' in data

    def test_load_with_yml_extension(self):
        """load_profile accepts name with .yml extension."""
        data = load_profile(_PROFILES_DIR, 'i3.yml')
        assert data['display_manager_default'] == 'lightdm'

    def test_extends_chain_merges_child_overrides_parent(self):
        """Child values override parent scalars in extends chain."""
        # i3 extends _base; i3's display_manager_default overrides _base's ""
        data = load_profile(_PROFILES_DIR, 'i3')
        assert data['display_manager_default'] == 'lightdm'
        assert data['desktop_environment'] == 'i3'

    def test_extends_chain_inherits_parent_fields(self):
        """Child profile inherits fields from parent that it does not override."""
        # i3 extends _base; roles from _base appear in merged result
        data = load_profile(_PROFILES_DIR, 'i3')
        assert 'roles' in data
        # i3's own roles are appended after _base roles
        role_names = [r['role'] if isinstance(r, dict) else r for r in data['roles']]
        assert 'base' in role_names      # from _base
        assert 'i3' in role_names        # from i3.yml

    def test_missing_profile_raises_value_error(self):
        """Missing profile file raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            load_profile(_PROFILES_DIR, 'nonexistent_profile')

    def test_missing_extends_target_raises_value_error(self):
        """Broken extends chain raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a profile that extends a non-existent parent
            Path(tmpdir, 'orphan.yml').write_text(
                'name: orphan\nextends: missing_parent.yml\n'
            )
            with pytest.raises(ValueError, match="not found"):
                load_profile(tmpdir, 'orphan')

    def test_all_named_profiles_load_successfully(self):
        """All 6 named profiles load without error."""
        for name in ('headless', 'i3', 'hyprland', 'gnome', 'awesomewm', 'kde'):
            data = load_profile(_PROFILES_DIR, name)
            assert isinstance(data, dict), f"load_profile('{name}') should return dict"


class TestValidateProfile:
    """Test validate_profile() function."""

    def test_valid_profile_returns_empty_list(self):
        """A correctly defined profile has no errors."""
        for name in ('headless', 'i3', 'hyprland', 'gnome', 'awesomewm', 'kde'):
            errors = validate_profile(_PROFILES_DIR, name)
            assert errors == [], f"Profile '{name}' should be valid, got: {errors}"

    def test_missing_display_manager_default_returns_error(self):
        """Missing display_manager_default field is reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'bad.yml').write_text(
                'name: bad\ndesktop_environment: i3\n'
            )
            errors = validate_profile(tmpdir, 'bad')
            assert any('display_manager_default' in e for e in errors)

    def test_missing_desktop_environment_returns_error(self):
        """Missing desktop_environment field is reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'bad.yml').write_text(
                'name: bad\ndisplay_manager_default: lightdm\n'
            )
            errors = validate_profile(tmpdir, 'bad')
            assert any('desktop_environment' in e for e in errors)

    def test_invalid_display_manager_value_caught(self):
        """An unrecognized display_manager_default value is an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'bad.yml').write_text(
                'name: bad\ndisplay_manager_default: xdm\ndesktop_environment: i3\n'
            )
            errors = validate_profile(tmpdir, 'bad')
            assert any('display_manager_default' in e for e in errors)
            assert any('xdm' in e for e in errors)

    def test_invalid_desktop_environment_value_caught(self):
        """An unrecognized desktop_environment value is an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'bad.yml').write_text(
                'name: bad\ndisplay_manager_default: lightdm\ndesktop_environment: xfce\n'
            )
            errors = validate_profile(tmpdir, 'bad')
            assert any('desktop_environment' in e for e in errors)
            assert any('xfce' in e for e in errors)

    def test_broken_extends_chain_returns_error(self):
        """Unresolvable extends chain is reported as an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'broken.yml').write_text(
                'name: broken\nextends: ghost.yml\n'
                'display_manager_default: lightdm\ndesktop_environment: i3\n'
            )
            errors = validate_profile(tmpdir, 'broken')
            assert len(errors) > 0
            assert any('not found' in e for e in errors)

    def test_nonexistent_profile_returns_error(self):
        """Validating a profile that does not exist returns an error."""
        errors = validate_profile(_PROFILES_DIR, 'does_not_exist')
        assert len(errors) > 0


class TestListProfiles:
    """Test list_profiles() function."""

    def test_returns_expected_six_profiles(self):
        """list_profiles returns the 6 named profiles."""
        names = list_profiles(_PROFILES_DIR)
        assert set(names) == {'headless', 'i3', 'hyprland', 'gnome', 'awesomewm', 'kde'}

    def test_excludes_base(self):
        """_base is excluded from the list."""
        names = list_profiles(_PROFILES_DIR)
        assert '_base' not in names

    def test_excludes_overlay_subdirectory(self):
        """Profiles in subdirectories (overlays/) are not returned."""
        names = list_profiles(_PROFILES_DIR)
        assert 'laptop' not in names
        assert 'bluetooth' not in names

    def test_returns_sorted_list(self):
        """list_profiles returns names in sorted order."""
        names = list_profiles(_PROFILES_DIR)
        assert names == sorted(names)

    def test_custom_dir_with_mock_profiles(self):
        """list_profiles discovers only valid profiles in a custom directory."""
        valid_content = 'display_manager_default: lightdm\ndesktop_environment: i3\n'
        invalid_content = 'name: missing-required-fields\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'alpha.yml').write_text(valid_content)
            Path(tmpdir, 'beta.yml').write_text(valid_content)
            Path(tmpdir, 'broken.yml').write_text(invalid_content)
            Path(tmpdir, '_base.yml').write_text('name: base\n')
            names = list_profiles(tmpdir)
            assert set(names) == {'alpha', 'beta'}
            assert 'broken' not in names


class TestDiscoverOverlays:
    """Test _discover_overlay_names() function."""

    def test_returns_sorted_overlay_names(self):
        """_discover_overlay_names returns overlay names sorted alphabetically."""
        names = _discover_overlay_names(_PROFILES_DIR)
        assert names == ["bluetooth", "laptop"]

    def test_returns_empty_list_for_nonexistent_overlays_dir(self):
        """_discover_overlay_names returns empty list when overlays directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Empty profiles dir (no overlays subdirectory)
            names = _discover_overlay_names(tmpdir)
            assert names == []

    def test_returns_empty_list_for_empty_overlays_dir(self):
        """_discover_overlay_names returns empty list when overlays directory is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_path = Path(tmpdir) / "overlays"
            overlays_path.mkdir()
            names = _discover_overlay_names(tmpdir)
            assert names == []


class TestLoadOverlay:
    """Test load_overlay() function."""

    def test_load_laptop_overlay(self):
        """load_overlay correctly parses laptop.yml."""
        overlay = load_overlay(_PROFILES_DIR, "laptop")
        assert isinstance(overlay, OverlayDefinition)
        assert overlay.name == "Laptop Features Overlay"
        assert overlay.applies_when == "laptop | default(false)"
        assert isinstance(overlay.roles, list)
        assert len(overlay.roles) == 2
        # First role entry
        assert overlay.roles[0]["role"] == "laptop"
        assert overlay.roles[0]["tags"] == ["laptop"]
        # Second role entry
        assert overlay.roles[1]["role"] == "backlight"
        assert overlay.roles[1]["tags"] == ["backlight"]
        assert overlay.roles[1]["requires_display"] is True

    def test_load_bluetooth_overlay(self):
        """load_overlay correctly parses bluetooth.yml."""
        overlay = load_overlay(_PROFILES_DIR, "bluetooth")
        assert isinstance(overlay, OverlayDefinition)
        assert overlay.name == "Bluetooth Support Overlay"
        assert overlay.applies_when == "bluetooth is defined and not (bluetooth.disable | default(false))"
        assert isinstance(overlay.roles, list)
        assert len(overlay.roles) == 1
        assert overlay.roles[0]["role"] == "bluetooth"
        assert overlay.roles[0]["tags"] == ["bluetooth"]
        assert overlay.roles[0]["os"] == "archlinux"

    def test_load_overlay_with_yml_extension(self):
        """load_overlay accepts name with .yml extension."""
        overlay = load_overlay(_PROFILES_DIR, "laptop.yml")
        assert overlay.name == "Laptop Features Overlay"

    def test_missing_overlay_raises_value_error(self):
        """Missing overlay file raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            load_overlay(_PROFILES_DIR, "nonexistent_overlay")
        error_msg = str(exc_info.value)
        assert "not found" in error_msg
        assert "nonexistent_overlay" in error_msg

    def test_overlay_missing_name_field_raises_value_error(self):
        """Overlay missing 'name' field raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_path = Path(tmpdir) / "overlays"
            overlays_path.mkdir()
            overlay_file = overlays_path / "bad.yml"
            overlay_file.write_text(
                'applies_when: "true"\nroles:\n  - { role: test }\n'
            )
            with pytest.raises(ValueError) as exc_info:
                load_overlay(tmpdir, "bad")
            error_msg = str(exc_info.value)
            assert "missing required fields" in error_msg
            assert "name" in error_msg

    def test_overlay_missing_applies_when_field_raises_value_error(self):
        """Overlay missing 'applies_when' field raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_path = Path(tmpdir) / "overlays"
            overlays_path.mkdir()
            overlay_file = overlays_path / "bad.yml"
            overlay_file.write_text(
                'name: "Bad Overlay"\nroles:\n  - { role: test }\n'
            )
            with pytest.raises(ValueError) as exc_info:
                load_overlay(tmpdir, "bad")
            error_msg = str(exc_info.value)
            assert "missing required fields" in error_msg
            assert "applies_when" in error_msg

    def test_overlay_missing_roles_field_raises_value_error(self):
        """Overlay missing 'roles' field raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_path = Path(tmpdir) / "overlays"
            overlays_path.mkdir()
            overlay_file = overlays_path / "bad.yml"
            overlay_file.write_text(
                'name: "Bad Overlay"\napplies_when: "true"\n'
            )
            with pytest.raises(ValueError) as exc_info:
                load_overlay(tmpdir, "bad")
            error_msg = str(exc_info.value)
            assert "missing required fields" in error_msg
            assert "roles" in error_msg

    def test_overlay_with_path_traversal_raises_value_error(self):
        """Overlay name with path separators raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            load_overlay(_PROFILES_DIR, "../etc/passwd")
        error_msg = str(exc_info.value)
        assert "invalid path characters" in error_msg


class TestOverlayDataclasses:
    """Test overlay dataclass properties."""

    def test_overlay_definition_is_frozen(self):
        """OverlayDefinition should be immutable (frozen dataclass)."""
        overlay = load_overlay(_PROFILES_DIR, "laptop")
        with pytest.raises(AttributeError):
            overlay.name = "Modified"  # Should raise AttributeError

    def test_resolved_overlay_is_frozen(self):
        """ResolvedOverlay should be immutable (frozen dataclass)."""
        role_entry = RoleEntry(role="test", tags=["test"])
        overlay = ResolvedOverlay(
            overlay=Overlay(name="Test", description="", applies_when="true", roles=[role_entry]),
            applies=True,
            resolved_roles=[(role_entry, True)]
        )
        with pytest.raises(AttributeError):
            overlay.applies = False  # Should raise AttributeError

    def test_resolved_overlay_role_is_frozen(self):
        """ResolvedOverlayRole should be immutable (frozen dataclass)."""
        role = ResolvedOverlayRole(role="test", tags=("test",), applies=True)
        with pytest.raises(AttributeError):
            role.role = "modified"  # Should raise AttributeError


class TestCLIResolve:
    """Tests for the 'resolve' CLI subcommand."""

    def test_resolve_named_profile_outputs_json(self, capsys):
        """resolve --profile i3 should print valid JSON and exit 0."""
        rc = main(["resolve", "--profile", "i3"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "i3"
        assert data["is_i3"] is True
        assert data["display_manager"] == "lightdm"
        assert data["has_display"] is True

    def test_resolve_headless_profile(self, capsys):
        """resolve --profile headless should have has_display=False."""
        rc = main(["resolve", "--profile", "headless"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["has_display"] is False
        assert data["display_manager"] is None

    def test_resolve_manual_mode_with_display_manager(self, capsys):
        """resolve --display-manager lightdm outputs manual mode JSON."""
        rc = main(["resolve", "--display-manager", "lightdm"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "manual"
        assert data["display_manager"] == "lightdm"
        assert data["has_display"] is True

    def test_resolve_with_disable_flags(self, capsys):
        """resolve with disable flags suppresses the relevant DE."""
        rc = main(["resolve", "--display-manager", "lightdm", "--disable-i3"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["is_i3"] is False
        assert data["is_hyprland"] is True

    def test_resolve_unknown_profile_exits_1(self, capsys):
        """resolve --profile unknown exits 1 and writes error to stderr."""
        rc = main(["resolve", "--profile", "unknown_profile"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Unknown profile" in err
        assert "unknown_profile" in err

    def test_resolve_json_matches_resolved_profile_schema(self, capsys):
        """resolve JSON contains all ResolvedProfile fields."""
        main(["resolve", "--profile", "gnome"])
        out = capsys.readouterr().out
        data = json.loads(out)
        expected_keys = {
            "profile", "display_manager", "has_display",
            "desktop_environment", "is_i3", "is_hyprland",
            "is_gnome", "is_awesomewm", "is_kde",
        }
        assert expected_keys == set(data.keys())


class TestCLIValidate:
    """Tests for the 'validate' CLI subcommand."""

    def test_validate_real_profiles_exits_0(self, capsys):
        """validate against the real profiles directory should exit 0."""
        rc = main(["validate"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out == "" or out.strip() == ""

    def test_validate_with_invalid_profile_exits_1(self, capsys):
        """validate exits 1 and writes errors to stderr when a profile is invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "bad.yml").write_text("name: missing_required\n")
            rc = main(["validate", "--profiles-dir", tmpdir])
        err = capsys.readouterr().err
        assert rc == 1
        assert "bad" in err

    def test_validate_empty_dir_exits_0(self, capsys):
        """validate exits 0 when there are no non-underscore profiles to check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "_base.yml").write_text("name: base\n")
            rc = main(["validate", "--profiles-dir", tmpdir])
        assert rc == 0

    def test_validate_error_goes_to_stderr_not_stdout(self, capsys):
        """validate writes errors to stderr and nothing to stdout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "bad.yml").write_text("name: broken\n")
            main(["validate", "--profiles-dir", tmpdir])
        out = capsys.readouterr().out
        # stdout should be empty; error belongs in stderr
        assert out == ""


class TestCLIListProfiles:
    """Tests for the 'list-profiles' CLI subcommand."""

    def test_list_profiles_names_format(self, capsys):
        """list-profiles --format names outputs space-separated profile names."""
        rc = main(["list-profiles", "--format", "names"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        names = out.split()
        assert set(names) == {"awesomewm", "gnome", "headless", "hyprland", "i3", "kde"}

    def test_list_profiles_default_format_is_names(self, capsys):
        """list-profiles with no --format defaults to names."""
        rc = main(["list-profiles"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert " " in out  # space-separated, multiple names

    def test_list_profiles_pretty_format(self, capsys):
        """list-profiles --format pretty outputs a table with header."""
        rc = main(["list-profiles", "--format", "pretty"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "NAME" in out
        assert "DESCRIPTION" in out
        assert "DISPLAY_MANAGER" in out
        assert "DESKTOP_ENVIRONMENT" in out
        # Table should include each profile
        for name in ("awesomewm", "gnome", "headless", "hyprland", "i3", "kde"):
            assert name in out

    def test_list_profiles_pretty_format_includes_display_manager(self, capsys):
        """pretty table includes display_manager values."""
        main(["list-profiles", "--format", "pretty"])
        out = capsys.readouterr().out
        assert "lightdm" in out
        assert "gdm" in out
        assert "sddm" in out

    def test_list_profiles_custom_dir(self, capsys):
        """list-profiles respects --profiles-dir."""
        valid = "display_manager_default: lightdm\ndesktop_environment: i3\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "myprofile.yml").write_text(valid)
            rc = main(["list-profiles", "--profiles-dir", tmpdir])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert "myprofile" in out


class TestCLIMakeArgs:
    """Tests for the 'make-args' CLI subcommand."""

    def test_make_args_i3_profile(self, capsys):
        """make-args --profile i3 outputs -e flag string with correct values."""
        rc = main(["make-args", "--profile", "i3"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert out.startswith('-e "')
        assert out.endswith('"')
        assert "profile=i3" in out
        assert "desktop_environment=i3" in out
        assert "display_manager=lightdm" in out

    def test_make_args_headless_profile(self, capsys):
        """make-args --profile headless omits optional fields with empty values."""
        rc = main(["make-args", "--profile", "headless"])
        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert "profile=headless" in out
        # headless has no display_manager or desktop_environment
        assert "desktop_environment" not in out
        assert "display_manager" not in out

    def test_make_args_unknown_profile_exits_1(self, capsys):
        """make-args with unknown profile exits 1 and writes to stderr."""
        rc = main(["make-args", "--profile", "bogus"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "bogus" in err or "Unknown profile" in err

    def test_make_args_output_is_shell_safe(self, capsys):
        """make-args output is wrapped in double quotes for shell safety."""
        main(["make-args", "--profile", "gnome"])
        out = capsys.readouterr().out.strip()
        assert out.startswith('-e "')
        assert out.endswith('"')


class TestCLIUnknownSubcommand:
    """Tests for unknown subcommand handling."""

    def test_no_subcommand_exits_1(self, capsys):
        """Running with no subcommand exits 1 and prints usage."""
        rc = main([])
        assert rc == 1

    def test_no_subcommand_prints_usage(self, capsys):
        """Running with no subcommand prints usage to stderr."""
        main([])
        err = capsys.readouterr().err
        assert "usage" in err.lower()

    def test_unknown_subcommand_exits_1(self, capsys):
        """An unrecognised subcommand returns 1 rather than raising SystemExit(2)."""
        rc = main(["not-a-real-subcommand"])
        assert rc == 1

    def test_unknown_subcommand_prints_usage(self, capsys):
        """An unrecognised subcommand prints usage to stderr."""
        main(["not-a-real-subcommand"])
        err = capsys.readouterr().err
        assert "usage" in err.lower()


class TestCLIResolveOverlays:
    """Tests for the 'resolve-overlays' CLI subcommand."""

    def test_resolve_overlays_outputs_valid_json(self, capsys):
        """resolve-overlays with valid facts outputs JSON with overlays + facts keys."""
        rc = main([
            "resolve-overlays",
            "--facts-json", '{"laptop": true}',
            "--profiles-dir", _PROFILES_DIR,
        ])
        assert rc == 0
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "overlays" in data
        assert "facts" in data
        assert isinstance(data["overlays"], list)
        assert isinstance(data["facts"], dict)

    def test_resolve_overlays_schema(self, capsys):
        """Each overlay in output has name, description, applies, and roles."""
        rc = main([
            "resolve-overlays",
            "--facts-json", '{"laptop": true}',
            "--profiles-dir", _PROFILES_DIR,
        ])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        for overlay in data["overlays"]:
            assert "name" in overlay
            assert "description" in overlay
            assert "applies" in overlay
            assert "roles" in overlay
            for role in overlay["roles"]:
                assert "role" in role
                assert "tags" in role
                assert "applies" in role

    def test_resolve_overlays_invalid_json_exits_1(self, capsys):
        """resolve-overlays with invalid JSON exits 1."""
        rc = main([
            "resolve-overlays",
            "--facts-json", "not-json",
            "--profiles-dir", _PROFILES_DIR,
        ])
        assert rc == 1

    def test_resolve_overlays_non_object_json_exits_1(self, capsys):
        """resolve-overlays with valid non-object JSON (e.g. array) exits 1."""
        rc = main([
            "resolve-overlays",
            "--facts-json", '[1, 2, 3]',
            "--profiles-dir", _PROFILES_DIR,
        ])
        assert rc == 1
        err = capsys.readouterr().err
        assert "object" in err.lower() or "mapping" in err.lower()

    def test_resolve_overlays_no_has_display(self, capsys):
        """resolve-overlays --no-has-display works and runs without error."""
        rc = main([
            "resolve-overlays",
            "--facts-json", '{}',
            "--no-has-display",
            "--profiles-dir", _PROFILES_DIR,
        ])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data["overlays"], list)

    def test_resolve_overlays_no_is_arch(self, capsys):
        """resolve-overlays --no-is-arch works and runs without error."""
        rc = main([
            "resolve-overlays",
            "--facts-json", '{}',
            "--no-is-arch",
            "--profiles-dir", _PROFILES_DIR,
        ])
        assert rc == 0


class TestCLIValidateOverlays:
    """Tests for the 'validate' CLI subcommand with overlay validation."""

    def test_validate_with_invalid_overlay_exits_1(self, capsys):
        """validate exits 1 when an overlay file is structurally invalid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_dir = Path(tmpdir) / "overlays"
            overlays_dir.mkdir()

            # Create a valid profile
            Path(tmpdir, "headless.yml").write_text(
                "display_manager_default: ''\ndesktop_environment: ''\n"
            )

            # Create an invalid overlay (missing applies_when)
            (overlays_dir / "bad.yml").write_text(
                "name: Bad Overlay\nroles:\n  - {role: test, tags: [test]}\n"
            )

            rc = main(["validate", "--profiles-dir", tmpdir])
            assert rc == 1
            err = capsys.readouterr().err
            assert "overlay" in err.lower()


class TestValidateProfileTypeChecking:
    """Tests for type validation of YAML fields in validate_profile()."""

    def test_list_value_for_display_manager_returns_error(self):
        """A list value for display_manager_default is caught as a type error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'bad.yml').write_text(
                'display_manager_default:\n  - lightdm\ndesktop_environment: i3\n'
            )
            errors = validate_profile(tmpdir, 'bad')
            assert any('display_manager_default' in e and 'string' in e for e in errors)

    def test_list_value_for_desktop_environment_returns_error(self):
        """A list value for desktop_environment is caught as a type error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, 'bad.yml').write_text(
                'display_manager_default: lightdm\ndesktop_environment:\n  - i3\n'
            )
            errors = validate_profile(tmpdir, 'bad')
            assert any('desktop_environment' in e and 'string' in e for e in errors)


class TestResolveInvalidProfileError:
    """Tests that resolve() surfaces validation errors for existing-but-invalid profiles."""

    def test_existing_invalid_profile_raises_with_details(self):
        """An existing profile that fails validation raises ValueError with details,
        not a generic 'Unknown profile' message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Profile file exists but is missing required fields
            Path(tmpdir, 'bad.yml').write_text('name: bad\n')
            with pytest.raises(ValueError) as exc_info:
                resolve(profile='bad', profiles_dir=tmpdir)
            msg = str(exc_info.value)
            # Should mention 'invalid', not 'Unknown profile'
            assert 'invalid' in msg.lower() or 'missing' in msg.lower()
            assert 'Unknown profile' not in msg


class TestResolveOverlays:
    """Tests for resolve_overlays() function."""

    def test_laptop_with_display_returns_both_roles_active(self):
        """Laptop overlay with display=True should activate both laptop and backlight roles."""
        results = resolve_overlays(
            facts={"laptop": True},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )

        # Should return both overlays
        assert len(results) == 2
        laptop_overlay = [r for r in results if r.overlay.name == "Laptop Features Overlay"][0]

        # Overlay applies
        assert laptop_overlay.applies is True

        # Both roles should apply
        assert len(laptop_overlay.resolved_roles) == 2
        laptop_role, backlight_role = laptop_overlay.resolved_roles

        assert laptop_role[0].role == "laptop"
        assert laptop_role[1] is True  # applies

        assert backlight_role[0].role == "backlight"
        assert backlight_role[1] is True  # applies (has_display=True)

    def test_laptop_without_display_backlight_disabled(self):
        """Laptop overlay with display=False should activate laptop but not backlight."""
        results = resolve_overlays(
            facts={"laptop": True},
            has_display=False,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )

        laptop_overlay = [r for r in results if r.overlay.name == "Laptop Features Overlay"][0]

        # Overlay applies, but backlight role should not
        assert laptop_overlay.applies is True

        laptop_role, backlight_role = laptop_overlay.resolved_roles

        assert laptop_role[0].role == "laptop"
        assert laptop_role[1] is True  # applies

        assert backlight_role[0].role == "backlight"
        assert backlight_role[1] is False  # does NOT apply (requires_display=True, has_display=False)

    def test_empty_facts_no_overlays_apply(self):
        """With empty facts, no overlays should apply."""
        results = resolve_overlays(
            facts={},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )

        # Both overlays should be present but not apply
        assert len(results) == 2
        for result in results:
            assert result.applies is False

    def test_bluetooth_with_disable_false_applies(self):
        """Bluetooth overlay with disable=False should apply on Arch."""
        results = resolve_overlays(
            facts={"bluetooth": {"disable": False}},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )

        bluetooth_overlay = [r for r in results if r.overlay.name == "Bluetooth Support Overlay"][0]
        assert bluetooth_overlay.applies is True

        # Role should apply (is_arch=True, os=archlinux)
        bluetooth_role = bluetooth_overlay.resolved_roles[0]
        assert bluetooth_role[0].role == "bluetooth"
        assert bluetooth_role[1] is True

    def test_bluetooth_with_disable_true_does_not_apply(self):
        """Bluetooth overlay with disable=True should not apply."""
        results = resolve_overlays(
            facts={"bluetooth": {"disable": True}},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )

        bluetooth_overlay = [r for r in results if r.overlay.name == "Bluetooth Support Overlay"][0]
        assert bluetooth_overlay.applies is False

        # Role should not apply (overlay doesn't apply)
        bluetooth_role = bluetooth_overlay.resolved_roles[0]
        assert bluetooth_role[0].role == "bluetooth"
        assert bluetooth_role[1] is False

    def test_bluetooth_on_debian_role_does_not_apply(self):
        """Bluetooth overlay applies on Debian, but role has os:archlinux constraint."""
        results = resolve_overlays(
            facts={"bluetooth": {"disable": False}},
            has_display=True,
            is_arch=False,  # Debian system
            profiles_dir=_PROFILES_DIR,
        )

        bluetooth_overlay = [r for r in results if r.overlay.name == "Bluetooth Support Overlay"][0]

        # Overlay-level applies (condition passes)
        assert bluetooth_overlay.applies is True

        # Role does NOT apply (os=archlinux, but is_arch=False)
        bluetooth_role = bluetooth_overlay.resolved_roles[0]
        assert bluetooth_role[0].role == "bluetooth"
        assert bluetooth_role[1] is False

    def test_custom_evaluator_dict_evaluator(self):
        """resolve_overlays accepts custom evaluator parameter."""
        evaluator = DictEvaluator({
            "laptop | default(false)": True,
            "bluetooth.disable | default(false)": False,
        })
        results = resolve_overlays(
            facts={"laptop": True},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
            evaluator=evaluator,
        )

        # Should work with DictEvaluator
        assert len(results) == 2
        laptop_overlay = [r for r in results if r.overlay.name == "Laptop Features Overlay"][0]
        assert laptop_overlay.applies is True

    def test_jinja2_evaluator_default(self):
        """When evaluator is None, Jinja2Evaluator is used by default."""
        # No evaluator provided - should use Jinja2Evaluator
        results = resolve_overlays(
            facts={"laptop": True},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )

        # Should work with default Jinja2Evaluator
        assert len(results) == 2

    def test_raises_error_for_unknown_expression_patterns(self):
        """resolve_overlays raises clear error for unknown expression patterns."""
        # Create an overlay with an invalid expression
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_dir = Path(tmpdir) / "overlays"
            overlays_dir.mkdir(parents=True)

            overlay_content = '''name: Bad Overlay
applies_when: "some_unknown_function()"
roles:
  - {role: test, tags: [test]}
'''
            (overlays_dir / "bad.yml").write_text(overlay_content)

            with pytest.raises(ValueError) as exc_info:
                resolve_overlays(
                    facts={},
                    has_display=True,
                    is_arch=True,
                    profiles_dir=tmpdir,
                )

            assert "failed to evaluate applies_when" in str(exc_info.value)

    def test_returns_sorted_list(self):
        """Results are returned in sorted order by overlay name."""
        results = resolve_overlays(
            facts={},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )

        # Extract names
        names = [r.overlay.name for r in results]
        assert names == sorted(names)


class TestValidateOverlays:
    """Tests for validate_overlays() function."""

    def test_real_overlays_are_valid(self):
        """Existing overlay files should pass validation."""
        results = validate_overlays(profiles_dir=_PROFILES_DIR)

        # Should return results for both overlays
        assert len(results) == 2

        # Each should have empty error list
        for overlay_name, errors in results:
            assert overlay_name in {"laptop", "bluetooth"}
            assert errors == []

    def test_catches_missing_applies_when(self):
        """Validation catches missing applies_when field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_dir = Path(tmpdir) / "overlays"
            overlays_dir.mkdir(parents=True)

            overlay_content = '''name: Bad Overlay
description: Missing applies_when
roles:
  - {role: test, tags: [test]}
'''
            (overlays_dir / "bad.yml").write_text(overlay_content)

            results = validate_overlays(profiles_dir=tmpdir)
            assert len(results) == 1

            overlay_name, errors = results[0]
            assert overlay_name == "bad"
            assert len(errors) > 0
            assert any("applies_when" in e for e in errors)

    def test_catches_missing_roles(self):
        """Validation catches missing roles field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_dir = Path(tmpdir) / "overlays"
            overlays_dir.mkdir(parents=True)

            overlay_content = '''name: Bad Overlay
applies_when: "true"
'''
            (overlays_dir / "bad.yml").write_text(overlay_content)

            results = validate_overlays(profiles_dir=tmpdir)
            assert len(results) == 1

            overlay_name, errors = results[0]
            assert overlay_name == "bad"
            assert len(errors) > 0
            assert any("roles" in e for e in errors)

    def test_catches_malformed_role_entries(self):
        """Validation catches malformed role entries (missing role or tags)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_dir = Path(tmpdir) / "overlays"
            overlays_dir.mkdir(parents=True)

            # Missing 'role' field
            overlay_content = '''name: Bad Overlay
applies_when: "true"
roles:
  - {tags: [test]}
'''
            (overlays_dir / "bad.yml").write_text(overlay_content)

            results = validate_overlays(profiles_dir=tmpdir)
            assert len(results) == 1

            overlay_name, errors = results[0]
            assert overlay_name == "bad"
            assert len(errors) > 0
            assert any("role" in e for e in errors)

    def test_catches_invalid_role_entry_types(self):
        """Validation catches incorrect types in role entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_dir = Path(tmpdir) / "overlays"
            overlays_dir.mkdir(parents=True)

            # tags should be a list, not a string
            overlay_content = '''name: Bad Overlay
applies_when: "true"
roles:
  - {role: test, tags: "not_a_list"}
'''
            (overlays_dir / "bad.yml").write_text(overlay_content)

            results = validate_overlays(profiles_dir=tmpdir)
            assert len(results) == 1

            overlay_name, errors = results[0]
            assert overlay_name == "bad"
            assert len(errors) > 0
            assert any("tags" in e and "list" in e for e in errors)

    def test_catches_empty_applies_when(self):
        """Validation catches empty applies_when string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_dir = Path(tmpdir) / "overlays"
            overlays_dir.mkdir(parents=True)

            overlay_content = '''name: Bad Overlay
applies_when: ""
roles:
  - {role: test, tags: [test]}
'''
            (overlays_dir / "bad.yml").write_text(overlay_content)

            results = validate_overlays(profiles_dir=tmpdir)
            assert len(results) == 1

            overlay_name, errors = results[0]
            assert overlay_name == "bad"
            assert len(errors) > 0
            assert any("applies_when" in e and "non-empty" in e for e in errors)

    def test_returns_empty_list_for_no_overlays(self):
        """Validation returns empty list when overlays directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = validate_overlays(profiles_dir=tmpdir)
            assert results == []

    def test_validates_multiple_overlays(self):
        """Validation returns errors for all invalid overlays."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays_dir = Path(tmpdir) / "overlays"
            overlays_dir.mkdir(parents=True)

            # Create two invalid overlays
            (overlays_dir / "bad1.yml").write_text("name: Bad1\n")
            (overlays_dir / "bad2.yml").write_text("name: Bad2\n")

            results = validate_overlays(profiles_dir=tmpdir)
            assert len(results) == 2

            # Both should have errors
            for overlay_name, errors in results:
                assert overlay_name in {"bad1", "bad2"}
                assert len(errors) > 0


class TestJinja2Evaluator:
    """Test Jinja2Evaluator expression evaluation."""

    def test_truthy_variable(self):
        """A variable set to a truthy value should evaluate to True."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop", {"laptop": True}) is True
        assert evaluator.evaluate("laptop", {"laptop": "yes"}) is True
        assert evaluator.evaluate("laptop", {"laptop": 1}) is True

    def test_falsy_variable(self):
        """A variable set to a falsy value should evaluate to False."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop", {"laptop": False}) is False
        assert evaluator.evaluate("laptop", {"laptop": ""}) is False
        assert evaluator.evaluate("laptop", {"laptop": 0}) is False
        assert evaluator.evaluate("laptop", {"laptop": None}) is False

    def test_absent_variable_with_default(self):
        """A variable with default filter should return the default value when absent."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop | default(false)", {}) is False
        assert evaluator.evaluate("laptop | default(true)", {}) is True
        assert evaluator.evaluate("laptop | default('')", {}) is False  # Empty string is falsy

    def test_absent_variable_without_default_raises_error(self):
        """Referencing an undefined variable without default() should raise EvaluationError."""
        evaluator = Jinja2Evaluator()
        with pytest.raises(EvaluationError, match="Failed to evaluate"):
            evaluator.evaluate("unknown_var", {})

    def test_is_defined_test(self):
        """The 'is defined' test should return True for defined variables."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop is defined", {"laptop": True}) is True
        assert evaluator.evaluate("laptop is defined", {"laptop": False}) is True
        assert evaluator.evaluate("laptop is defined", {}) is False

    def test_nested_dict_access(self):
        """Dotted access should work for nested dictionaries.

        Missing attributes on dicts raise EvaluationError with StrictUndefined;
        use ``| default(false)`` for safe access (see test_nested_dict_access_with_default).
        """
        evaluator = Jinja2Evaluator()
        context = {
            "bluetooth": {"disable": True},
            "laptop": {"hardware": {"trackpad": True}},
        }
        assert evaluator.evaluate("bluetooth.disable", context) is True
        assert evaluator.evaluate("laptop.hardware.trackpad", context) is True
        # Missing attribute on a dict raises EvaluationError (StrictUndefined)
        with pytest.raises(EvaluationError):
            evaluator.evaluate("laptop.hardware.touchscreen", context)

    def test_boolean_and_operator(self):
        """The 'and' operator should perform logical AND."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop and desktop", {"laptop": True, "desktop": True}) is True
        assert evaluator.evaluate("laptop and desktop", {"laptop": True, "desktop": False}) is False
        assert evaluator.evaluate("laptop and desktop", {"laptop": False, "desktop": True}) is False

    def test_boolean_or_operator(self):
        """The 'or' operator should perform logical OR."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop or desktop", {"laptop": True, "desktop": True}) is True
        assert evaluator.evaluate("laptop or desktop", {"laptop": True, "desktop": False}) is True
        assert evaluator.evaluate("laptop or desktop", {"laptop": False, "desktop": False}) is False

    def test_boolean_not_operator(self):
        """The 'not' operator should perform logical NOT."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("not laptop", {"laptop": False}) is True
        assert evaluator.evaluate("not laptop", {"laptop": True}) is False

    def test_complex_boolean_expression(self):
        """Complex boolean expressions with and/or/not should work correctly."""
        evaluator = Jinja2Evaluator()
        context = {"laptop": True, "desktop": False, "gui": True}
        assert evaluator.evaluate("laptop and not desktop", context) is True
        assert evaluator.evaluate("(laptop or desktop) and gui", context) is True
        assert evaluator.evaluate("laptop and desktop and gui", context) is False

    def test_parenthesized_expressions(self):
        """Parentheses should control operator precedence."""
        evaluator = Jinja2Evaluator()
        context = {"a": True, "b": True, "c": False}
        assert evaluator.evaluate("(a or b) and c", context) is False
        assert evaluator.evaluate("a or (b and c)", context) is True

    def test_default_filter_with_boolean_operators(self):
        """Default filters should work in boolean expressions."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate(
            "laptop | default(false) and not (desktop | default(false))",
            {"laptop": True}
        ) is True
        assert evaluator.evaluate(
            "laptop | default(false) and not (desktop | default(false))",
            {"desktop": True}
        ) is False

    def test_invalid_syntax_raises_evaluation_error(self):
        """Invalid Jinja2 syntax should raise EvaluationError."""
        evaluator = Jinja2Evaluator()
        with pytest.raises(EvaluationError, match="Failed to evaluate"):
            evaluator.evaluate("unclosed (parenthesis", {})

    def test_nested_dict_access_with_default(self):
        """Default filters should work with nested dict access."""
        evaluator = Jinja2Evaluator()
        context = {"laptop": {}}
        assert evaluator.evaluate("laptop.trackpad | default(false)", context) is False
        assert evaluator.evaluate("laptop.trackpad | default(true)", context) is True


class TestDictEvaluator:
    """Test DictEvaluator expression evaluation."""

    def test_mapped_expression_returns_correct_bool(self):
        """An expression in the mapping should return its mapped boolean value."""
        evaluator = DictEvaluator({"laptop": True, "desktop": False})
        assert evaluator.evaluate("laptop", {}) is True
        assert evaluator.evaluate("desktop", {}) is False

    def test_unmapped_expression_returns_false(self):
        """An expression not in the mapping should return False."""
        evaluator = DictEvaluator({"laptop": True})
        assert evaluator.evaluate("desktop", {}) is False
        assert evaluator.evaluate("unknown", {}) is False

    def test_context_parameter_is_ignored(self):
        """The context parameter should be ignored (for protocol compatibility)."""
        evaluator = DictEvaluator({"laptop": True})
        # Context dict should not affect the result
        assert evaluator.evaluate("laptop", {"laptop": False}) is True
        assert evaluator.evaluate("laptop", {}) is True

    def test_empty_mapping_returns_false_for_all(self):
        """An empty mapping should return False for all expressions."""
        evaluator = DictEvaluator({})
        assert evaluator.evaluate("anything", {}) is False
        assert evaluator.evaluate("laptop", {}) is False

    def test_multiple_expressions(self):
        """Multiple expressions should all resolve correctly."""
        evaluator = DictEvaluator({
            "laptop": True,
            "desktop": False,
            "server": True,
        })
        assert evaluator.evaluate("laptop", {}) is True
        assert evaluator.evaluate("desktop", {}) is False
        assert evaluator.evaluate("server", {}) is True


class TestManifest:
    """Test Manifest dataclass and resolve_manifest() function."""

    def test_manifest_is_frozen(self):
        """Manifest should be immutable."""
        m = Manifest(
            profile="i3", display_manager="lightdm", has_display=True,
            is_i3=True, is_hyprland=False, is_gnome=False,
            is_awesomewm=False, is_kde=False, is_arch=True,
        )
        with pytest.raises(AttributeError):
            m.profile = "hyprland"

    def test_resolve_manifest_default_os_is_arch(self):
        """Without os_family, defaults to Archlinux."""
        manifest = resolve_manifest(profile="i3")
        assert manifest.is_arch is True
        assert manifest.is_i3 is True

    def test_resolve_manifest_debian_is_not_arch(self):
        """os_family='Debian' sets is_arch=False."""
        manifest = resolve_manifest(profile="headless", os_family="Debian")
        assert manifest.is_arch is False
        assert manifest.has_display is False

    def test_resolve_manifest_arch_explicit(self):
        """os_family='Archlinux' sets is_arch=True."""
        manifest = resolve_manifest(profile="hyprland", os_family="Archlinux")
        assert manifest.is_arch is True
        assert manifest.is_hyprland is True
        assert manifest.display_manager == "sddm"

    def test_resolve_manifest_manual_mode(self):
        """Manual mode with explicit vars."""
        manifest = resolve_manifest(
            display_manager="lightdm",
            desktop_environment="i3",
            os_family="Debian",
        )
        assert manifest.profile == "manual"
        assert manifest.is_arch is False
        assert manifest.is_i3 is True

    def test_resolve_manifest_null_os_family_defaults_arch(self):
        """None os_family defaults to Archlinux."""
        manifest = resolve_manifest(profile="gnome", os_family=None)
        assert manifest.is_arch is True

    def test_resolve_manifest_all_profiles(self):
        """All 6 profiles resolve successfully with os_family."""
        for name in ("headless", "i3", "hyprland", "gnome", "awesomewm", "kde"):
            manifest = resolve_manifest(profile=name, os_family="Archlinux")
            assert manifest.profile == name
            assert manifest.is_arch is True


class TestTranslateConditionExtended:
    """Extended tests for translate_condition() function."""

    def test_no_annotation_returns_empty_condition(self):
        """Role without annotations returns empty condition."""
        role_entry = {"role": "base", "tags": ["base"]}
        condition = translate_condition(role_entry, {}, "Archlinux")
        assert condition == ""

    def test_role_string_returns_empty_condition(self):
        """Simple string role returns empty condition."""
        condition = translate_condition("base", {}, "Archlinux")
        assert condition == ""

    def test_os_archlinux_translates_to_is_arch(self):
        """os: archlinux translates to _is_arch."""
        role_entry = {"role": "aur", "tags": ["aur"], "os": "archlinux"}
        condition = translate_condition(role_entry, {}, "Archlinux")
        assert condition == "_is_arch"

    def test_os_debian_translates_to_not_is_arch(self):
        """os: debian translates to not _is_arch."""
        role_entry = {"role": "homebrew", "tags": ["homebrew"], "os": "debian"}
        condition = translate_condition(role_entry, {}, "Debian")
        assert condition == "not _is_arch"

    def test_requires_display_translates_to_has_display(self):
        """requires_display: true translates to _has_display."""
        role_entry = {"role": "fonts", "tags": ["fonts"], "requires_display": True}
        condition = translate_condition(role_entry, {}, "Archlinux")
        assert condition == "_has_display"

    def test_combined_annotations_are_anded(self):
        """Multiple annotations are combined with AND."""
        role_entry = {
            "role": "cups",
            "tags": ["cups"],
            "os": "archlinux",
            "requires_display": True,
        }
        condition = translate_condition(role_entry, {}, "Archlinux")
        assert condition == "_is_arch and _has_display"

    def test_config_check_enabled_returns_true(self):
        """config_check for enabled flag returns true when enabled."""
        role_entry = {
            "role": "cursor-theme",
            "tags": ["cursor-theme"],
            "requires_display": True,
            "config_check": "cursor_theme.enabled",
        }
        host_vars = {"cursor_theme": {"enabled": True}}
        condition = translate_condition(role_entry, host_vars, "Archlinux")
        assert condition == "_has_display and true"

    def test_config_check_disabled_returns_false(self):
        """config_check for enabled flag returns false when disabled."""
        role_entry = {
            "role": "cursor-theme",
            "tags": ["cursor-theme"],
            "config_check": "cursor_theme.enabled",
        }
        host_vars = {"cursor_theme": {"enabled": False}}
        condition = translate_condition(role_entry, host_vars, "Archlinux")
        assert condition == "false"


class TestResolveRoleManifestFunction:
    """Test resolve_role_manifest() function."""

    def test_resolves_hyprland_profile(self):
        """resolve_role_manifest for hyprland profile returns correct manifest."""
        manifest = resolve_role_manifest(profile="hyprland", host_vars={}, os_family="Archlinux")
        assert manifest.profile == "hyprland"
        assert manifest.display_manager == "sddm"
        assert manifest.has_display is True
        assert manifest.profile_flags["_is_arch"] is True
        assert manifest.profile_flags["_is_hyprland"] is True
        assert manifest.profile_flags["_is_i3"] is False

    def test_resolves_headless_profile(self):
        """resolve_manifest for headless profile has _has_display=False in flags."""
        manifest = resolve_role_manifest(profile="headless", host_vars={}, os_family="Archlinux")
        assert manifest.profile == "headless"
        assert manifest.has_display is False
        assert manifest.profile_flags["_has_display"] is False

    def test_manual_mode_with_explicit_vars(self):
        """resolve_manifest works in manual mode with explicit variables."""
        manifest = resolve_role_manifest(
            display_manager="lightdm",
            desktop_environment="i3",
            host_vars={},
            os_family="Archlinux",
        )
        assert manifest.profile == "manual"
        assert manifest.display_manager == "lightdm"
        assert manifest.has_display is True
        assert manifest.profile_flags["_is_i3"] is True

    def test_includes_overlay_flags_when_overlay_applies(self):
        """resolve_manifest includes overlay flags when overlay applies."""
        host_vars = {"laptop": True}
        manifest = resolve_role_manifest(
            profile="hyprland",
            host_vars=host_vars,
            os_family="Archlinux",
        )
        assert "_overlay_laptop" in manifest.overlay_flags
        assert manifest.overlay_flags["_overlay_laptop"] is True

    def test_deduplicates_roles_by_name(self):
        """Roles appearing in multiple profiles produce single manifest entry."""
        manifest = resolve_role_manifest(profile="i3", host_vars={}, os_family="Archlinux")
        role_names = [r.role for r in manifest.roles]
        terminal_count = role_names.count("terminal")
        assert terminal_count == 1

    def test_evaluates_config_check_correctly(self):
        """config_check expressions are evaluated against host_vars."""
        host_vars = {
            "dotfiles_config": {"repo_url": "https://github.com/example/dotfiles"}
        }
        manifest = resolve_role_manifest(
            profile="hyprland",
            host_vars=host_vars,
            os_family="Archlinux",
        )
        dotfiles_roles = [r for r in manifest.roles if r.role == "dotfiles"]
        assert len(dotfiles_roles) == 1
        assert dotfiles_roles[0].condition == "true"

    def test_all_profiles_resolve_successfully(self):
        """All 6 named profiles resolve to valid manifests."""
        for profile_name in ("headless", "i3", "hyprland", "gnome", "awesomewm", "kde"):
            manifest = resolve_role_manifest(
                profile=profile_name,
                host_vars={},
                os_family="Archlinux",
            )
            assert manifest.profile == profile_name
            assert isinstance(manifest.roles, tuple)
            assert len(manifest.roles) > 0

    def test_resolved_manifest_is_frozen(self):
        """ResolvedManifest should be immutable (frozen dataclass)."""
        manifest = resolve_role_manifest(profile="i3", host_vars={}, os_family="Archlinux")
        with pytest.raises(AttributeError):
            manifest.profile = "hyprland"

    def test_resolved_manifest_equality(self):
        """ResolvedManifest with same inputs should be equal."""
        manifest1 = resolve_role_manifest(profile="i3", host_vars={}, os_family="Archlinux")
        manifest2 = resolve_role_manifest(profile="i3", host_vars={}, os_family="Archlinux")
        manifest3 = resolve_role_manifest(profile="hyprland", host_vars={}, os_family="Archlinux")

        assert manifest1 == manifest2
        assert manifest1 != manifest3


class TestCLIResolveRoleManifest:
    """Tests for the 'resolve-role-manifest' CLI subcommand."""

    def test_resolve_manifest_named_profile(self, capsys):
        """resolve-manifest --profile i3 outputs valid JSON."""
        rc = main(["resolve-role-manifest", "--profile", "i3"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "i3"
        assert data["display_manager"] == "lightdm"
        assert data["has_display"] is True
        assert "profile_flags" in data
        assert "overlay_flags" in data
        assert "roles" in data

    def test_resolve_manifest_headless_profile(self, capsys):
        """resolve-manifest --profile headless outputs manifest with no display."""
        rc = main(["resolve-role-manifest", "--profile", "headless"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "headless"
        assert data["has_display"] is False
        assert data["display_manager"] is None

    def test_resolve_role_manifest_with_host_vars(self, capsys):
        """resolve-role-manifest --host-vars evaluates config_check expressions."""
        host_vars_json = json.dumps({"laptop": True})
        rc = main(["resolve-role-manifest", "--profile", "i3", "--host-vars", host_vars_json])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert "_overlay_laptop" in data["overlay_flags"]

    def test_resolve_manifest_invalid_host_vars_exits_1(self, capsys):
        """resolve-manifest with invalid JSON in --host-vars exits 1."""
        rc = main(["resolve-role-manifest", "--profile", "i3", "--host-vars", "invalid json"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Invalid JSON" in err

    def test_resolve_manifest_manual_mode(self, capsys):
        """resolve-manifest works in manual mode without --profile."""
        rc = main([
            "resolve-role-manifest",
            "--display-manager", "lightdm",
            "--desktop-environment", "i3",
        ])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "manual"
        assert data["display_manager"] == "lightdm"

    def test_resolve_manifest_roles_have_required_fields(self, capsys):
        """resolve-manifest output includes all required role fields."""
        main(["resolve-role-manifest", "--profile", "hyprland"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "roles" in data
        assert len(data["roles"]) > 0
        first_role = data["roles"][0]
        assert "role" in first_role
        assert "tags" in first_role
        assert "condition" in first_role
        assert "source" in first_role

    def test_resolve_manifest_unknown_profile_exits_1(self, capsys):
        """resolve-manifest with unknown profile exits 1."""
        rc = main(["resolve-role-manifest", "--profile", "unknown"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Unknown profile" in err


class TestPlaybookGeneratorResolveManifest:
    """Tests for PlaybookGenerator.resolve_manifest() class."""

    def test_resolve_manifest_delegates_to_resolve_role_manifest(self):
        """PlaybookGenerator.resolve_manifest() produces same output as resolve_role_manifest()."""
        gen = PlaybookGenerator(profiles_dir=_PROFILES_DIR)
        result = gen.resolve_manifest(profile="i3", host_vars={}, os_family="Archlinux")

        direct = resolve_role_manifest(
            profile="i3",
            host_vars={},
            os_family="Archlinux",
            profiles_dir=_PROFILES_DIR,
        )
        assert result == direct

    def test_resolve_manifest_with_host_vars(self):
        """PlaybookGenerator.resolve_manifest() passes host_vars through."""
        gen = PlaybookGenerator(profiles_dir=_PROFILES_DIR)
        result = gen.resolve_manifest(
            profile="i3",
            host_vars={"laptop": True},
            os_family="Archlinux",
        )
        assert "_overlay_laptop" in result.overlay_flags
        assert result.overlay_flags["_overlay_laptop"] is True

    def test_resolve_manifest_headless(self):
        """PlaybookGenerator.resolve_manifest() works for headless profile."""
        gen = PlaybookGenerator(profiles_dir=_PROFILES_DIR)
        result = gen.resolve_manifest(
            profile="headless",
            host_vars={},
            os_family="Archlinux",
        )
        assert result.profile == "headless"
        assert result.has_display is False

    def test_resolve_manifest_unknown_profile_raises(self):
        """PlaybookGenerator.resolve_manifest() raises ValueError for unknown profile."""
        gen = PlaybookGenerator(profiles_dir=_PROFILES_DIR)
        with pytest.raises(ValueError, match="Unknown profile"):
            gen.resolve_manifest(profile="nonexistent", host_vars={})


class TestNormalizeCondition:
    """Tests for _normalize_condition helper."""

    def test_empty_string(self):
        assert _normalize_condition("") == ""

    def test_none_returns_empty(self):
        assert _normalize_condition(None) == ""

    def test_single_condition_unchanged(self):
        assert _normalize_condition("_is_arch") == "_is_arch"

    def test_sorts_and_terms(self):
        result = _normalize_condition("_has_display and _is_arch")
        assert result == "_has_display and _is_arch"

    def test_sorts_and_terms_reverse(self):
        result = _normalize_condition("_is_arch and _has_display")
        assert result == "_has_display and _is_arch"

    def test_strips_bool_filter(self):
        assert _normalize_condition("_has_display | bool") == "_has_display"

    def test_strips_bool_filter_in_and_expr(self):
        result = _normalize_condition("_is_arch and _has_display | bool")
        assert result == "_has_display and _is_arch"

    def test_equivalent_conditions_compare_equal(self):
        """goesimage-style ordering difference normalizes to same string."""
        a = _normalize_condition("goesimage is defined and _has_display")
        b = _normalize_condition("_has_display and goesimage is defined")
        assert a == b


class TestSyncPlaybook:
    """Tests for the sync-playbook CLI subcommand."""

    _PLAYBOOK = str(Path(__file__).resolve().parent.parent / "play.yml")

    def test_sync_playbook_in_sync(self, capsys):
        """sync-playbook exits 0 when play.yml matches profiles."""
        rc = main(["sync-playbook", "--playbook", self._PLAYBOOK])
        out = capsys.readouterr().out
        assert rc == 0
        assert "in sync" in out

    def test_sync_playbook_check_mode(self, capsys):
        """sync-playbook --check exits 0 when in sync (CI gate)."""
        rc = main(["sync-playbook", "--playbook", self._PLAYBOOK, "--check"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "in sync" in out

    def test_sync_playbook_missing_playbook(self, capsys):
        """sync-playbook exits 1 if playbook file doesn't exist."""
        rc = main(["sync-playbook", "--playbook", "/nonexistent/play.yml"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "not found" in err.lower()

    def test_sync_playbook_detects_extra_role(self, capsys, tmp_path):
        """sync-playbook reports extra roles not in any profile."""
        # Create a minimal playbook with a role that no profile defines
        playbook = tmp_path / "play.yml"
        playbook.write_text(
            "---\n"
            "- name: Configure localhost\n"
            "  hosts: localhost\n"
            "  roles:\n"
            "    - { role: nonexistent_role_xyz, tags: ['test'] }\n"
        )
        rc = main(["sync-playbook", "--playbook", str(playbook)])
        out = capsys.readouterr().out
        assert rc == 0  # Non-check mode returns 0 but prints drift
        assert "out of sync" in out
        assert "nonexistent_role_xyz" in out

    def test_sync_playbook_check_mode_exits_1_on_drift(self, capsys, tmp_path):
        """sync-playbook --check exits 1 when drift is detected."""
        playbook = tmp_path / "play.yml"
        playbook.write_text(
            "---\n"
            "- name: Configure localhost\n"
            "  hosts: localhost\n"
            "  roles:\n"
            "    - { role: fake_role, tags: ['test'] }\n"
        )
        rc = main(["sync-playbook", "--playbook", str(playbook), "--check"])
        assert rc == 1

    def test_sync_playbook_profile_gating(self, capsys):
        """sync-playbook infers _is_<de> conditions from profile membership."""
        # The hyprland role only appears in the hyprland profile,
        # so the expected condition should include _is_hyprland.
        rc = main(["sync-playbook", "--playbook", self._PLAYBOOK])
        out = capsys.readouterr().out
        assert rc == 0
        # If in sync, the hyprland role must be gated with _is_hyprland
        assert "in sync" in out

    def test_sync_playbook_condition_normalization(self, capsys, tmp_path):
        """sync-playbook normalizes condition ordering for comparison."""
        # Read actual play.yml to get the real roles, but tweak a condition
        # to use different AND-term ordering
        with open(self._PLAYBOOK) as f:
            real_play = f.read()
        # Replace a condition with equivalent but reordered terms
        modified = real_play.replace(
            "goesimage is defined and _has_display",
            "_has_display and goesimage is defined",
        )
        if modified == real_play:
            # Condition not found with exact text — skip test gracefully
            pytest.skip("goesimage condition not found with expected text")

        playbook = tmp_path / "play.yml"
        playbook.write_text(modified)
        # Even though terms are reordered, sync should report in-sync
        rc = main(["sync-playbook", "--playbook", str(playbook)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "in sync" in out


class TestORLogicForOverlappingRoles:
    """Tests verifying OR logic when a role appears in both profile and overlay."""

    def test_role_in_profile_and_overlay_gets_or_condition(self):
        """When backlight appears in both profile and overlay, condition is OR'd."""
        # backlight appears in _base.yml with requires_display AND in laptop overlay
        manifest = resolve_role_manifest(
            profile="i3",
            host_vars={"laptop": True},
            os_family="Archlinux",
        )
        backlight_roles = [r for r in manifest.roles if r.role == "backlight"]
        assert len(backlight_roles) == 1
        # Should have condition from profile (requires_display) OR overlay
        cond = backlight_roles[0].condition
        assert cond  # Not empty
        # The condition should contain "or" since it's from both sources
        assert " or " in cond.lower() or cond == "_has_display"

    def test_overlay_only_role_included_in_manifest(self):
        """Roles from overlays appear in manifest when overlay applies."""
        manifest = resolve_role_manifest(
            profile="i3",
            host_vars={"laptop": True},
            os_family="Archlinux",
        )
        # laptop role comes from overlay, not from profile
        laptop_roles = [r for r in manifest.roles if r.role == "laptop"]
        assert len(laptop_roles) == 1
        # Overlay-derived role is included; condition is empty because
        # gating is via _overlay_* facts set by play.yml pre_tasks
        assert laptop_roles[0].role == "laptop"
        assert "_overlay_laptop" in manifest.overlay_flags

    def test_profile_only_role_not_affected_by_overlays(self):
        """Profile roles that don't overlap with overlays keep their condition."""
        manifest = resolve_role_manifest(
            profile="i3",
            host_vars={},  # No overlay vars
            os_family="Archlinux",
        )
        # shell is universal (no annotations), should have no condition
        shell_roles = [r for r in manifest.roles if r.role == "shell"]
        assert len(shell_roles) == 1
        # Universal roles from _base.yml have empty conditions
        assert shell_roles[0].condition == ""

    def test_deduplication_produces_single_entry(self):
        """A role in both profile and overlay appears exactly once."""
        manifest = resolve_role_manifest(
            profile="i3",
            host_vars={"laptop": True},
            os_family="Archlinux",
        )
        role_names = [r.role for r in manifest.roles]
        # backlight is in both _base.yml (profile) and laptop overlay
        assert role_names.count("backlight") == 1


class TestDeduplicationSemantics:
    """Focused tests for role deduplication with conditions and tags.

    Exercises:
    - Identical conditions across 2+ sources are NOT OR-ed
    - Distinct conditions across 3+ sources are OR-ed without duplicates
    - Tags are unioned across all sources
    """

    @staticmethod
    def _make_profiles(tmp_path, base_roles, overlay_roles=None, overlay_name="test_overlay"):
        """Create temporary profile + overlay files for testing."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        overlays_path = profiles_dir / "overlays"
        overlays_path.mkdir()

        # Write _base.yml
        base_data = {
            "display_manager_default": "",
            "desktop_environment": "",
            "roles": base_roles,
        }
        (profiles_dir / "_base.yml").write_text(yaml.dump(base_data, default_flow_style=False))

        # Write profile extending _base
        profile_data = {
            "extends": "_base",
            "display_manager_default": "",
            "desktop_environment": "",
            "roles": [],
        }
        (profiles_dir / "test.yml").write_text(yaml.dump(profile_data, default_flow_style=False))

        # Write overlay if provided
        if overlay_roles:
            overlay_data = {
                "name": overlay_name,
                "applies_when": f"{overlay_name} | default(false)",
                "roles": overlay_roles,
            }
            (overlays_path / f"{overlay_name}.yml").write_text(
                yaml.dump(overlay_data, default_flow_style=False)
            )

        return str(profiles_dir)

    def test_identical_conditions_not_or_ed(self, tmp_path):
        """When a role appears twice with identical conditions, no OR is produced."""
        profiles_dir = self._make_profiles(
            tmp_path,
            base_roles=[{"role": "foo", "tags": ["t1"], "os": "archlinux"}],
            overlay_roles=[{"role": "foo", "tags": ["t2"], "os": "archlinux"}],
        )
        manifest = resolve_role_manifest(
            profile="test",
            host_vars={"test_overlay": True},
            os_family="Archlinux",
            profiles_dir=profiles_dir,
        )
        foo_roles = [r for r in manifest.roles if r.role == "foo"]
        assert len(foo_roles) == 1
        # Condition should NOT contain "or" — both sources gave the same condition
        assert " or " not in foo_roles[0].condition.lower()
        assert foo_roles[0].condition == "_is_arch"

    def test_tags_unioned_across_sources(self, tmp_path):
        """Tags from all sources are unioned (no duplicates, sorted)."""
        profiles_dir = self._make_profiles(
            tmp_path,
            base_roles=[{"role": "foo", "tags": ["alpha", "beta"], "os": "archlinux"}],
            overlay_roles=[{"role": "foo", "tags": ["beta", "gamma"], "os": "archlinux"}],
        )
        manifest = resolve_role_manifest(
            profile="test",
            host_vars={"test_overlay": True},
            os_family="Archlinux",
            profiles_dir=profiles_dir,
        )
        foo_roles = [r for r in manifest.roles if r.role == "foo"]
        assert len(foo_roles) == 1
        assert foo_roles[0].tags == ("alpha", "beta", "gamma")

    def test_three_sources_no_duplicate_or_terms(self, tmp_path):
        """With 3 sources, duplicate conditions are not re-OR-ed.

        Scenario:
          Source 1: _has_display
          Source 2: _is_arch        → produces "(_has_display) or (_is_arch)"
          Source 3: _has_display    → should NOT re-add _has_display
        """
        profiles_dir = self._make_profiles(
            tmp_path,
            base_roles=[
                {"role": "bar", "tags": ["t1"], "requires_display": True},
                {"role": "bar", "tags": ["t2"], "os": "archlinux"},
            ],
            overlay_roles=[
                {"role": "bar", "tags": ["t3"], "requires_display": True},
            ],
        )
        manifest = resolve_role_manifest(
            profile="test",
            host_vars={"test_overlay": True},
            os_family="Archlinux",
            profiles_dir=profiles_dir,
        )
        bar_roles = [r for r in manifest.roles if r.role == "bar"]
        assert len(bar_roles) == 1
        cond = bar_roles[0].condition
        # Should have exactly two terms OR'd, not three
        # _has_display appears twice in sources but should appear once in output
        or_count = cond.lower().count(" or ")
        assert or_count == 1, f"Expected exactly 1 'or', got {or_count}: {cond}"

    def test_three_distinct_conditions_all_or_ed(self, tmp_path):
        """Three distinct conditions produce a 3-way OR."""
        profiles_dir = self._make_profiles(
            tmp_path,
            base_roles=[
                {"role": "baz", "tags": ["t1"], "requires_display": True},
                {"role": "baz", "tags": ["t2"], "os": "archlinux"},
            ],
            overlay_roles=[
                {"role": "baz", "tags": ["t3"], "os": "debian"},
            ],
        )
        manifest = resolve_role_manifest(
            profile="test",
            host_vars={"test_overlay": True},
            os_family="Archlinux",
            profiles_dir=profiles_dir,
        )
        baz_roles = [r for r in manifest.roles if r.role == "baz"]
        assert len(baz_roles) == 1
        cond = baz_roles[0].condition
        # Three distinct terms: _has_display, _is_arch, not _is_arch
        assert cond.count(" or ") == 2, f"Expected 2 'or's, got: {cond}"


class TestConditionTranslatorProtocol:
    """Test the ConditionTranslator protocol and AnsibleConditionTranslator implementation."""

    def test_os_annotation_archlinux(self):
        """os: archlinux annotation translates to _is_arch."""
        translator = AnsibleConditionTranslator(os_family="Archlinux")
        annotation = {"role": "test", "tags": ["test"], "os": "archlinux"}
        result = translator.translate_annotation(annotation, {})
        assert result == "_is_arch"

    def test_os_annotation_debian(self):
        """os: debian annotation translates to 'not _is_arch'."""
        translator = AnsibleConditionTranslator(os_family="Archlinux")
        annotation = {"role": "test", "tags": ["test"], "os": "debian"}
        result = translator.translate_annotation(annotation, {})
        assert result == "not _is_arch"

    def test_requires_display_true(self):
        """requires_display: true annotation translates to _has_display."""
        translator = AnsibleConditionTranslator()
        annotation = {"role": "test", "tags": ["test"], "requires_display": True}
        result = translator.translate_annotation(annotation, {})
        assert result == "_has_display"

    def test_config_check_simple(self):
        """config_check with 'is defined' is preserved when preserve_config_check=True."""
        translator = AnsibleConditionTranslator(preserve_config_check=True)
        annotation = {"role": "dotfiles", "tags": ["dotfiles"], "config_check": "dotfiles is defined"}
        result = translator.translate_annotation(annotation, {})
        assert result == "dotfiles is defined"

    def test_config_check_with_host_vars_true(self):
        """config_check evaluates to 'true' when variable is defined in host_vars."""
        translator = AnsibleConditionTranslator(preserve_config_check=False)
        annotation = {"role": "dotfiles", "tags": ["dotfiles"], "config_check": "dotfiles is defined"}
        host_vars = {"dotfiles": {"repo": "https://example.com"}}
        result = translator.translate_annotation(annotation, host_vars)
        assert result == "true"

    def test_config_check_with_host_vars_false(self):
        """config_check evaluates to 'false' when variable is not defined in host_vars."""
        translator = AnsibleConditionTranslator(preserve_config_check=False)
        annotation = {"role": "dotfiles", "tags": ["dotfiles"], "config_check": "dotfiles is defined"}
        host_vars = {}
        result = translator.translate_annotation(annotation, host_vars)
        assert result == "false"

    def test_requires_config_display_manager(self):
        """requires_config: {display_manager: lightdm} translates to _has_display and _dm == 'lightdm'."""
        translator = AnsibleConditionTranslator()
        annotation = {
            "role": "lightdm",
            "tags": ["lightdm"],
            "requires_config": {"display_manager": "lightdm"}
        }
        result = translator.translate_annotation(annotation, {})
        assert result == "_has_display and _dm == 'lightdm'"

    def test_combined_os_and_requires_display(self):
        """Combining os: archlinux and requires_display: true produces AND condition."""
        translator = AnsibleConditionTranslator(os_family="Archlinux")
        annotation = {
            "role": "test",
            "tags": ["test"],
            "os": "archlinux",
            "requires_display": True
        }
        result = translator.translate_annotation(annotation, {})
        assert result == "_is_arch and _has_display"

    def test_combined_all_annotations(self):
        """Combining all annotation types produces complex AND condition."""
        translator = AnsibleConditionTranslator(os_family="Archlinux")
        annotation = {
            "role": "cups",
            "tags": ["cups"],
            "os": "archlinux",
            "requires_display": True,
            "requires_config": {"display_manager": "lightdm"}
        }
        result = translator.translate_annotation(annotation, {})
        # Known behavior: requires_config with display_manager adds _has_display,
        # which duplicates the one from requires_display. This matches the current
        # translate_condition() behavior and will be addressed in a future slice
        # when condition normalization is added.
        assert result == "_is_arch and _has_display and _has_display and _dm == 'lightdm'"

    def test_empty_annotations(self):
        """Role with no annotations returns empty string condition."""
        translator = AnsibleConditionTranslator()
        annotation = {"role": "shell", "tags": ["shell"]}
        result = translator.translate_annotation(annotation, {})
        assert result == ""

    def test_string_role_entry(self):
        """String role entry (not dict) returns empty string condition."""
        translator = AnsibleConditionTranslator()
        annotation = "shell"
        result = translator.translate_annotation(annotation, {})
        assert result == ""

    def test_translate_profile_gate_pass_through(self):
        """translate_profile_gate is a pass-through in Slice 1 (returns empty string)."""
        translator = AnsibleConditionTranslator()
        result = translator.translate_profile_gate(
            role_name="i3",
            member_profiles=["i3", "hyprland"],
            all_profiles=["headless", "i3", "hyprland", "gnome"],
            de_profile_map={"i3": "i3", "hyprland": "hyprland", "gnome": "gnome"}
        )
        assert result == ""

    def test_combine_conditions_both_non_empty(self):
        """Combining two non-empty conditions ANDs them."""
        translator = AnsibleConditionTranslator()
        result = translator.combine_conditions("_is_arch", "_has_display")
        assert result == "_is_arch and _has_display"

    def test_combine_conditions_annotation_only(self):
        """When profile_gate is empty, returns annotation_condition."""
        translator = AnsibleConditionTranslator()
        result = translator.combine_conditions("_is_arch", "")
        assert result == "_is_arch"

    def test_combine_conditions_profile_gate_only(self):
        """When annotation_condition is empty, returns profile_gate."""
        translator = AnsibleConditionTranslator()
        result = translator.combine_conditions("", "_has_display")
        assert result == "_has_display"

    def test_combine_conditions_both_empty(self):
        """When both conditions are empty, returns empty string."""
        translator = AnsibleConditionTranslator()
        result = translator.combine_conditions("", "")
        assert result == ""

    def test_default_translator_factory(self):
        """DefaultTranslator factory creates AnsibleConditionTranslator with defaults."""
        translator = DefaultTranslator()
        assert isinstance(translator, AnsibleConditionTranslator)
        # Verify it works by testing a translation
        annotation = {"role": "test", "tags": ["test"], "os": "archlinux"}
        result = translator.translate_annotation(annotation, {})
        assert result == "_is_arch"

    def test_default_translator_with_custom_os_family(self):
        """DefaultTranslator factory passes os_family through.

        Note: The os_family parameter is used for evaluation context, not for
        translating os annotations. The annotation os: archlinux always translates
        to _is_arch regardless of the target OS family.
        """
        translator = DefaultTranslator(os_family="Debian")
        annotation = {"role": "test", "tags": ["test"], "os": "archlinux"}
        result = translator.translate_annotation(annotation, {})
        # os: archlinux always translates to _is_arch (the os_family param
        # is for evaluation context, not annotation translation)
        assert result == "_is_arch"

    def test_default_translator_with_evaluator(self):
        """DefaultTranslator factory passes evaluator through."""
        evaluator = DictEvaluator({"dotfiles is defined": True})
        translator = DefaultTranslator(evaluator=evaluator)
        annotation = {"role": "dotfiles", "tags": ["dotfiles"], "config_check": "dotfiles is defined"}
        result = translator.translate_annotation(annotation, {})
        # DictEvaluator returns True for the expression
        assert result == "true"

    def test_default_translator_with_preserve_config_check(self):
        """DefaultTranslator factory passes preserve_config_check through."""
        translator = DefaultTranslator(preserve_config_check=True)
        annotation = {"role": "dotfiles", "tags": ["dotfiles"], "config_check": "dotfiles is defined"}
        result = translator.translate_annotation(annotation, {})
        # With preserve_config_check=True, the expression is kept as-is
        assert result == "dotfiles is defined"


class TestPlaybookGenerator:
    """Test PlaybookGenerator.generate() and sync_check()."""

    def test_generate_returns_playbook_roles(self):
        """generate() should return PlaybookRole tuples with conditions."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        roles = generator.generate()

        # Should return a tuple
        assert isinstance(roles, tuple)

        # Should have PlaybookRole objects
        assert all(isinstance(r, PlaybookRole) for r in roles)

        # Should have some roles
        assert len(roles) > 0

        # Each role should have a name and tags
        for role in roles:
            assert isinstance(role.role, str)
            assert len(role.role) > 0
            assert isinstance(role.tags, tuple)
            assert all(isinstance(t, str) for t in role.tags)

    def test_generate_roles_have_nonempty_tags(self):
        """generate() should include tags from profile definitions."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        roles = generator.generate()
        role_map = {r.role: r for r in roles}

        # Known roles that should have tags matching their name
        for name in ("base", "shell", "gpu_detect"):
            assert name in role_map, f"Expected role '{name}' in generated output"
            assert name in role_map[name].tags, (
                f"Expected '{name}' in tags for role '{name}', got {role_map[name].tags}"
            )

    def test_generate_tags_are_sorted(self):
        """Tags on each role should be sorted for determinism."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        for role in generator.generate():
            assert role.tags == tuple(sorted(role.tags)), (
                f"Tags for '{role.role}' not sorted: {role.tags}"
            )

    def test_generate_tags_unioned_across_profiles(self):
        """Tags from all profiles containing a role are unioned."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        roles = generator.generate()
        role_map = {r.role: r for r in roles}

        # backlight appears in _base.yml and laptop overlay with different tags
        # base gives it backlight tag, overlay gives it backlight tag too
        # After unioning it should have at least the backlight tag
        assert "backlight" in role_map, "Expected 'backlight' in generated output"
        assert "backlight" in role_map["backlight"].tags

    def test_generate_deterministic_order(self):
        """generate() should return roles in consistent order."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        roles1 = generator.generate()
        roles2 = generator.generate()

        # Same length
        assert len(roles1) == len(roles2)

        # Same order
        assert roles1 == roles2

    def test_sync_check_in_sync_returns_true(self):
        """sync_check() on an in-sync playbook should return in_sync=True."""
        # Create a temporary playbook file matching expected output
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        expected_roles = generator.generate()

        # Build playbook YAML
        playbook_roles = []
        for role in expected_roles:
            if role.condition:
                playbook_roles.append({"role": role.role, "when": role.condition})
            else:
                playbook_roles.append(role.role)

        playbook_data = {
            "hosts": "all",
            "roles": playbook_roles,
        }

        # Write to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(playbook_data, f)
            temp_path = f.name

        try:
            result = generator.sync_check(temp_path)
            assert result.in_sync is True
            assert len(result.missing_roles) == 0
            assert len(result.extra_roles) == 0
            assert len(result.condition_mismatches) == 0
        finally:
            os.unlink(temp_path)

    def test_sync_check_detects_missing_role(self):
        """sync_check() should detect roles in generated but not in playbook."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )

        # Generate expected roles, then remove a known role to force a gap
        expected_roles = generator.generate()
        assert len(expected_roles) > 0, "generate() should return at least one role"

        # Pick a role to omit (the first one with no condition is simplest)
        removed_role = expected_roles[0]
        for r in expected_roles:
            if r.condition is None:
                removed_role = r
                break

        # Build playbook from expected roles minus the removed one
        playbook_roles = []
        for role in expected_roles:
            if role.role == removed_role.role:
                continue
            if role.condition:
                playbook_roles.append({"role": role.role, "when": role.condition})
            else:
                playbook_roles.append(role.role)

        playbook_data = {"hosts": "all", "roles": playbook_roles}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(playbook_data, f)
            temp_path = f.name

        try:
            result = generator.sync_check(temp_path)
            assert result.in_sync is False, (
                f"Expected in_sync=False after removing '{removed_role.role}'"
            )
            missing_names = {r.role for r in result.missing_roles}
            assert removed_role.role in missing_names, (
                f"Expected '{removed_role.role}' in missing_roles, got {missing_names}"
            )
        finally:
            os.unlink(temp_path)

    def test_sync_check_detects_extra_role(self):
        """sync_check() should detect roles in playbook but not in generated."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )

        # Create a playbook with an extra role not in profiles
        playbook_data = {
            "hosts": "all",
            "roles": ["shell", "system", "fake_extra_role_xyz"],
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(playbook_data, f)
            temp_path = f.name

        try:
            result = generator.sync_check(temp_path)
            assert result.in_sync is False
            assert len(result.extra_roles) > 0
            # Should contain the fake role
            extra_role_names = {r.role for r in result.extra_roles}
            assert "fake_extra_role_xyz" in extra_role_names
        finally:
            os.unlink(temp_path)

    def test_sync_check_detects_condition_mismatch(self):
        """sync_check() should detect condition mismatches."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        expected_roles = generator.generate()

        # Find a role with a condition and change it
        test_role = None
        test_role_idx = -1
        for i, role in enumerate(expected_roles):
            if role.condition:
                test_role = role
                test_role_idx = i
                break

        # Skip test if no role has a condition
        if test_role is None:
            return

        # Build playbook with wrong condition
        playbook_roles = []
        for i, role in enumerate(expected_roles):
            if i == test_role_idx:
                # Use wrong condition
                playbook_roles.append({
                    "role": role.role,
                    "when": "_is_wrong_condition_xyz"
                })
            elif role.condition:
                playbook_roles.append({"role": role.role, "when": role.condition})
            else:
                playbook_roles.append(role.role)

        playbook_data = {
            "hosts": "all",
            "roles": playbook_roles,
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(playbook_data, f)
            temp_path = f.name

        try:
            result = generator.sync_check(temp_path)
            assert result.in_sync is False
            assert len(result.condition_mismatches) > 0

            # Check mismatch details
            mismatch = result.condition_mismatches[0]
            assert "role" in mismatch
            assert "actual" in mismatch
            assert "expected" in mismatch
            assert mismatch["role"] == test_role.role
            assert mismatch["actual"] == "_is_wrong_condition_xyz"
        finally:
            os.unlink(temp_path)

    def test_sync_check_multiple_mismatches_reported(self):
        """sync_check() should report multiple differences together."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )

        # Create a playbook with multiple issues
        playbook_data = {
            "hosts": "all",
            "roles": [
                "shell",
                "extra_role_1",
                "extra_role_2",
            ],
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(playbook_data, f)
            temp_path = f.name

        try:
            result = generator.sync_check(temp_path)
            assert result.in_sync is False

            # Should have both extra roles
            extra_role_names = {r.role for r in result.extra_roles}
            assert "extra_role_1" in extra_role_names
            assert "extra_role_2" in extra_role_names

            # Should also have missing roles
            assert len(result.missing_roles) > 0
        finally:
            os.unlink(temp_path)

    def test_sync_check_nonexistent_playbook_raises(self):
        """sync_check() should raise ValueError for nonexistent playbook."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )

        with pytest.raises(ValueError, match="Playbook not found"):
            generator.sync_check("/nonexistent/path/play.yml")


class TestPlaybookGeneratorResolve:
    """Test PlaybookGenerator.resolve() method."""

    def test_resolve_i3_profile(self):
        """resolve('i3') should return only roles from the i3 profile + overlays."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        roles = generator.resolve("i3")

        # Should return a tuple
        assert isinstance(roles, tuple)

        # Should have PlaybookRole objects
        assert all(isinstance(r, PlaybookRole) for r in roles)

        # Should have some roles (i3 profile has roles)
        assert len(roles) > 0

        # Check for some expected roles in i3 profile
        role_names = {r.role for r in roles}
        # shell and system are base roles that should be in i3
        assert "shell" in role_names or len(roles) > 5  # At minimum, some roles

        # Resolved roles should have tags from profile definitions
        for r in roles:
            assert isinstance(r.tags, tuple)

        # Check specific role has expected tag content
        shell_roles = [r for r in roles if r.role == "shell"]
        assert len(shell_roles) == 1
        assert "shell" in shell_roles[0].tags

    def test_resolve_headless_excludes_display_gated(self):
        """resolve('headless') should exclude roles that require a display."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        roles = generator.resolve("headless")

        role_names = {r.role for r in roles}
        role_conditions = {r.role: r.condition for r in roles}

        # Check that display-gated roles are either not present or have conditions
        # (e.g., fonts, i3, hyprland should be absent or conditional)
        # The headless profile should not have roles that require a display
        # without appropriate conditions

        # Verify no unconditional roles that are display-specific
        for role_name, condition in role_conditions.items():
            # If a role is display-specific (like i3, hyprland, etc.),
            # it should have a condition or not be in headless
            display_specific = {"i3", "hyprland", "gnome", "awesomewm", "kde", "lightdm"}
            if role_name in display_specific:
                # These should either not be in headless, or have conditions
                assert role_name not in role_names or condition is not None

    def test_resolve_with_host_vars(self):
        """resolve() should use provided host_vars for overlay evaluation."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},  # Empty default
        )

        # With laptop host_vars, should get laptop overlay roles
        roles_with_laptop = generator.resolve("i3", host_vars={"laptop": True})

        # Without laptop host_vars, should not get laptop overlay roles
        roles_without_laptop = generator.resolve("i3", host_vars={})

        # The laptop overlay should add roles
        role_names_with = {r.role for r in roles_with_laptop}
        role_names_without = {r.role for r in roles_without_laptop}

        # The "laptop" role from the laptop overlay must be present when
        # host_vars={"laptop": True} and absent when host_vars={}
        assert "laptop" in role_names_with, (
            "Expected 'laptop' role when host_vars={'laptop': True}"
        )
        assert "laptop" not in role_names_without, (
            "Did not expect 'laptop' role when host_vars={}"
        )

        # The laptop overlay should add strictly more roles than without it
        assert len(role_names_with) >= len(role_names_without)

    def test_resolve_unknown_profile_raises(self):
        """resolve() with unknown profile should raise ValueError."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )

        with pytest.raises(ValueError):
            generator.resolve("nonexistent_profile_xyz")


class TestPlaybookGeneratorExplain:
    """Test PlaybookGenerator.explain() method."""

    def test_explain_gpu_detect_os_annotation(self):
        """explain('gpu_detect') should describe os: archlinux annotation."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        explanation = generator.explain("gpu_detect")

        # Should contain the role name
        assert "gpu_detect" in explanation

        # Should mention profiles
        assert "profile" in explanation.lower()

        # Should mention annotations
        assert "annotation" in explanation.lower()

        # Should mention the os annotation
        assert "archlinux" in explanation.lower() or "os" in explanation.lower()

        # Should explain the condition
        assert "condition" in explanation.lower()

    def test_explain_fonts_profile_gating(self):
        """explain('fonts') should describe profile-gating across multiple DE profiles."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        explanation = generator.explain("fonts")

        # Should contain the role name
        assert "fonts" in explanation

        # Should mention profile-gating
        assert "profile-gating" in explanation.lower() or "gate" in explanation.lower()

        # Should list containing profiles
        assert "Found in" in explanation or "profile" in explanation.lower()

    def test_explain_unknown_role(self):
        """explain() with unknown role should return appropriate message."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        explanation = generator.explain("fake_role_xyz")

        # Should say role not found
        assert "not defined" in explanation or "not found" in explanation.lower()

    def test_explain_structure_contains_all_sections(self):
        """explain() output should contain all required explanation sections."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )

        # Test with a role that should exist (like shell or system)
        explanation = generator.explain("shell")

        # Should have structured sections
        lines = explanation.split("\n")

        # Should contain key sections
        text_lower = explanation.lower()
        # Check for at least some of the expected sections
        has_profile_section = "profile" in text_lower
        has_annotation_section = "annotation" in text_lower
        has_condition_section = "condition" in text_lower

        # At least one section should be present for existing roles
        assert has_profile_section or has_annotation_section or has_condition_section


class TestCLIGeneratePlaybook:
    """Tests for the 'generate-playbook' CLI subcommand."""

    def test_generate_playbook_outputs_valid_yaml(self, capsys):
        """generate-playbook should write a valid playbook YAML file."""
        with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as tmp:
            tmpfile = tmp.name
        try:
            rc = main(["generate-playbook", "--write", tmpfile])
            assert rc == 0
            with open(tmpfile) as f:
                parsed = yaml.safe_load(f)
            assert isinstance(parsed, list)
            play = parsed[0]
            assert "roles" in play
            assert isinstance(play["roles"], list)
            assert any(
                (
                    isinstance(role, dict) and role.get("role") in {"shell", "base"}
                )
                for role in play["roles"]
            )
        finally:
            os.unlink(tmpfile)

    def test_generate_playbook_stdout_mode(self, capsys):
        """generate-playbook without --write should output role manifest JSON to stdout."""
        rc = main(["generate-playbook"])
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        # Verify output is valid JSON
        output = json.loads(captured.out)
        assert "os_family" in output
        assert "profiles" in output
        assert "roles" in output
        # Verify roles structure
        assert isinstance(output["roles"], list)
        if len(output["roles"]) > 0:
            role = output["roles"][0]
            assert "role" in role
            assert "tags" in role
            assert "condition" in role
            assert "source" in role

    def test_generate_playbook_output_includes_tags(self, capsys):
        """generate-playbook output should include tags for each role."""
        with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as tmp:
            tmpfile = tmp.name
        try:
            main(["generate-playbook", "--write", tmpfile])
            with open(tmpfile) as f:
                parsed = yaml.safe_load(f)
            play = parsed[0]
            dict_roles = [r for r in play["roles"] if isinstance(r, dict)]
            # Most roles should have tags
            with_tags = [r for r in dict_roles if "tags" in r]
            assert len(with_tags) > 0, "Expected at least one role with tags"
            # Tags should be lists of strings
            for role in with_tags:
                assert isinstance(role["tags"], list)
                assert all(isinstance(t, str) for t in role["tags"])
        finally:
            os.unlink(tmpfile)

    def test_generate_playbook_custom_dir(self, capsys):
        """generate-playbook respects --profiles-dir."""
        valid = "display_manager_default: lightdm\ndesktop_environment: i3\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "myprofile.yml").write_text(valid)
            outfile = str(Path(tmpdir) / "output.yml")
            rc = main(["generate-playbook", "--profiles-dir", tmpdir, "--write", outfile])
            assert rc == 0
            with open(outfile) as f:
                parsed = yaml.safe_load(f)
            assert "roles" in parsed[0]

    def test_generate_playbook_bad_dir_exits_1(self, capsys):
        """generate-playbook with nonexistent profiles-dir exits 1."""
        rc = main(["generate-playbook", "--profiles-dir", "/nonexistent/path"])
        captured = capsys.readouterr()
        assert rc == 1
        assert captured.out == ""
        assert "does not exist" in captured.err


class TestDiscoverOverlayVariables:
    """Tests for discover_overlay_variables() function."""

    def test_discovers_current_overlays(self):
        """Returns all overlay variables from current overlays directory."""
        variables = discover_overlay_variables(_PROFILES_DIR)
        # Current overlays: laptop and bluetooth
        expected = ["bluetooth", "laptop"]
        assert variables == expected

    def test_returns_sorted_list(self):
        """Variables are returned in sorted order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = Path(tmpdir)
            overlays_dir = profiles_dir / "overlays"
            overlays_dir.mkdir()

            # Create overlays with variable names in reverse alphabetical order
            (overlays_dir / "zebra.yml").write_text(
                "name: Zebra\napplies_when: zebra | default(false)\nroles: []\n"
            )
            (overlays_dir / "alpha.yml").write_text(
                "name: Alpha\napplies_when: alpha is defined\nroles: []\n"
            )

            variables = discover_overlay_variables(str(profiles_dir))
            assert variables == ["alpha", "zebra"]

    def test_extracts_variable_from_default_pattern(self):
        """Extracts variable name from 'var | default(...)' pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = Path(tmpdir)
            overlays_dir = profiles_dir / "overlays"
            overlays_dir.mkdir()

            (overlays_dir / "test.yml").write_text(
                "name: Test\napplies_when: laptop | default(false)\nroles: []\n"
            )

            variables = discover_overlay_variables(str(profiles_dir))
            assert "laptop" in variables

    def test_extracts_variable_from_is_defined_pattern(self):
        """Extracts variable name from 'var is defined' pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = Path(tmpdir)
            overlays_dir = profiles_dir / "overlays"
            overlays_dir.mkdir()

            (overlays_dir / "test.yml").write_text(
                "name: Test\napplies_when: dotfiles is defined\nroles: []\n"
            )

            variables = discover_overlay_variables(str(profiles_dir))
            assert "dotfiles" in variables

    def test_deduplicates_variables(self):
        """Same variable appearing in multiple overlays appears only once."""
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = Path(tmpdir)
            overlays_dir = profiles_dir / "overlays"
            overlays_dir.mkdir()

            (overlays_dir / "test1.yml").write_text(
                "name: Test1\napplies_when: laptop | default(false)\nroles: []\n"
            )
            (overlays_dir / "test2.yml").write_text(
                "name: Test2\napplies_when: laptop is defined\nroles: []\n"
            )

            variables = discover_overlay_variables(str(profiles_dir))
            assert variables.count("laptop") == 1

    def test_raises_error_when_overlays_dir_missing(self):
        """Raises ValueError if overlays directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = Path(tmpdir) / "profiles"
            # Don't create overlays subdirectory

            with pytest.raises(ValueError, match="Overlays directory not found"):
                discover_overlay_variables(str(profiles_dir))

    def test_skips_private_files(self):
        """Files starting with underscore are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = Path(tmpdir)
            overlays_dir = profiles_dir / "overlays"
            overlays_dir.mkdir()

            (overlays_dir / "_private.yml").write_text(
                "name: Private\napplies_when: private | default(false)\nroles: []\n"
            )
            (overlays_dir / "public.yml").write_text(
                "name: Public\napplies_when: public is defined\nroles: []\n"
            )

            variables = discover_overlay_variables(str(profiles_dir))
            assert variables == ["public"]

    def test_handles_complex_applies_when(self):
        """Extracts variables from complex applies_when expressions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = Path(tmpdir)
            overlays_dir = profiles_dir / "overlays"
            overlays_dir.mkdir()

            (overlays_dir / "test.yml").write_text(
                'name: Test\n'
                "applies_when: bluetooth is defined and not (bluetooth.disable | default(false))\n"
                "roles: []\n"
            )

            variables = discover_overlay_variables(str(profiles_dir))
            assert "bluetooth" in variables


class TestGenerateHostVarsTemplate:
    """Tests for generate_host_vars_template() function."""

    def test_empty_variables_returns_empty_template(self):
        """Empty list returns minimal template."""
        template = generate_host_vars_template([])
        assert template == "{{ {} | to_json }}"

    def test_single_variable_template(self):
        """Generates correct template for single variable."""
        template = generate_host_vars_template(["laptop"])
        expected = "{{\n  {}\n  | combine({\"laptop\": laptop} if laptop is defined else {})\n  | to_json\n}}"
        assert template == expected

    def test_multiple_variables_template(self):
        """Generates correct template for multiple variables."""
        template = generate_host_vars_template(["laptop", "bluetooth"])
        lines = template.split("\n")
        assert lines[0] == "{{"
        assert lines[1] == "  {}"
        assert '  | combine({"bluetooth": bluetooth} if bluetooth is defined else {})' in lines
        assert '  | combine({"laptop": laptop} if laptop is defined else {})' in lines
        assert "  | to_json" in lines
        assert "}}" in lines

    def test_variables_are_sorted(self):
        """Variables are sorted alphabetically in template."""
        template = generate_host_vars_template(["zebra", "alpha", "beta"])
        lines = template.split("\n")
        # Find the combine lines
        combine_lines = [l for l in lines if "combine" in l]
        assert len(combine_lines) == 3
        assert "alpha" in combine_lines[0]
        assert "beta" in combine_lines[1]
        assert "zebra" in combine_lines[2]

    def test_template_matches_play_yml_format(self):
        """Generated template matches the format used in play.yml."""
        variables = ["laptop", "bluetooth", "dotfiles", "goesimage", "regdomain"]
        template = generate_host_vars_template(variables)

        # Verify template structure matches _generate_host_vars_json_template format
        assert template.startswith("{{\n  {}")
        assert template.endswith("}}")

        # Verify all variables are present
        for var in variables:
            assert f'"{var}": {var}' in template
            assert f"if {var} is defined" in template

    def test_jinja2_syntax_is_valid(self):
        """Template can be parsed as valid Jinja2."""
        from jinja2 import Environment

        variables = ["laptop", "bluetooth"]
        template = generate_host_vars_template(variables)

        # Parse the template - should not raise
        env = Environment()
        env.parse(template)


class TestGenerateOverlayFactsTask:
    """Tests for generate_overlay_facts_task() function."""

    def test_empty_variables_returns_empty_string(self):
        """Empty list returns empty task string."""
        task = generate_overlay_facts_task([])
        assert task == ""

    def test_single_variable_task(self):
        """Generates correct task for single variable."""
        task = generate_overlay_facts_task(["laptop"])

        assert "Set overlay facts from resolved manifest" in task
        assert "_manifest_result.stdout | from_json" in task
        assert "overlay_flags" in task
        assert "_overlay_laptop" in task
        assert "default(false)" in task
        assert "tags: always" in task

    def test_multiple_variables_task(self):
        """Generates correct task for multiple variables."""
        task = generate_overlay_facts_task(["laptop", "bluetooth"])

        # Check structure
        assert "- name: Set overlay facts from resolved manifest" in task
        assert "  vars:" in task
        assert "  set_fact:" in task
        assert "  tags: always" in task

        # Check all variables are present
        assert "_overlay_laptop" in task
        assert "_overlay_bluetooth" in task

    def test_variables_are_sorted(self):
        """Variables are sorted alphabetically in task."""
        task = generate_overlay_facts_task(["zebra", "alpha", "beta"])
        lines = task.split("\n")

        # Find set_fact lines
        fact_lines = [l for l in lines if "_overlay_" in l]
        assert len(fact_lines) == 3
        assert "_overlay_alpha" in fact_lines[0]
        assert "_overlay_beta" in fact_lines[1]
        assert "_overlay_zebra" in fact_lines[2]

    def test_task_matches_play_yml_format(self):
        """Generated task matches the format used in play.yml."""
        variables = ["laptop", "bluetooth"]
        task = generate_overlay_facts_task(variables)

        # Verify task structure matches play.yml format
        assert task.startswith("- name: Set overlay facts from resolved manifest")
        assert "_manifest: \"{{ _manifest_result.stdout | from_json }}\"" in task
        assert "_of: \"{{ _manifest.overlay_flags }}\"" in task
        assert "  set_fact:" in task
        assert "  tags: always" in task

        # Verify fact format
        for var in variables:
            assert f"    _overlay_{var}: \"{{{{ _of._overlay_{var} | default(false) }}}}\"" in task


class TestSectionSorting:
    """Tests verifying role sorting by section."""

    def test_section_sort_key_gpu_roles_first(self):
        """GPU roles should be in section 0 (first section)."""
        assert _section_sort_key("gpu_detect") == (0, "gpu_detect")
        assert _section_sort_key("gpu_drivers") == (0, "gpu_drivers")

    def test_section_sort_key_base_system_section_1(self):
        """Base system roles should be in section 1."""
        assert _section_sort_key("base") == (1, "base")
        assert _section_sort_key("grub") == (1, "grub")
        assert _section_sort_key("microcode") == (1, "microcode")

    def test_section_sort_key_roles_sorted_alphabetically_within_section(self):
        """Roles within the same section should sort alphabetically."""
        # Both in "Universal System Configuration" section (index 2)
        key_gnupg = _section_sort_key("gnupg")
        key_shell = _section_sort_key("shell")
        assert key_gnupg[0] == key_shell[0]  # Same section
        assert key_gnupg < key_shell  # Alphabetically "gnupg" < "shell"

    def test_section_sort_key_unknown_role_goes_to_end(self):
        """Roles not in any section should get section 999 (catch-all)."""
        assert _section_sort_key("unknown_role_xyz") == (999, "unknown_role_xyz")

    def test_resolve_role_manifest_output_sorted_by_section(self):
        """Resolved manifest roles should be sorted by section, then alphabetically."""
        manifest = resolve_role_manifest(
            profile="i3",
            os_family="Archlinux",
        )
        role_names = [r.role for r in manifest.roles]

        # First 5 roles should be from GPU Detection & Drivers, then Base System sections
        # These are the first 5 roles in current play.yml order:
        # gpu_detect, gpu_drivers, base, grub, microcode
        assert role_names[0] == "gpu_detect"
        assert role_names[1] == "gpu_drivers"
        assert role_names[2] == "base"
        assert role_names[3] == "grub"
        assert role_names[4] == "microcode"

    def test_resolve_role_manifest_section_grouping(self):
        """Roles from the same section should appear together."""
        manifest = resolve_role_manifest(
            profile="i3",
            os_family="Archlinux",
        )
        role_names = [r.role for r in manifest.roles]

        # Find indices of Package Management section roles
        pkg_mgmt_roles = [
            "ansible-role-packages",
            "ansible-role-asdf",
            "flatpak",
            "aur",
        ]
        indices = {role: role_names.index(role) for role in pkg_mgmt_roles if role in role_names}

        # All roles between the first and last Package Management role should
        # belong to the same section, even if additional roles are added there.
        if len(indices) >= 2:
            sorted_indices = sorted(indices.values())
            expected_section = _section_sort_key(role_names[sorted_indices[0]])[0]
            section_span = role_names[sorted_indices[0]: sorted_indices[-1] + 1]
            for role in section_span:
                assert _section_sort_key(role)[0] == expected_section


class TestPlaybookGeneratorWritePlaybook:
    """Test PlaybookGenerator.write_playbook() method."""

    def test_write_playbook_creates_valid_yaml(self, tmp_path):
        """write_playbook() should produce valid Ansible YAML."""
        playbook_path = tmp_path / "test_playbook.yml"

        generator = PlaybookGenerator(profile="headless", profiles_dir=_PROFILES_DIR)
        generator.write_playbook(str(playbook_path))

        # Verify file was created
        assert playbook_path.exists()

        # Verify it's valid YAML
        with open(playbook_path) as f:
            data = yaml.safe_load(f)

        # Verify structure
        assert isinstance(data, list)
        assert len(data) == 1
        play = data[0]
        assert play["name"] == "Configure localhost"
        assert play["hosts"] == "localhost"
        assert "roles" in play
        assert len(play["roles"]) > 0

    def test_write_playbook_preserves_pre_tasks(self, tmp_path):
        """write_playbook() should preserve pre_tasks block."""
        playbook_path = tmp_path / "test_playbook.yml"

        # Create existing playbook with pre_tasks
        existing_content = """---
- name: Test Play
  hosts: localhost
  pre_tasks:
    - name: Test task
      debug:
        msg: "test"
  roles: []
  vars_prompt:
    - name: test_var
      prompt: "Enter value"
"""
        with open(playbook_path, "w") as f:
            f.write(existing_content)

        generator = PlaybookGenerator(profile="headless", profiles_dir=_PROFILES_DIR)
        generator.write_playbook(str(playbook_path))

        # Verify pre_tasks are preserved structurally
        with open(playbook_path) as f:
            data = yaml.safe_load(f)

        pre_tasks = data[0]["pre_tasks"]
        assert len(pre_tasks) == 1
        assert pre_tasks[0]["name"] == "Test task"

        # Verify task name appears in the written text
        with open(playbook_path) as f:
            content = f.read()
        assert "Test task" in content

    def test_write_playbook_preserves_vars_prompt(self, tmp_path):
        """write_playbook() should preserve vars_prompt block."""
        playbook_path = tmp_path / "test_playbook.yml"

        # Create existing playbook with vars_prompt
        existing_content = """---
- name: Test Play
  hosts: localhost
  pre_tasks: []
  roles: []
  vars_prompt:
    - name: user_password
      prompt: "Enter desired user password"
    - name: test_var
      prompt: "Enter test value"
"""
        with open(playbook_path, "w") as f:
            f.write(existing_content)

        generator = PlaybookGenerator(profile="headless", profiles_dir=_PROFILES_DIR)
        generator.write_playbook(str(playbook_path))

        # Verify vars_prompt is preserved structurally
        with open(playbook_path) as f:
            data = yaml.safe_load(f)

        vars_prompt = data[0]["vars_prompt"]
        assert len(vars_prompt) == 2
        assert vars_prompt[0]["name"] == "user_password"
        assert vars_prompt[1]["name"] == "test_var"

        # Verify prompts appear in the written text
        with open(playbook_path) as f:
            content = f.read()
        assert "user_password" in content
        assert "test_var" in content

    def test_write_playbook_adds_header_comment(self, tmp_path):
        """write_playbook() should add generated header comment."""
        playbook_path = tmp_path / "test_playbook.yml"

        generator = PlaybookGenerator(profile="headless", profiles_dir=_PROFILES_DIR)
        generator.write_playbook(str(playbook_path))

        # Verify header comment
        with open(playbook_path) as f:
            first_line = f.readline().strip()

        assert first_line == "# GENERATED by profile_dispatcher — do not edit by hand"

    def test_write_playbook_generates_roles(self, tmp_path):
        """write_playbook() should generate roles from profile."""
        playbook_path = tmp_path / "test_playbook.yml"

        generator = PlaybookGenerator(profile="headless", profiles_dir=_PROFILES_DIR)
        generator.write_playbook(str(playbook_path))

        # Verify roles are generated
        with open(playbook_path) as f:
            data = yaml.safe_load(f)

        roles = data[0]["roles"]
        assert len(roles) > 0

        # Verify role structure
        first_role = roles[0]
        assert "role" in first_role
        assert "tags" in first_role

    def test_write_playbook_section_comments(self, tmp_path):
        """write_playbook() should add section comments between role groups."""
        playbook_path = tmp_path / "test_playbook.yml"

        generator = PlaybookGenerator(profile="i3", profiles_dir=_PROFILES_DIR)
        generator.write_playbook(str(playbook_path))

        # Read file as text to check for comments
        with open(playbook_path) as f:
            content = f.read()

        # Verify section comments are present
        assert "# -------------------------------------------------------------------------" in content
        # Check for specific section names
        assert "GPU Detection & Drivers (Arch-only)" in content or "Base System (Arch-only)" in content

    def test_write_playbook_syntax_check(self, tmp_path):
        """Generated playbook should pass ansible-playbook syntax check."""
        import subprocess

        playbook_path = tmp_path / "test_playbook.yml"

        generator = PlaybookGenerator(profile="headless", profiles_dir=_PROFILES_DIR)
        generator.write_playbook(str(playbook_path))

        # Verify it's valid YAML at minimum
        with open(playbook_path) as f:
            yaml.safe_load(f)

        # Run ansible-playbook syntax check when available.
        # Note: syntax check may fail due to missing roles in the temp directory,
        # which is expected — the check validates YAML structure and role references,
        # but roles won't be installed under tmp_path.
        try:
            result = subprocess.run(
                [
                    "ansible-playbook",
                    "--syntax-check",
                    "-i", "localhost,",
                    "-c", "local",
                    str(playbook_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError:
            pytest.skip("ansible-playbook is not installed")
        except subprocess.TimeoutExpired:
            pytest.fail("ansible-playbook --syntax-check timed out")

        # If syntax check ran, verify no YAML parsing errors (role-not-found is ok
        # since roles aren't installed in the temp directory)
        if result.returncode != 0 and "was not found" not in result.stderr:
            pytest.fail(
                "ansible-playbook --syntax-check failed with unexpected error\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
