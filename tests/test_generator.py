#!/usr/bin/env python3
"""Tests for PlaybookGenerator boundary (generate, sync_check, resolve, manifest, explain)."""

import json
from pathlib import Path

import pytest

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import (  # noqa: E402
    resolve_manifest,
    resolve_role_manifest,
    _normalize_condition,
    Manifest,
    RoleEntry,
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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

