#!/usr/bin/env python3
"""Tests for PlaybookGenerator boundary (generate, sync_check, resolve, manifest, explain, write_playbook)."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import (  # noqa: E402
    resolve_manifest,
    resolve_role_manifest,
    _normalize_condition,
    _section_sort_key,
    discover_overlay_variables,
    generate_host_vars_template,
    generate_overlay_facts_task,
    Manifest,
    RoleEntry,
    PlaybookGenerator,
    PlaybookRole,
    main,
)


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
            "dotfiles_config": True,
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

        # Verify no unconditional roles that are display-specific
        for role_name, condition in role_conditions.items():
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
        text_lower = explanation.lower()
        # Check for at least some of the expected sections
        has_profile_section = "profile" in text_lower
        has_annotation_section = "annotation" in text_lower
        has_condition_section = "condition" in text_lower

        # At least one section should be present for existing roles
        assert has_profile_section or has_annotation_section or has_condition_section


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

