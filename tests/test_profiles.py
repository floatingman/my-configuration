#!/usr/bin/env python3
"""Tests for profile/overlay loading and validation."""

import tempfile
from pathlib import Path

import pytest

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import (  # noqa: E402
    ManifestResolver,
    ManualTarget,
    resolve,
    resolve_role_manifest,
    validate_profile,
    validate_overlays,
    load_sections,
    load_profile,
    list_profiles,
    load_overlay,
    main,
)

_DES = ("i3", "hyprland", "gnome", "awesomewm", "kde")


class TestProfileMode:
    """Profile mode resolution, exercised through ManifestResolver (FR7)."""

    @pytest.mark.parametrize(
        "profile,dm,de_flag",
        [
            ("headless", None, None),
            ("i3", "lightdm", "i3"),
            ("hyprland", "sddm", "hyprland"),
            ("gnome", "gdm", "gnome"),
            ("awesomewm", "lightdm", "awesomewm"),
            ("kde", "sddm", "kde"),
        ],
    )
    def test_profile_flags(self, profile, dm, de_flag):
        rm = ManifestResolver().manifest(profile)
        assert rm.profile == profile
        assert rm.display_manager == dm
        assert rm.has_display is (dm is not None)
        for de in _DES:
            assert rm.profile_flags[f"_is_{de}"] is (de == de_flag), de

    def test_unknown_profile_raises_value_error(self):
        with pytest.raises(ValueError) as exc_info:
            ManifestResolver().manifest("unknown_profile")
        error_msg = str(exc_info.value)
        assert "Unknown profile" in error_msg
        assert "unknown_profile" in error_msg
        for name in ("headless", "i3", "hyprland", "gnome", "awesomewm", "kde"):
            assert name in error_msg

    def test_none_empty_whitespace_and_manual_targets_are_manual_mode(self):
        resolver = ManifestResolver()
        baseline = resolver.manifest(None)
        assert baseline.profile == "manual"
        for target in ("", "   ", "manual"):
            assert resolver.manifest(target) == baseline

    def test_case_sensitive_profile_names(self):
        resolver = ManifestResolver()
        with pytest.raises(ValueError):
            resolver.manifest("I3")
        with pytest.raises(ValueError):
            resolver.manifest("Hyprland")


class TestManualMode:
    """Manual mode via ManualTarget, exercised through ManifestResolver (FR7)."""

    def test_no_display_manager(self):
        rm = ManifestResolver().manifest(ManualTarget())
        assert rm.profile == "manual"
        assert rm.display_manager is None
        assert rm.has_display is False
        assert all(rm.profile_flags[f"_is_{de}"] is False for de in _DES)

    def test_empty_display_manager_means_none(self):
        rm = ManifestResolver().manifest(ManualTarget(display_manager=""))
        assert rm.display_manager is None
        assert rm.has_display is False

    def test_empty_desktop_environment_is_dual_desktop(self):
        rm = ManifestResolver().manifest(
            ManualTarget(display_manager="lightdm", desktop_environment="")
        )
        assert rm.display_manager == "lightdm"
        assert rm.has_display is True
        assert rm.profile_flags["_is_i3"] is True
        assert rm.profile_flags["_is_hyprland"] is True
        assert rm.profile_flags["_is_gnome"] is False
        assert rm.profile_flags["_is_kde"] is False

    @pytest.mark.parametrize(
        "dm,de,only_de",
        [
            ("lightdm", None, None),   # dual-desktop default
            ("gdm", None, None),       # dual-desktop with gdm
            ("lightdm", "i3", "i3"),
            ("lightdm", "hyprland", "hyprland"),
            ("gdm", "gnome", "gnome"),
            ("lightdm", "awesomewm", "awesomewm"),
            ("lightdm", "kde", "kde"),
        ],
    )
    def test_display_manager_and_desktop_environment(self, dm, de, only_de):
        rm = ManifestResolver().manifest(
            ManualTarget(display_manager=dm, desktop_environment=de)
        )
        assert rm.profile == "manual"
        assert rm.display_manager == dm
        assert rm.has_display is True
        for de_name in _DES:
            if only_de is None:
                expected = de_name in ("i3", "hyprland")
            else:
                expected = de_name == only_de
            assert rm.profile_flags[f"_is_{de_name}"] is expected, de_name


