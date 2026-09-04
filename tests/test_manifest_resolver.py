#!/usr/bin/env python3
"""Unit coverage for the ManifestResolver surface (PRD-176 FR1).

Pins the resolver's public contract: ManualTarget normalization (AC6), the
one-resolver-one-run cache semantics (AC7), and EvalMode's effect on
config_check handling. Pure Python over tmp-dir YAML trees; imports only
public API (NFR3).
"""

import json
from pathlib import Path

import pytest
import yaml

from profile_dispatcher import (  # noqa: E402
    EvalMode,
    ManifestResolver,
    ManualTarget,
    manifest_to_json,
)


def _write_tree(root: Path, roles: list) -> None:
    """Minimal profiles tree: i3 profile + laptop overlay + one section."""
    (root / "overlays").mkdir(parents=True)
    (root / "_sections.yml").write_text(yaml.safe_dump(
        {"sections": [{"name": "base", "comment": "base section"}]}
    ))
    (root / "i3.yml").write_text(yaml.safe_dump({
        "display_manager_default": "lightdm",
        "desktop_environment": "i3",
        "roles": roles,
    }))
    (root / "overlays" / "laptop.yml").write_text(yaml.safe_dump({
        "name": "laptop",
        "description": "laptop extras",
        "applies_when": "laptop | default(false)",
        "roles": [
            {"role": "laptop", "section": "base"},
            {"role": "backlight", "requires_display": True},
        ],
    }))


class TestManifestResolver:
    """Public-contract tests for ManifestResolver / ManualTarget / EvalMode."""

    def test_none_target_means_manual_defaults(self, tmp_path):
        _write_tree(tmp_path, roles=[])
        rm = ManifestResolver(profiles_dir=str(tmp_path)).manifest(None)
        assert rm.profile == "manual"
        assert rm.display_manager is None
        assert rm.has_display is False
        assert rm.profile_flags["_dm"] == ""

    def test_manual_target_flags(self, tmp_path):
        _write_tree(tmp_path, roles=[])
        target = ManualTarget(
            display_manager="lightdm",
            desktop_environment="gnome",
            disable=("gnome",),
        )
        rm = ManifestResolver(profiles_dir=str(tmp_path)).manifest(target)
        assert rm.profile == "manual"
        assert rm.profile_flags["_is_gnome"] is False
        assert rm.profile_flags["_has_display"] is True
        assert rm.profile_flags["_dm"] == "lightdm"

    def test_manual_target_unknown_disable_name_raises(self, tmp_path):
        _write_tree(tmp_path, roles=[])
        with pytest.raises(ValueError, match="Unknown desktop environment"):
            ManifestResolver(profiles_dir=str(tmp_path)).manifest(
                ManualTarget(disable=("cinnamon",))
            )

    def test_fresh_resolver_sees_yaml_changes_cached_one_does_not(self, tmp_path):
        """One resolver = one logical run (AC7): a fresh instance re-reads YAML."""
        _write_tree(tmp_path, roles=[])
        cached = ManifestResolver(profiles_dir=str(tmp_path))
        assert all(g.role != "extra" for g in cached.manifest("i3").roles)

        (tmp_path / "i3.yml").write_text(yaml.safe_dump({
            "display_manager_default": "lightdm",
            "desktop_environment": "i3",
            "roles": [{"role": "extra", "section": "base"}],
        }))

        # The pre-existing instance keeps its parsed view (documented semantics)
        assert all(g.role != "extra" for g in cached.manifest("i3").roles)
        # A fresh resolver sees the change
        fresh = ManifestResolver(profiles_dir=str(tmp_path))
        assert any(g.role == "extra" for g in fresh.manifest("i3").roles)

    def test_eval_mode_controls_config_check(self, tmp_path):
        roles = [{"role": "dotfiles", "section": "base", "config_check": "dotfiles_config is defined"}]
        _write_tree(tmp_path, roles=roles)
        build = ManifestResolver(profiles_dir=str(tmp_path), mode=EvalMode.BUILD)
        runtime = ManifestResolver(profiles_dir=str(tmp_path), mode=EvalMode.RUNTIME)
        bg = next(g for g in build.manifest("i3").roles if g.role == "dotfiles")
        rg = next(g for g in runtime.manifest("i3", host_vars={}).roles if g.role == "dotfiles")
        assert bg.condition == "dotfiles_config is defined"  # kept RAW
        assert rg.condition == "false"  # evaluated against host_vars

    def test_provenance_recorded_at_collection(self, tmp_path):
        """FR4/AC2: source = profile, overlay, or profile+overlays sorted."""
        _write_tree(tmp_path, roles=[{
            "role": "backlight", "section": "base", "requires_display": True,
        }])
        resolver = ManifestResolver(profiles_dir=str(tmp_path))

        # backlight contributed by profile AND overlay; "laptop" role overlay-only
        src = {g.role: g.source for g in resolver.manifest("i3", host_vars={"laptop": True}).roles}
        assert src["backlight"] == "i3+laptop"
        assert src["laptop"] == "laptop"

        # overlay skipped: backlight contributed by profile only
        src = {g.role: g.source for g in resolver.manifest("i3").roles}
        assert src["backlight"] == "i3"
        assert "laptop" not in src

    def test_manifest_to_json_key_order(self, tmp_path):
        _write_tree(tmp_path, roles=[])
        rm = ManifestResolver(profiles_dir=str(tmp_path)).manifest("i3")
        data = json.loads(manifest_to_json(rm))
        assert list(data) == [
            "profile", "display_manager", "has_display",
            "profile_flags", "overlay_flags", "roles",
        ]
