#!/usr/bin/env python3
"""Tests for condition evaluation, translation, and overlays validation."""

import tempfile
from pathlib import Path

import pytest

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import (  # noqa: E402
    validate_overlays,
    _DictEvaluator,
    AnsibleConditionTranslator,
    DefaultTranslator,
)


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


class TestPrivateDictEvaluator:
    """Test _DictEvaluator expression evaluation."""

    def test_mapped_expression_returns_correct_bool(self):
        """An expression in the mapping should return its mapped boolean value."""
        evaluator = _DictEvaluator({"laptop": True, "desktop": False})
        assert evaluator.evaluate("laptop", {}) is True
        assert evaluator.evaluate("desktop", {}) is False

    def test_unmapped_expression_returns_false(self):
        """An expression not in the mapping should return False."""
        evaluator = _DictEvaluator({"laptop": True})
        assert evaluator.evaluate("desktop", {}) is False
        assert evaluator.evaluate("unknown", {}) is False

    def test_context_parameter_is_ignored(self):
        """The context parameter should be ignored (for protocol compatibility)."""
        evaluator = _DictEvaluator({"laptop": True})
        # Context dict should not affect the result
        assert evaluator.evaluate("laptop", {"laptop": False}) is True
        assert evaluator.evaluate("laptop", {}) is True

    def test_empty_mapping_returns_false_for_all(self):
        """An empty mapping should return False for all expressions."""
        evaluator = _DictEvaluator({})
        assert evaluator.evaluate("anything", {}) is False
        assert evaluator.evaluate("laptop", {}) is False

    def test_multiple_expressions(self):
        """Multiple expressions should all resolve correctly."""
        evaluator = _DictEvaluator({
            "laptop": True,
            "desktop": False,
            "server": True,
        })
        assert evaluator.evaluate("laptop", {}) is True
        assert evaluator.evaluate("desktop", {}) is False
        assert evaluator.evaluate("server", {}) is True


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

    def test_config_check_jinja_filter_passed_through(self):
        """config_check with Jinja filters (e.g. | default(false) | bool) is passed through as-is."""
        translator = AnsibleConditionTranslator(preserve_config_check=False)
        annotation = {"role": "ai", "tags": ["ai"], "config_check": "ai_enabled | default(false) | bool"}
        result = translator.translate_annotation(annotation, {})
        assert result == "ai_enabled | default(false) | bool"

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
        evaluator = _DictEvaluator({"dotfiles is defined": True})
        translator = DefaultTranslator(evaluator=evaluator)
        annotation = {"role": "dotfiles", "tags": ["dotfiles"], "config_check": "dotfiles is defined"}
        result = translator.translate_annotation(annotation, {})
        # _DictEvaluator returns True for the expression
        assert result == "true"

    def test_default_translator_with_preserve_config_check(self):
        """DefaultTranslator factory passes preserve_config_check through."""
        translator = DefaultTranslator(preserve_config_check=True)
        annotation = {"role": "dotfiles", "tags": ["dotfiles"], "config_check": "dotfiles is defined"}
        result = translator.translate_annotation(annotation, {})
        # With preserve_config_check=True, the expression is kept as-is
        assert result == "dotfiles is defined"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