class TestDisableFlags:
    """disable_* suppression in manual mode via ManualTarget (FR7)."""

    def test_disable_i3(self):
        rm = ManifestResolver().manifest(
            ManualTarget(display_manager="lightdm", disable=("i3",))
        )
        assert rm.profile_flags["_is_i3"] is False
        assert rm.profile_flags["_is_hyprland"] is True  # Other DEs unaffected

    def test_disable_hyprland(self):
        rm = ManifestResolver().manifest(
            ManualTarget(display_manager="lightdm", disable=("hyprland",))
        )
        assert rm.profile_flags["_is_hyprland"] is False
        assert rm.profile_flags["_is_i3"] is True  # Other DEs unaffected

    @pytest.mark.parametrize("de", ["gnome", "awesomewm", "kde"])
    def test_disable_single_de(self, de):
        dm = "gdm" if de == "gnome" else "lightdm"
        rm = ManifestResolver().manifest(
            ManualTarget(display_manager=dm, desktop_environment=de, disable=(de,))
        )
        assert rm.profile_flags[f"_is_{de}"] is False

    def test_disable_both_i3_and_hyprland(self):
        rm = ManifestResolver().manifest(
            ManualTarget(display_manager="lightdm", disable=("i3", "hyprland"))
        )
        assert rm.profile_flags["_is_i3"] is False
        assert rm.profile_flags["_is_hyprland"] is False
        assert rm.has_display is True  # Still has display, just no DEs

    def test_disable_flags_with_explicit_desktop_environment(self):
        resolver = ManifestResolver()
        r1 = resolver.manifest(
            ManualTarget(display_manager="lightdm", desktop_environment="i3", disable=("i3",))
        )
        assert r1.profile_flags["_is_i3"] is False
        r2 = resolver.manifest(
            ManualTarget(display_manager="lightdm", desktop_environment="hyprland", disable=("hyprland",))
        )
        assert r2.profile_flags["_is_hyprland"] is False

    def test_all_de_flags_false_preserves_display_manager(self):
        rm = ManifestResolver().manifest(
            ManualTarget(
                display_manager="lightdm",
                desktop_environment="i3",
                disable=("i3", "hyprland"),
            )
        )
        assert rm.display_manager == "lightdm"
        assert rm.has_display is True
        assert rm.profile_flags["_is_i3"] is False
        assert rm.profile_flags["_is_hyprland"] is False

    def test_unknown_disable_name_raises_value_error(self):
        with pytest.raises(ValueError):
            ManifestResolver().manifest(ManualTarget(disable=("cinnamon",)))


