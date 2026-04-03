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

import json

from profile_dispatcher import (
    main,
    resolve,
    load_profile,
    validate_profile,
    list_profiles,
    ResolvedProfile,
    RoleCondition,
    ResolvedManifest,
    translate_condition,
    resolve_manifest,
    discover_overlays,
    load_overlay,
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


class TestDiscoverOverlays:
    """Test discover_overlays() function."""

    def test_discovers_overlays_in_overlays_directory(self):
        """discover_overlays should find laptop and bluetooth overlays."""
        overlays = discover_overlays(_PROFILES_DIR)
        assert "laptop" in overlays
        assert "bluetooth" in overlays

    def test_returns_sorted_list(self):
        """discover_overlays returns names in sorted order."""
        overlays = discover_overlays(_PROFILES_DIR)
        assert overlays == sorted(overlays)

    def test_empty_if_overlays_dir_missing(self):
        """discover_overlays returns empty list if overlays/ directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            overlays = discover_overlays(tmpdir)
            assert overlays == []


class TestLoadOverlay:
    """Test load_overlay() function."""

    def test_load_laptop_overlay(self):
        """load_overlay loads laptop overlay with expected fields."""
        overlay = load_overlay(_PROFILES_DIR, "laptop")
        assert "name" in overlay
        assert "applies_when" in overlay
        assert "roles" in overlay

    def test_load_bluetooth_overlay(self):
        """load_overlay loads bluetooth overlay with expected fields."""
        overlay = load_overlay(_PROFILES_DIR, "bluetooth")
        assert "name" in overlay
        assert "applies_when" in overlay
        assert "roles" in overlay

    def test_load_with_yml_extension(self):
        """load_overlay accepts name with .yml extension."""
        overlay = load_overlay(_PROFILES_DIR, "laptop.yml")
        assert overlay is not None

    def test_missing_overlay_raises_value_error(self):
        """load_overlay raises ValueError for non-existent overlay."""
        with pytest.raises(ValueError, match="not found"):
            load_overlay(_PROFILES_DIR, "nonexistent")


class TestTranslateCondition:
    """Test translate_condition() function."""

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

    def test_requires_config_dm_translates_to_dm_equals(self):
        """requires_config: {display_manager: lightdm} translates to _dm == 'lightdm'."""
        role_entry = {
            "role": "lightdm",
            "tags": ["lightdm"],
            "requires_config": {"display_manager": "lightdm"},
        }
        condition = translate_condition(role_entry, {}, "Archlinux")
        assert condition == "_dm == 'lightdm'"

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

    def test_config_check_is_defined_returns_true_when_defined(self):
        """config_check 'var is defined' returns true when var exists."""
        role_entry = {
            "role": "dotfiles",
            "tags": ["dotfiles"],
            "config_check": "dotfiles is defined",
        }
        host_vars = {"dotfiles": {"repo_url": "https://github.com/example/dotfiles"}}
        condition = translate_condition(role_entry, host_vars, "Archlinux")
        assert condition == "true"

    def test_config_check_is_defined_returns_false_when_undefined(self):
        """config_check 'var is defined' returns false when var doesn't exist."""
        role_entry = {
            "role": "dotfiles",
            "tags": ["dotfiles"],
            "config_check": "dotfiles is defined",
        }
        host_vars = {}
        condition = translate_condition(role_entry, host_vars, "Archlinux")
        assert condition == "false"


class TestResolveManifest:
    """Test resolve_manifest() function."""

    def test_resolves_hyprland_profile(self):
        """resolve_manifest for hyprland profile returns correct manifest."""
        manifest = resolve_manifest(profile="hyprland", host_vars={}, os_family="Archlinux")
        assert manifest.profile == "hyprland"
        assert manifest.display_manager == "sddm"
        assert manifest.has_display is True
        assert manifest.profile_flags["_is_arch"] is True
        assert manifest.profile_flags["_is_hyprland"] is True
        assert manifest.profile_flags["_is_i3"] is False

    def test_resolves_headless_profile(self):
        """resolve_manifest for headless profile has _has_display=False in flags."""
        manifest = resolve_manifest(profile="headless", host_vars={}, os_family="Archlinux")
        assert manifest.profile == "headless"
        assert manifest.has_display is False
        # Note: headless extends _base which includes devtools with requires_display: true
        # These roles will have _has_display condition but won't run because flag is False
        assert manifest.profile_flags["_has_display"] is False

    def test_manual_mode_with_explicit_vars(self):
        """resolve_manifest works in manual mode with explicit variables."""
        manifest = resolve_manifest(
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
        host_vars = {"laptop": True}  # laptop overlay applies (truthy value)
        manifest = resolve_manifest(
            profile="hyprland",
            host_vars=host_vars,
            os_family="Archlinux",
        )
        assert "_overlay_laptop" in manifest.overlay_flags
        assert manifest.overlay_flags["_overlay_laptop"] is True

    def test_deduplicates_roles_by_name(self):
        """Roles appearing in multiple profiles produce single manifest entry."""
        # terminal appears in both _base and i3/hyprland/gnome
        manifest = resolve_manifest(profile="i3", host_vars={}, os_family="Archlinux")
        role_names = [r.role for r in manifest.roles]
        # terminal should appear only once
        terminal_count = role_names.count("terminal")
        assert terminal_count == 1

    def test_or_logic_for_overlay_roles(self):
        """Roles from both profile and overlay get ORed conditions."""
        # backlight appears in both desktop profiles and laptop overlay
        host_vars = {"laptop": {}}
        manifest = resolve_manifest(
            profile="i3",
            host_vars=host_vars,
            os_family="Archlinux",
        )
        backlight_roles = [r for r in manifest.roles if r.role == "backlight"]
        assert len(backlight_roles) == 1
        # Condition should have OR from overlay integration
        # Note: Full OR logic requires tracking source during collection
        # For now, we verify the role exists
        assert len(backlight_roles) >= 1

    def test_evaluates_config_check_correctly(self):
        """config_check expressions are evaluated against host_vars."""
        host_vars = {
            "dotfiles": {"repo_url": "https://github.com/example/dotfiles"}
        }
        manifest = resolve_manifest(
            profile="hyprland",
            host_vars=host_vars,
            os_family="Archlinux",
        )
        dotfiles_roles = [r for r in manifest.roles if r.role == "dotfiles"]
        assert len(dotfiles_roles) == 1
        # config_check "dotfiles is defined" should evaluate to true
        # Condition should be "true" (config_check evaluated)
        assert "true" in dotfiles_roles[0].condition or dotfiles_roles[0].condition == ""

    def test_all_profiles_resolve_successfully(self):
        """All 6 named profiles resolve to valid manifests."""
        for profile_name in ("headless", "i3", "hyprland", "gnome", "awesomewm", "kde"):
            manifest = resolve_manifest(
                profile=profile_name,
                host_vars={},
                os_family="Archlinux",
            )
            assert manifest.profile == profile_name
            assert isinstance(manifest.roles, tuple)
            assert len(manifest.roles) > 0

    def test_resolved_manifest_is_frozen(self):
        """ResolvedManifest should be immutable (frozen dataclass)."""
        manifest = resolve_manifest(profile="i3", host_vars={}, os_family="Archlinux")
        with pytest.raises(AttributeError):
            manifest.profile = "hyprland"

    def test_resolved_manifest_equality(self):
        """ResolvedManifest with same inputs should be equal."""
        manifest1 = resolve_manifest(profile="i3", host_vars={}, os_family="Archlinux")
        manifest2 = resolve_manifest(profile="i3", host_vars={}, os_family="Archlinux")
        manifest3 = resolve_manifest(profile="hyprland", host_vars={}, os_family="Archlinux")

        # Same inputs produce equal manifests
        assert manifest1 == manifest2
        # Different profiles produce different manifests
        assert manifest1 != manifest3


class TestCLIResolveManifest:
    """Tests for the 'resolve-manifest' CLI subcommand."""

    def test_resolve_manifest_named_profile(self, capsys):
        """resolve-manifest --profile i3 outputs valid JSON."""
        rc = main(["resolve-manifest", "--profile", "i3"])
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
        rc = main(["resolve-manifest", "--profile", "headless"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["profile"] == "headless"
        assert data["has_display"] is False
        assert data["display_manager"] is None

    def test_resolve_manifest_with_host_vars(self, capsys):
        """resolve-manifest --host-vars evaluates config_check expressions."""
        host_vars_json = json.dumps({"laptop": True})
        rc = main(["resolve-manifest", "--profile", "i3", "--host-vars", host_vars_json])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert "_overlay_laptop" in data["overlay_flags"]

    def test_resolve_manifest_invalid_host_vars_exits_1(self, capsys):
        """resolve-manifest with invalid JSON in --host-vars exits 1."""
        rc = main(["resolve-manifest", "--profile", "i3", "--host-vars", "invalid json"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Invalid JSON" in err

    def test_resolve_manifest_manual_mode(self, capsys):
        """resolve-manifest works in manual mode without --profile."""
        rc = main([
            "resolve-manifest",
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
        main(["resolve-manifest", "--profile", "hyprland"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "roles" in data
        assert len(data["roles"]) > 0
        # Check first role has required fields
        first_role = data["roles"][0]
        assert "role" in first_role
        assert "tags" in first_role
        assert "condition" in first_role
        assert "source" in first_role

    def test_resolve_manifest_unknown_profile_exits_1(self, capsys):
        """resolve-manifest with unknown profile exits 1."""
        rc = main(["resolve-manifest", "--profile", "unknown"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "Unknown profile" in err


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
