#!/usr/bin/env python3
"""Tests for PlaybookGenerator boundary (generate, sync_check, resolve, manifest, explain)."""

import json
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import (  # noqa: E402
    resolve_role_manifest,
    resolve_manifest,
    discover_overlay_variables,
    generate_host_vars_template,
    generate_overlay_facts_task,
    PlaybookGenerator,
    PlaybookRole,
    main,
)


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

    def test_sync_playbook_detects_overlay_role_drift(self, capsys, tmp_path):
        """Overlay-gated role condition drift is detected (V1: _overlay_ roles are compared)."""
        content = Path(self._PLAYBOOK).read_text()
        mutated = content.replace("when: _overlay_laptop", "when: _overlay_no_such_overlay", 1)
        assert mutated != content, "play.yml must contain an _overlay_laptop-gated role"
        playbook = tmp_path / "play.yml"
        playbook.write_text(mutated)
        rc = main(["sync-playbook", "--playbook", str(playbook), "--check"])
        out = capsys.readouterr().out
        assert rc == 1
        assert "laptop" in out

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
            "_has_display and goesimage is defined",
            "goesimage is defined and _has_display",
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

    def test_sync_check_treats_equivalent_conditions_as_in_sync(self):
        """sync_check() treats '| bool' filters and AND-term reordering as equivalent."""
        generator = PlaybookGenerator(
            profiles_dir=_PROFILES_DIR,
            os_family="Archlinux",
            host_vars={},
        )
        expected_roles = generator.generate()

        def mangle(condition: str) -> str:
            if not condition or " and " not in condition:
                return condition
            terms = condition.split(" and ")
            return " and ".join(reversed(terms)) + " | bool"

        playbook_roles = []
        for role in expected_roles:
            if role.condition:
                playbook_roles.append({"role": role.role, "when": mangle(role.condition)})
            else:
                playbook_roles.append(role.role)

        playbook_data = {"hosts": "all", "roles": playbook_roles}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(playbook_data, f)
            temp_path = f.name

        try:
            result = generator.sync_check(temp_path)
            assert result.in_sync is True, (
                f"Equivalent conditions flagged: {result.condition_mismatches}"
            )
        finally:
            os.unlink(temp_path)

    def test_generate_ors_conditions_for_overlapping_roles(self, tmp_path):
        """generate() OR's conditions when a role appears in profile and overlay with different conditions."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        overlays_path = profiles_dir / "overlays"
        overlays_path.mkdir()
        (profiles_dir / "_sections.yml").write_text(
            "sections:\n  - {name: misc, comment: Misc}\n"
        )

        base_data = {
            "display_manager_default": "",
            "desktop_environment": "",
            "roles": [{"role": "foo", "tags": ["t1"], "requires_display": True}],
        }
        (profiles_dir / "_base.yml").write_text(yaml.dump(base_data, default_flow_style=False))

        profile_data = {
            "extends": "_base",
            "display_manager_default": "",
            "desktop_environment": "",
            "roles": [],
        }
        (profiles_dir / "test.yml").write_text(yaml.dump(profile_data, default_flow_style=False))

        overlay_data = {
            "name": "test_overlay",
            "applies_when": "test_overlay | default(false)",
            "roles": [{"role": "foo", "tags": ["t2"], "os": "debian"}],
        }
        (overlays_path / "test_overlay.yml").write_text(
            yaml.dump(overlay_data, default_flow_style=False)
        )

        gen = PlaybookGenerator(
            profiles_dir=str(profiles_dir),
            os_family="Archlinux",
            host_vars={"test_overlay": True},
        )
        roles = gen.generate()
        foo = [r for r in roles if r.role == "foo"]
        assert len(foo) == 1
        # Different conditions from profile and overlay should be OR'd
        assert " or " in foo[0].condition.lower()
        # Tags should be unioned
        assert "t1" in foo[0].tags
        assert "t2" in foo[0].tags

    def test_generate_no_or_for_identical_conditions(self, tmp_path):
        """generate() does not OR identical conditions from different sources."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        overlays_path = profiles_dir / "overlays"
        overlays_path.mkdir()
        (profiles_dir / "_sections.yml").write_text(
            "sections:\n  - {name: misc, comment: Misc}\n"
        )

        base_data = {
            "display_manager_default": "",
            "desktop_environment": "",
            "roles": [{"role": "bar", "tags": ["t1"], "os": "archlinux"}],
        }
        (profiles_dir / "_base.yml").write_text(yaml.dump(base_data, default_flow_style=False))

        profile_data = {
            "extends": "_base",
            "display_manager_default": "",
            "desktop_environment": "",
            "roles": [],
        }
        (profiles_dir / "test.yml").write_text(yaml.dump(profile_data, default_flow_style=False))

        overlay_data = {
            "name": "test_overlay",
            "applies_when": "test_overlay | default(false)",
            "roles": [{"role": "bar", "tags": ["t2"], "os": "archlinux"}],
        }
        (overlays_path / "test_overlay.yml").write_text(
            yaml.dump(overlay_data, default_flow_style=False)
        )

        gen = PlaybookGenerator(
            profiles_dir=str(profiles_dir),
            os_family="Archlinux",
            host_vars={"test_overlay": True},
        )
        roles = gen.generate()
        bar = [r for r in roles if r.role == "bar"]
        assert len(bar) == 1
        # Same condition from both sources should NOT produce OR
        assert " or " not in bar[0].condition.lower()
        assert bar[0].condition == "_is_arch"

    def test_generate_deduplicates_across_three_sources(self, tmp_path):
        """generate() deduplicates roles across profile entries + overlay without duplicate OR terms."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        overlays_path = profiles_dir / "overlays"
        overlays_path.mkdir()
        (profiles_dir / "_sections.yml").write_text(
            "sections:\n  - {name: misc, comment: Misc}\n"
        )

        base_data = {
            "display_manager_default": "",
            "desktop_environment": "",
            "roles": [
                {"role": "baz", "tags": ["t1"], "requires_display": True},
                {"role": "baz", "tags": ["t2"], "os": "archlinux"},
            ],
        }
        (profiles_dir / "_base.yml").write_text(yaml.dump(base_data, default_flow_style=False))

        profile_data = {
            "extends": "_base",
            "display_manager_default": "",
            "desktop_environment": "",
            "roles": [],
        }
        (profiles_dir / "test.yml").write_text(yaml.dump(profile_data, default_flow_style=False))

        overlay_data = {
            "name": "test_overlay",
            "applies_when": "test_overlay | default(false)",
            "roles": [{"role": "baz", "tags": ["t3"], "requires_display": True}],
        }
        (overlays_path / "test_overlay.yml").write_text(
            yaml.dump(overlay_data, default_flow_style=False)
        )

        gen = PlaybookGenerator(
            profiles_dir=str(profiles_dir),
            os_family="Archlinux",
            host_vars={"test_overlay": True},
        )
        roles = gen.generate()
        baz = [r for r in roles if r.role == "baz"]
        assert len(baz) == 1
        # generate() includes overlay sources: the three distinct conditions
        # (_has_display, _is_arch, (_has_display) and _overlay_test_overlay)
        # OR into one condition — exactly 2 'or' joins. The _has_display term
        # shared by two sources must not add a redundant third arm.
        cond = baz[0].condition
        or_count = cond.lower().count(" or ")
        assert or_count == 2, f"Expected exactly 2 'or', got {or_count}: {cond}"
        assert cond.count("_has_display") == 2


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


class TestSectionSorting:
    """Tests verifying role sorting by section in manifest output."""

    def test_resolve_role_manifest_output_sorted_by_section(self):
        """Resolved manifest roles should be sorted by section, then alphabetically."""
        manifest = resolve_role_manifest(
            profile="i3",
            os_family="Archlinux",
        )
        role_names = [r.role for r in manifest.roles]

        # First roles should be from GPU Detection, then Base System
        assert role_names[:5] == ["gpu_detect", "gpu_drivers", "base", "grub", "microcode"]


class TestDiscoverOverlayVariables:
    """Tests for discover_overlay_variables() function."""

    def test_discovers_current_overlays(self):
        """Returns all overlay variables from current overlays directory."""
        variables = discover_overlay_variables(_PROFILES_DIR)
        # Current overlays: laptop, bluetooth, user_environment
        expected = ["bluetooth", "laptop", "user_environment"]
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


class TestHostVarsTemplateRendering:
    """V2: rendering round-trip for the pre_tasks Jinja2 -> CLI -> JSON seam (play.yml:12-40)."""

    @staticmethod
    def _render(template: str, host_vars: dict) -> str:
        """Render with Ansible-equivalent filters (combine/to_json are Ansible, not Jinja2 builtins)."""
        from jinja2 import Environment

        env = Environment()
        env.filters["combine"] = lambda d, other: {**d, **other}
        env.filters["to_json"] = json.dumps
        return env.from_string(template).render(**host_vars)

    @pytest.mark.parametrize(
        "host_vars,expected_json",
        [
            ({}, {}),
            ({"laptop": True}, {"laptop": True}),
            ({"bluetooth": {"disable": False}}, {"bluetooth": {"disable": False}}),
            ({"laptop": True, "unrelated": 1}, {"laptop": True}),  # undiscovered var excluded
        ],
        ids=["none", "one", "several", "undiscovered-excluded"],
    )
    def test_template_renders_to_expected_json(self, host_vars, expected_json):
        """Rendered _host_vars_json is single-line, single-quote-safe, and parses to the expected dict."""
        variables = discover_overlay_variables(_PROFILES_DIR)
        rendered = self._render(generate_host_vars_template(variables), host_vars)
        # play.yml:27 wraps the value in single quotes — output must stay a safe one-word argument.
        assert "'" not in rendered
        assert "\n" not in rendered
        assert json.loads(rendered) == expected_json

    @pytest.mark.parametrize(
        "host_vars,expected_flags",
        [
            ({}, {"_overlay_laptop": False, "_overlay_bluetooth": False}),
            ({"laptop": True}, {"_overlay_laptop": True, "_overlay_bluetooth": False}),
            ({"bluetooth": {"disable": False}}, {"_overlay_laptop": False, "_overlay_bluetooth": True}),
            ({"bluetooth": {"disable": True}}, {"_overlay_laptop": False, "_overlay_bluetooth": False}),
        ],
        ids=["none", "laptop", "bluetooth", "bluetooth-disabled"],
    )
    def test_rendered_json_drives_overlay_flags(self, capsys, host_vars, expected_flags):
        """Rendered JSON fed through resolve-role-manifest produces the expected overlay_flags."""
        variables = discover_overlay_variables(_PROFILES_DIR)
        rendered = self._render(generate_host_vars_template(variables), host_vars)
        rc = main([
            "resolve-role-manifest",
            "--profiles-dir", _PROFILES_DIR,
            "--profile", "manual",
            "--os-family", "Archlinux",
            "--host-vars", rendered,
        ])
        assert rc == 0
        manifest = json.loads(capsys.readouterr().out)
        for flag, expected in expected_flags.items():
            assert (manifest["overlay_flags"].get(flag) is True) == expected, flag


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


class TestResolveManifestFunction:
    """Test resolve_manifest() function (module-level convenience boundary)."""

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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

