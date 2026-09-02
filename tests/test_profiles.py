#!/usr/bin/env python3
"""Tests for profile/overlay loading and validation."""

import tempfile
from pathlib import Path

import pytest

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import (  # noqa: E402
    resolve,
    resolve_overlays,
    validate_profile,
    load_profile,
    list_profiles,
    load_overlay,
)


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

    def test_none_profile_equals_manual_mode(self):
        """profile=None should behave like manual mode."""
        result_none = resolve(profile=None)
        result_manual = resolve()
        assert result_none == result_manual

    def test_empty_string_profile_equals_manual_mode(self):
        """profile='' should behave like manual mode."""
        result_empty = resolve(profile='')
        result_manual = resolve()
        assert result_empty == result_manual

    def test_whitespace_profile_equals_manual_mode(self):
        """profile='   ' should behave like manual mode."""
        result_ws = resolve(profile='   ')
        result_manual = resolve()
        assert result_ws == result_manual

    def test_literal_manual_profile_equals_manual_mode(self):
        """Profile='manual' should behave exactly like manual mode."""
        result_manual_profile = resolve(profile='manual')
        result_manual = resolve()
        assert result_manual_profile == result_manual

    def test_case_sensitive_profile_names(self):
        """Profile names should be case-sensitive."""
        with pytest.raises(ValueError):
            resolve(profile='I3')
        with pytest.raises(ValueError):
            resolve(profile='Hyprland')


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


class TestLoadOverlay:
    """Test load_overlay() function."""

    def test_load_laptop_overlay(self):
        """load_overlay correctly parses laptop.yml."""
        overlay = load_overlay(_PROFILES_DIR, "laptop")
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

        # All three overlays are returned (laptop, bluetooth, user_environment)
        assert len(results) == 3
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
        """With empty facts, only default-true overlays should apply."""
        results = resolve_overlays(
            facts={},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )

        # Three overlays present
        assert len(results) == 3
        # laptop and bluetooth should not apply (default(false))
        for result in results:
            if result.overlay.name == "User Environment":
                assert result.applies is True  # default(true)
            else:
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

    def test_custom_evaluator_injection(self):
        """resolve_overlays honors an injected evaluator's verdicts.

        With empty facts the default Jinja2Evaluator would NOT apply the
        laptop overlay; the injected mapping evaluator says it does. The
        control run proves the injection (not the facts) flipped the verdict.
        """
        class MappingEvaluator:
            def __init__(self, mapping):
                self._mapping = mapping

            def evaluate(self, expression, context):
                return self._mapping.get(expression, False)

        evaluator = MappingEvaluator({"laptop | default(false)": True})
        results = resolve_overlays(
            facts={},  # empty: only the injected evaluator can apply laptop
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
            evaluator=evaluator,
        )

        # Control: default evaluator + empty facts → laptop does not apply
        default_results = resolve_overlays(
            facts={},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )
        default_laptop = [r for r in default_results if r.overlay.name == "Laptop Features Overlay"][0]
        assert default_laptop.applies is False

        assert len(results) == 3
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
        assert len(results) == 3

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
