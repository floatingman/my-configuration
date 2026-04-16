#!/usr/bin/env python3
"""Tests for condition evaluation (Jinja2Evaluator, DictEvaluator, overlays)."""

import tempfile
from pathlib import Path

import pytest

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import (  # noqa: E402
    resolve_overlays,
    validate_overlays,
    Jinja2Evaluator,
    DictEvaluator,
    EvaluationError,
)


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

        # Should return both overlays
        assert len(results) == 2
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
        """With empty facts, no overlays should apply."""
        results = resolve_overlays(
            facts={},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
        )

        # Both overlays should be present but not apply
        assert len(results) == 2
        for result in results:
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

    def test_custom_evaluator_dict_evaluator(self):
        """resolve_overlays accepts custom evaluator parameter."""
        evaluator = DictEvaluator({
            "laptop | default(false)": True,
            "bluetooth.disable | default(false)": False,
        })
        results = resolve_overlays(
            facts={"laptop": True},
            has_display=True,
            is_arch=True,
            profiles_dir=_PROFILES_DIR,
            evaluator=evaluator,
        )

        # Should work with DictEvaluator
        assert len(results) == 2
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
        assert len(results) == 2

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



class TestJinja2Evaluator:
    """Test Jinja2Evaluator expression evaluation."""

    def test_truthy_variable(self):
        """A variable set to a truthy value should evaluate to True."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop", {"laptop": True}) is True
        assert evaluator.evaluate("laptop", {"laptop": "yes"}) is True
        assert evaluator.evaluate("laptop", {"laptop": 1}) is True

    def test_falsy_variable(self):
        """A variable set to a falsy value should evaluate to False."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop", {"laptop": False}) is False
        assert evaluator.evaluate("laptop", {"laptop": ""}) is False
        assert evaluator.evaluate("laptop", {"laptop": 0}) is False
        assert evaluator.evaluate("laptop", {"laptop": None}) is False

    def test_absent_variable_with_default(self):
        """A variable with default filter should return the default value when absent."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop | default(false)", {}) is False
        assert evaluator.evaluate("laptop | default(true)", {}) is True
        assert evaluator.evaluate("laptop | default('')", {}) is False  # Empty string is falsy

    def test_absent_variable_without_default_raises_error(self):
        """Referencing an undefined variable without default() should raise EvaluationError."""
        evaluator = Jinja2Evaluator()
        with pytest.raises(EvaluationError, match="Failed to evaluate"):
            evaluator.evaluate("unknown_var", {})

    def test_is_defined_test(self):
        """The 'is defined' test should return True for defined variables."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop is defined", {"laptop": True}) is True
        assert evaluator.evaluate("laptop is defined", {"laptop": False}) is True
        assert evaluator.evaluate("laptop is defined", {}) is False

    def test_nested_dict_access(self):
        """Dotted access should work for nested dictionaries.

        Missing attributes on dicts raise EvaluationError with StrictUndefined;
        use ``| default(false)`` for safe access (see test_nested_dict_access_with_default).
        """
        evaluator = Jinja2Evaluator()
        context = {
            "bluetooth": {"disable": True},
            "laptop": {"hardware": {"trackpad": True}},
        }
        assert evaluator.evaluate("bluetooth.disable", context) is True
        assert evaluator.evaluate("laptop.hardware.trackpad", context) is True
        # Missing attribute on a dict raises EvaluationError (StrictUndefined)
        with pytest.raises(EvaluationError):
            evaluator.evaluate("laptop.hardware.touchscreen", context)

    def test_boolean_and_operator(self):
        """The 'and' operator should perform logical AND."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop and desktop", {"laptop": True, "desktop": True}) is True
        assert evaluator.evaluate("laptop and desktop", {"laptop": True, "desktop": False}) is False
        assert evaluator.evaluate("laptop and desktop", {"laptop": False, "desktop": True}) is False

    def test_boolean_or_operator(self):
        """The 'or' operator should perform logical OR."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop or desktop", {"laptop": True, "desktop": True}) is True
        assert evaluator.evaluate("laptop or desktop", {"laptop": True, "desktop": False}) is True
        assert evaluator.evaluate("laptop or desktop", {"laptop": False, "desktop": False}) is False

    def test_boolean_not_operator(self):
        """The 'not' operator should perform logical NOT."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("not laptop", {"laptop": False}) is True
        assert evaluator.evaluate("not laptop", {"laptop": True}) is False

    def test_complex_boolean_expression(self):
        """Complex boolean expressions with and/or/not should work correctly."""
        evaluator = Jinja2Evaluator()
        context = {"laptop": True, "desktop": False, "gui": True}
        assert evaluator.evaluate("laptop and not desktop", context) is True
        assert evaluator.evaluate("(laptop or desktop) and gui", context) is True
        assert evaluator.evaluate("laptop and desktop and gui", context) is False

    def test_parenthesized_expressions(self):
        """Parentheses should control operator precedence."""
        evaluator = Jinja2Evaluator()
        context = {"a": True, "b": True, "c": False}
        assert evaluator.evaluate("(a or b) and c", context) is False
        assert evaluator.evaluate("a or (b and c)", context) is True

    def test_default_filter_with_boolean_operators(self):
        """Default filters should work in boolean expressions."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate(
            "laptop | default(false) and not (desktop | default(false))",
            {"laptop": True}
        ) is True
        assert evaluator.evaluate(
            "laptop | default(false) and not (desktop | default(false))",
            {"desktop": True}
        ) is False

    def test_invalid_syntax_raises_evaluation_error(self):
        """Invalid Jinja2 syntax should raise EvaluationError."""
        evaluator = Jinja2Evaluator()
        with pytest.raises(EvaluationError, match="Failed to evaluate"):
            evaluator.evaluate("unclosed (parenthesis", {})

    def test_nested_dict_access_with_default(self):
        """Default filters should work with nested dict access."""
        evaluator = Jinja2Evaluator()
        context = {"laptop": {}}
        assert evaluator.evaluate("laptop.trackpad | default(false)", context) is False
        assert evaluator.evaluate("laptop.trackpad | default(true)", context) is True