class TestDualDesktopMode:
    """Dual-desktop behavior via ManualTarget (FR7): display_manager set
    without desktop_environment enables both i3 and hyprland."""

    def test_dual_desktop_with_lightdm(self):
        rm = ManifestResolver().manifest(ManualTarget(display_manager="lightdm"))
        assert rm.profile_flags["_is_i3"] is True
        assert rm.profile_flags["_is_hyprland"] is True

    def test_dual_desktop_with_gdm(self):
        rm = ManifestResolver().manifest(ManualTarget(display_manager="gdm"))
        assert rm.profile_flags["_is_i3"] is True
        assert rm.profile_flags["_is_hyprland"] is True

    def test_explicit_desktop_environment_breaks_dual_desktop(self):
        rm = ManifestResolver().manifest(
            ManualTarget(display_manager="lightdm", desktop_environment="i3")
        )
        assert rm.profile_flags["_is_i3"] is True
        assert rm.profile_flags["_is_hyprland"] is False



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
    """Overlay loading semantics through the resolver's repository-backed
    diagnostic view (FR7 re-home of the former load_overlay() tests)."""

    def test_all_shipped_overlays_are_discovered_in_sorted_order(self):
        view = ManifestResolver().overlays({}, has_display=True)
        assert [r.overlay.name for r in view] == [
            "Bluetooth Support Overlay",
            "Laptop Features Overlay",
            "User Environment",
        ]

    def _overlay_view(self, host_vars, has_display=True):
        return {
            r.overlay.name: r for r in ManifestResolver().overlays(host_vars, has_display)
        }

    def test_laptop_overlay_content(self):
        laptop = self._overlay_view({})["Laptop Features Overlay"]
        assert laptop.overlay.applies_when == "laptop | default(false)"
        roles = laptop.overlay.roles
        assert len(roles) == 2
        assert roles[0].role == "laptop"
        assert tuple(roles[0].tags) == ("laptop",)
        assert roles[1].role == "backlight"
        assert tuple(roles[1].tags) == ("backlight",)
        assert roles[1].requires_display is True

    def test_bluetooth_overlay_content(self):
        bt = self._overlay_view({})["Bluetooth Support Overlay"]
        assert bt.overlay.applies_when == (
            "bluetooth is defined and not (bluetooth.disable | default(false))"
        )
        roles = bt.overlay.roles
        assert len(roles) == 1
        assert roles[0].role == "bluetooth"
        assert tuple(roles[0].tags) == ("bluetooth",)
        assert roles[0].os == "archlinux"

    def test_laptop_overlay_applies_against_host_vars(self):
        off = self._overlay_view({})["Laptop Features Overlay"]
        on = self._overlay_view({"laptop": True})["Laptop Features Overlay"]
        assert off.applies is False
        assert on.applies is True
        assert [role.role for role, role_applies in on.resolved_roles if role_applies] == [
            "laptop", "backlight",
        ]

    def test_laptop_roles_suppressed_without_display(self):
        view = self._overlay_view({"laptop": True}, has_display=False)
        laptop = view["Laptop Features Overlay"]
        assert laptop.applies is True
        # requires_display flips backlight off; plain laptop role still applies
        by_role = {role.role: role_applies for role, role_applies in laptop.resolved_roles}
        assert by_role["laptop"] is True
        assert by_role["backlight"] is False

    def test_bluetooth_disable_via_host_vars(self):
        bt = self._overlay_view({"bluetooth": {"disable": True}})["Bluetooth Support Overlay"]
        assert bt.applies is False

    def test_manifest_applies_laptop_overlay_flags_and_roles(self):
        rm = ManifestResolver().manifest("i3", host_vars={"laptop": True})
        assert rm.overlay_flags["_overlay_laptop"] is True
        assert rm.overlay_flags["_overlay_backlight"] is True
        # bluetooth overlay not applied -> its flags are absent entirely
        assert "_overlay_bluetooth" not in rm.overlay_flags
        assert any(g.role == "backlight" and g.source == "i3+laptop" for g in rm.roles)



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



