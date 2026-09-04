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
    load_overlay,
    main,
    manifest_to_json,
    resolve_role_manifest,
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


# Recorded PRE-deletion (PRD-176 FR5 / AC3): the substring sniffer vs
# Jinja2Evaluator over the 3 shipped applies_when expressions, the PRD's var
# shapes, and the sniffer's string-"false" special case. Expected values are
# the Jinja2Evaluator verdict (post-swap behavior); delta=True marks the cells
# where the deleted sniffer differed:
#   - string "false" is truthy under Jinja2 (the PRD's accepted delta)
#   - user_environment={} passes through default(true) and is falsy
_PARITY_ROWS = [
    # (expression, var, value, expected_applies, delta_vs_sniffer)
    ("laptop | default(false)", "laptop", "__missing__", False, False),
    ("laptop | default(false)", "laptop", {}, False, False),
    ("laptop | default(false)", "laptop", True, True, False),
    ("laptop | default(false)", "laptop", {"disable": True}, True, False),
    ("laptop | default(false)", "laptop", False, False, False),
    ("laptop | default(false)", "laptop", "false", True, True),
    ("bluetooth is defined and not (bluetooth.disable | default(false))", "bluetooth", "__missing__", False, False),
    ("bluetooth is defined and not (bluetooth.disable | default(false))", "bluetooth", {}, True, False),
    ("bluetooth is defined and not (bluetooth.disable | default(false))", "bluetooth", True, True, False),
    ("bluetooth is defined and not (bluetooth.disable | default(false))", "bluetooth", {"disable": True}, False, False),
    ("bluetooth is defined and not (bluetooth.disable | default(false))", "bluetooth", False, True, False),
    ("bluetooth is defined and not (bluetooth.disable | default(false))", "bluetooth", "false", True, False),
    ("user_environment | default(true)", "user_environment", "__missing__", True, False),
    ("user_environment | default(true)", "user_environment", {}, False, True),
    ("user_environment | default(true)", "user_environment", True, True, False),
    ("user_environment | default(true)", "user_environment", {"disable": True}, True, False),
    ("user_environment | default(true)", "user_environment", False, False, False),
    ("user_environment | default(true)", "user_environment", "false", True, True),
]


class TestAppliesWhenEvaluation:
    """FR5: applies_when is evaluated by the real Jinja2Evaluator."""

    @pytest.mark.parametrize(
        "expression,var,value,expected,delta",
        _PARITY_ROWS,
        ids=[f"{r[0][:14]}..{r[1]}={r[2]}" for r in _PARITY_ROWS],
    )
    def test_applies_when_evaluated_by_jinja2(self, tmp_path, expression, var, value, expected, delta):
        (tmp_path / "overlays").mkdir(parents=True)
        (tmp_path / "_sections.yml").write_text(yaml.safe_dump(
            {"sections": [{"name": "base", "comment": "base section"}]}
        ))
        (tmp_path / "i3.yml").write_text(yaml.safe_dump({
            "display_manager_default": "lightdm",
            "desktop_environment": "i3",
            "roles": [],
        }))
        (tmp_path / "overlays" / "probe.yml").write_text(yaml.safe_dump({
            "name": "probe",
            "description": "parity probe",
            "applies_when": expression,
            "roles": [{"role": "probe_role", "section": "base"}],
        }))
        host_vars = {} if value == "__missing__" else {var: value}
        rm = ManifestResolver(profiles_dir=str(tmp_path)).manifest("i3", host_vars=host_vars)
        assert ("_overlay_probe" in rm.overlay_flags) is expected


class TestFailLoudOnMalformedOverlays:
    """FR6/AC4: malformed overlay YAML is an error naming the overlay."""

    def _tree_with_broken_overlay(self, tmp_path) -> None:
        (tmp_path / "overlays").mkdir(parents=True)
        (tmp_path / "_sections.yml").write_text(yaml.safe_dump(
            {"sections": [{"name": "base", "comment": "base section"}]}
        ))
        (tmp_path / "i3.yml").write_text(yaml.safe_dump({
            "display_manager_default": "lightdm",
            "desktop_environment": "i3",
            "roles": [],
        }))
        (tmp_path / "overlays" / "broken.yml").write_text(
            "name: broken\napplies_when: 'true'\nroles: [unclosed\n"
        )

    def test_manifest_resolver_raises_naming_overlay(self, tmp_path):
        self._tree_with_broken_overlay(tmp_path)
        with pytest.raises(ValueError, match="Overlay 'broken'"):
            ManifestResolver(profiles_dir=str(tmp_path)).manifest("i3")

    def test_legacy_shim_raises_naming_overlay(self, tmp_path):
        self._tree_with_broken_overlay(tmp_path)
        with pytest.raises(ValueError, match="Overlay 'broken'"):
            resolve_role_manifest(profile="i3", profiles_dir=str(tmp_path))

    def test_cli_exits_1_and_names_overlay(self, tmp_path, capsys):
        self._tree_with_broken_overlay(tmp_path)
        rc = main([
            "resolve-role-manifest", "--profile", "i3",
            "--profiles-dir", str(tmp_path),
        ])
        err = capsys.readouterr().err
        assert rc == 1
        # Full message contract (AC4): the overlay is explicitly named with
        # the validate_overlays message pattern, not incidental text.
        assert "Overlay 'broken': invalid YAML" in err

    def test_non_mapping_overlay_doc_raises_naming_overlay(self, tmp_path):
        # A YAML doc that parses to a non-dict (e.g. a bare list) must raise
        # the overlay-named ValueError, never a TypeError.
        self._tree_with_broken_overlay(tmp_path)
        (tmp_path / "overlays" / "listish.yml").write_text("- name\n- applies_when\n- roles\n")
        with pytest.raises(ValueError, match="Overlay 'listish'"):
            load_overlay(str(tmp_path), "listish")


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