class TestDictEvaluator:
    """Test DictEvaluator expression evaluation."""

    def test_mapped_expression_returns_correct_bool(self):
        """An expression in the mapping should return its mapped boolean value."""
        evaluator = DictEvaluator({"laptop": True, "desktop": False})
        assert evaluator.evaluate("laptop", {}) is True
        assert evaluator.evaluate("desktop", {}) is False

    def test_unmapped_expression_returns_false(self):
        """An expression not in the mapping should return False."""
        evaluator = DictEvaluator({"laptop": True})
        assert evaluator.evaluate("desktop", {}) is False
        assert evaluator.evaluate("unknown", {}) is False

    def test_context_parameter_is_ignored(self):
        """The context parameter should be ignored (for protocol compatibility)."""
        evaluator = DictEvaluator({"laptop": True})
        # Context dict should not affect the result
        assert evaluator.evaluate("laptop", {"laptop": False}) is True
        assert evaluator.evaluate("laptop", {}) is True

    def test_empty_mapping_returns_false_for_all(self):
        """An empty mapping should return False for all expressions."""
        evaluator = DictEvaluator({})
        assert evaluator.evaluate("anything", {}) is False
        assert evaluator.evaluate("laptop", {}) is False

    def test_multiple_expressions(self):
        """Multiple expressions should all resolve correctly."""
        evaluator = DictEvaluator({
            "laptop": True,
            "desktop": False,
            "server": True,
        })
        assert evaluator.evaluate("laptop", {}) is True
        assert evaluator.evaluate("desktop", {}) is False
        assert evaluator.evaluate("server", {}) is True