class TestSectionValidation:
    """FR6: every dict role entry carries a valid section key (PRD-159)."""

    def _write_sections(self, tmpdir: str) -> None:
        Path(tmpdir, "_sections.yml").write_text(
            "sections:\n"
            "  - name: misc\n"
            "    comment: Misc\n"
            "  - name: other\n"
            "    comment: Other\n"
        )

    def _write_valid_profile(self, tmpdir: str, name: str, role_line: str) -> None:
        Path(tmpdir, f"{name}.yml").write_text(
            f"name: {name}\n"
            'display_manager_default: ""\n'
            'desktop_environment: ""\n'
            "roles:\n"
            f"  - {role_line}\n"
        )

    def _write_overlay(self, tmpdir: str, role_line: str) -> None:
        Path(tmpdir, "overlays").mkdir()
        Path(tmpdir, "overlays", "thing.yml").write_text(
            "name: thing\n"
            'applies_when: "thing | default(false)"\n'
            "roles:\n"
            f"  - {role_line}\n"
        )

    def test_validate_rejects_role_missing_section(self):
        """A dict role entry without section: fails profile validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            self._write_valid_profile(
                tmpdir, "testprof", "{ role: demo_role, tags: [demo_role] }"
            )
            errors = validate_profile(tmpdir, "testprof")
            assert any(
                "role 'demo_role' missing required field: section" in e for e in errors
            )

    def test_validate_rejects_unknown_section_key(self):
        """A dict role entry with an unknown section key fails validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            self._write_valid_profile(
                tmpdir, "testprof", "{ role: demo_role, tags: [demo_role], section: bogus }"
            )
            errors = validate_profile(tmpdir, "testprof")
            assert any(
                "role 'demo_role' has unknown section 'bogus'" in e for e in errors
            )

    def test_validate_rejects_overlay_role_missing_section(self):
        """A dict overlay role entry without section: fails overlay validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            self._write_overlay(tmpdir, "{ role: demo_role, tags: [demo_role] }")
            results = validate_overlays(tmpdir)
            thing_errors = dict(results).get("thing", [])
            assert any(
                "role 'demo_role' missing required field: section" in e
                for e in thing_errors
            )

    def test_validate_rejects_conflicting_sections_across_files(self, capsys):
        """The same role with different sections in two files fails validate (rc 1)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            self._write_valid_profile(
                tmpdir, "testprof", "{ role: demo_role, tags: [demo_role], section: misc }"
            )
            self._write_overlay(
                tmpdir, "{ role: demo_role, tags: [demo_role], section: other }"
            )
            rc = main(["validate", "--profiles-dir", tmpdir])
            err = capsys.readouterr().err
            assert rc == 1
            assert "conflicting sections" in err

    def test_validate_rejects_role_entry_missing_role_name(self):
        """A dict role entry without role: fails profile validation.

        Otherwise the entry is silently dropped during manifest generation.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            self._write_valid_profile(
                tmpdir, "testprof", "{ tags: [demo_role], section: misc }"
            )
            errors = validate_profile(tmpdir, "testprof")
            assert any("missing required field: role" in e for e in errors)

    def test_validate_rejects_overlay_role_entry_missing_role_name(self):
        """A dict overlay role entry without role: reports one structural error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            self._write_overlay(tmpdir, "{ tags: [demo_role], section: misc }")
            results = validate_overlays(tmpdir)
            thing_errors = dict(results).get("thing", [])
            assert len(thing_errors) == 1
            assert "missing required field 'role'" in thing_errors[0]

    def test_validate_reports_non_string_section(self):
        """A non-string section (e.g. a YAML list) reports an error, not a TypeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            self._write_valid_profile(
                tmpdir, "testprof", "{ role: demo_role, tags: [demo_role], section: [misc] }"
            )
            errors = validate_profile(tmpdir, "testprof")
            assert any("non-string 'section' field" in e for e in errors)

    def test_validate_reports_non_string_section_in_overlay(self):
        """A non-string section in an overlay reports an error, not a TypeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            self._write_overlay(
                tmpdir, "{ role: demo_role, tags: [demo_role], section: [misc] }"
            )
            results = validate_overlays(tmpdir)
            thing_errors = dict(results).get("thing", [])
            assert any("non-string 'section' field" in e for e in thing_errors)

    def test_validate_handles_non_string_role_name(self, capsys):
        """validate reports malformed role entries instead of crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            self._write_valid_profile(
                tmpdir, "testprof", "{ role: [demo_role], tags: [x], section: misc }"
            )
            rc = main(["validate", "--profiles-dir", tmpdir])
            err = capsys.readouterr().err
            assert rc == 1
            assert "non-string 'role' field" in err

    def test_validate_reports_non_list_roles_field(self):
        """A non-list roles field reports one type error, not per-character noise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            Path(tmpdir, "testprof.yml").write_text(
                "name: testprof\n"
                'display_manager_default: ""\n'
                'desktop_environment: ""\n'
                "roles: demo_role\n"
            )
            errors = validate_profile(tmpdir, "testprof")
            assert errors == ["Field 'roles' must be a list, got str"]

    def test_resolve_manifest_keeps_first_valid_section(self):
        """A later duplicate entry without section: must not reset the sort bucket."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "_sections.yml").write_text(
                "sections:\n"
                "  - name: misc\n"
                "    comment: Misc\n"
            )
            Path(tmpdir, "_base.yml").write_text(
                "name: base\n"
                'display_manager_default: ""\n'
                'desktop_environment: ""\n'
                "roles:\n"
                "  - { role: aaa_role, tags: [aaa_role], section: misc }\n"
                "  - { role: zzz_role, tags: [zzz_role], section: misc }\n"
            )
            Path(tmpdir, "test.yml").write_text(
                "name: test\n"
                "extends: _base\n"
                'display_manager_default: ""\n'
                'desktop_environment: ""\n'
                "roles: []\n"
            )
            Path(tmpdir, "overlays").mkdir()
            Path(tmpdir, "overlays", "test_overlay.yml").write_text(
                "name: test_overlay\n"
                'applies_when: "test_overlay | default(false)"\n'
                "roles:\n"
                "  - { role: aaa_role, tags: [aaa2] }\n"
            )
            manifest = resolve_role_manifest(
                profile="test",
                profiles_dir=tmpdir,
                host_vars={"test_overlay": True},
            )
            names = [r.role for r in manifest.roles]
            assert names.index("aaa_role") < names.index("zzz_role")

    def test_validate_rejects_non_mapping_role_entry(self):
        """A string role entry cannot carry section: and must fail validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            Path(tmpdir, "testprof.yml").write_text(
                "name: testprof\n"
                'display_manager_default: ""\n'
                'desktop_environment: ""\n'
                "roles:\n"
                "  - demo_role\n"
            )
            errors = validate_profile(tmpdir, "testprof")
            assert any("must be a mapping" in e for e in errors)

    def test_validate_reports_non_list_overlay_roles_field(self):
        """A non-list overlay roles field reports one type error, not per-char noise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            Path(tmpdir, "overlays").mkdir()
            Path(tmpdir, "overlays", "thing.yml").write_text(
                "name: thing\n"
                'applies_when: "thing | default(false)"\n'
                "roles: demo_role\n"
            )
            results = validate_overlays(tmpdir)
            thing_errors = dict(results).get("thing", [])
            assert len(thing_errors) == 1
            assert "'roles' must be a list, got str" in thing_errors[0]

    def test_validate_rejects_non_mapping_overlay_role_entry(self):
        """A string overlay role entry reports one structural error, not duplicates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            Path(tmpdir, "overlays").mkdir()
            Path(tmpdir, "overlays", "thing.yml").write_text(
                "name: thing\n"
                'applies_when: "thing | default(false)"\n'
                "roles:\n"
                "  - demo_role\n"
            )
            results = validate_overlays(tmpdir)
            thing_errors = dict(results).get("thing", [])
            assert len(thing_errors) == 1
            assert "role entry 0 must be a dict, got str" in thing_errors[0]

    def test_validate_detects_base_vs_profile_section_conflict(self, capsys):
        """A role sectioned differently in _base.yml and a profile fails validate.

        _base.yml folds into every profile via extends, so a base-vs-profile
        section conflict is a generation failure and must surface here too.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_sections(tmpdir)
            Path(tmpdir, "_base.yml").write_text(
                "name: base\n"
                'display_manager_default: ""\n'
                'desktop_environment: ""\n'
                "roles:\n"
                "  - { role: demo_role, tags: [demo_role], section: misc }\n"
            )
            Path(tmpdir, "testprof.yml").write_text(
                "name: testprof\n"
                "extends: _base\n"
                'display_manager_default: ""\n'
                'desktop_environment: ""\n'
                "roles:\n"
                "  - { role: demo_role, tags: [demo_role], section: other }\n"
            )
            rc = main(["validate", "--profiles-dir", tmpdir])
            err = capsys.readouterr().err
            assert rc == 1
            assert "conflicting sections" in err


class TestLoadSections:
    """Fail-fast contract of load_sections() (PRD-159 Slice 3)."""

    def test_rejects_non_string_comment(self):
        """A non-string comment fails load_sections instead of reaching play.yml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "_sections.yml").write_text(
                "sections:\n"
                "  - name: misc\n"
                "    comment: [Misc]\n"
            )
            with pytest.raises(ValueError, match="non-string 'comment' field"):
                load_sections(tmpdir)

    def test_rejects_non_string_name(self):
        """A non-string section name fails load_sections (pins existing behavior)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "_sections.yml").write_text(
                "sections:\n"
                "  - name: [misc]\n"
                "    comment: Misc\n"
            )
            with pytest.raises(ValueError, match="non-string 'name' field"):
                load_sections(tmpdir)

    def test_reports_unreadable_file(self):
        """An unreadable _sections.yml raises ValueError, not a raw OSError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # exists() is True for a directory, but read_text() fails with OSError
            Path(tmpdir, "_sections.yml").mkdir()
            with pytest.raises(ValueError, match="cannot read file"):
                load_sections(tmpdir)

    def test_returns_only_validated_fields(self):
        """Section dicts carry exactly the validated keys; stray keys are dropped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "_sections.yml").write_text(
                "sections:\n"
                "  - name: misc\n"
                "    comment: Misc\n"
                "    roles: [stale]\n"
                "    description: stray\n"
            )
            result = load_sections(tmpdir)
            assert result == [{"name": "misc", "comment": "Misc"}]
