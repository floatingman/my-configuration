#!/usr/bin/env python3
"""
Test suite for profile_dispatcher module.

Comprehensive unit tests covering all input combinations and edge cases.
No Ansible dependency - pure Python tests.
"""

import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts directory to path so profile_dispatcher can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profile_dispatcher import (
    resolve,
    load_profile,
    validate_profile,
    list_profiles,
    ResolvedProfile,
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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
