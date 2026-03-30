#!/usr/bin/env python3
"""
Tests for Profile Dispatcher

Unit tests for profile loading, validation, resolution, and expression evaluation.
"""

import pytest

from profile_dispatcher import (
    ConditionEvaluator,
    DictEvaluator,
    EvaluationError,
    Jinja2Evaluator,
    ResolvedProfile,
    _load_profile_inner,
    _merge_profile_data,
    _resolve_manual_mode,
    _resolve_profile_mode,
    list_profiles,
    load_profile,
    resolve,
    validate_profile,
)


# ---------------------------------------------------------------------------
# Jinja2Evaluator Tests
# ---------------------------------------------------------------------------

class TestJinja2Evaluator:
    """Tests for Jinja2-based expression evaluator."""

    def test_evaluate_truthy_variable(self):
        """Truthy variable evaluates to True."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop", {"laptop": True}) is True
        assert evaluator.evaluate("laptop", {"laptop": "yes"}) is True
        assert evaluator.evaluate("laptop", {"laptop": 1}) is True

    def test_evaluate_falsy_variable(self):
        """Falsy variable evaluates to False."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop", {"laptop": False}) is False
        assert evaluator.evaluate("laptop", {"laptop": ""}) is False
        assert evaluator.evaluate("laptop", {"laptop": 0}) is False
        assert evaluator.evaluate("laptop", {"laptop": None}) is False

    def test_evaluate_with_default_filter(self):
        """default() filter provides fallback for undefined variables."""
        evaluator = Jinja2Evaluator()
        # Variable present but falsy, default returns the falsy value
        assert evaluator.evaluate("laptop | default(false)", {"laptop": False}) is False
        # Variable absent, default provides fallback
        assert evaluator.evaluate("laptop | default(false)", {}) is False
        assert evaluator.evaluate("laptop | default(true)", {}) is True
        # Variable present and truthy, returns actual value
        assert evaluator.evaluate("laptop | default(false)", {"laptop": True}) is True

    def test_evaluate_with_is_defined_test(self):
        """is defined test checks variable existence."""
        evaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop is defined", {"laptop": True}) is True
        assert evaluator.evaluate("laptop is defined", {"laptop": None}) is True
        assert evaluator.evaluate("laptop is defined", {}) is False
        # Combining is defined with boolean operators
        assert evaluator.evaluate(
            "laptop is defined and laptop",
            {"laptop": True}
        ) is True
        assert evaluator.evaluate(
            "laptop is defined and laptop",
            {"laptop": False}
        ) is False

    def test_evaluate_nested_dict_access(self):
        """Dotted access works for nested dictionaries."""
        evaluator = Jinja2Evaluator()
        context = {
            "bluetooth": {
                "disable": False
            }
        }
        assert evaluator.evaluate("bluetooth.disable", context) is False
        assert evaluator.evaluate("not bluetooth.disable", context) is True

        context2 = {
            "bluetooth": {
                "disable": True
            }
        }
        assert evaluator.evaluate("bluetooth.disable", context2) is True
        assert evaluator.evaluate("not bluetooth.disable", context2) is False

    def test_evaluate_boolean_operators(self):
        """and, or, not operators work correctly."""
        evaluator = Jinja2Evaluator()

        # and
        assert evaluator.evaluate(
            "laptop and desktop",
            {"laptop": True, "desktop": True}
        ) is True
        assert evaluator.evaluate(
            "laptop and desktop",
            {"laptop": True, "desktop": False}
        ) is False

        # or
        assert evaluator.evaluate(
            "laptop or desktop",
            {"laptop": True, "desktop": False}
        ) is True
        assert evaluator.evaluate(
            "laptop or desktop",
            {"laptop": False, "desktop": False}
        ) is False

        # not
        assert evaluator.evaluate("not laptop", {"laptop": True}) is False
        assert evaluator.evaluate("not laptop", {"laptop": False}) is True

        # Complex expression from bluetooth.yml overlay
        context = {
            "bluetooth": {
                "disable": False
            }
        }
        assert evaluator.evaluate(
            "bluetooth is defined and not (bluetooth.disable | default(false))",
            context
        ) is True

        context2 = {
            "bluetooth": {
                "disable": True
            }
        }
        assert evaluator.evaluate(
            "bluetooth is defined and not (bluetooth.disable | default(false))",
            context2
        ) is False

    def test_evaluate_parenthesized_expressions(self):
        """Parentheses control evaluation order."""
        evaluator = Jinja2Evaluator()

        # (true or false) and false = false
        assert evaluator.evaluate(
            "(laptop or desktop) and server",
            {"laptop": True, "desktop": False, "server": False}
        ) is False

        # true or (false and false) = true
        assert evaluator.evaluate(
            "laptop or (desktop and server)",
            {"laptop": True, "desktop": False, "server": False}
        ) is True

    def test_evaluate_invalid_expression_raises(self):
        """Invalid expressions raise EvaluationError with clear message."""
        evaluator = Jinja2Evaluator()

        with pytest.raises(EvaluationError) as exc_info:
            evaluator.evaluate("undefined_var without any operator", {})

        assert "Failed to evaluate expression" in str(exc_info.value)
        assert "undefined_var without any operator" in str(exc_info.value)

    def test_evaluate_syntax_error_raises(self):
        """Syntax errors in expressions raise EvaluationError."""
        evaluator = Jinja2Evaluator()

        with pytest.raises(EvaluationError) as exc_info:
            evaluator.evaluate("laptop |", {"laptop": True})

        assert "Failed to evaluate expression" in str(exc_info.value)


# ---------------------------------------------------------------------------
# DictEvaluator Tests
# ---------------------------------------------------------------------------

class TestDictEvaluator:
    """Tests for simple dict-based evaluator."""

    def test_evaluate_mapped_expression_returns_correct_bool(self):
        """Mapped expressions return their configured boolean values."""
        evaluator = DictEvaluator({
            "laptop": True,
            "desktop": False,
            "laptop | default(false)": True,
        })

        assert evaluator.evaluate("laptop", {}) is True
        assert evaluator.evaluate("desktop", {}) is False
        assert evaluator.evaluate("laptop | default(false)", {}) is True

    def test_evaluate_unmapped_expression_returns_false(self):
        """Expressions not in mapping return False."""
        evaluator = DictEvaluator({
            "laptop": True,
        })

        assert evaluator.evaluate("desktop", {}) is False
        assert evaluator.evaluate("server", {}) is False
        assert evaluator.evaluate("unknown_expression", {}) is False

    def test_evaluate_context_ignored(self):
        """Context parameter is ignored (present for Protocol compatibility)."""
        evaluator = DictEvaluator({
            "laptop": True,
        })

        # Context is ignored, always returns the mapped value
        assert evaluator.evaluate("laptop", {"laptop": False}) is True
        assert evaluator.evaluate("laptop", {}) is True


# ---------------------------------------------------------------------------
# ConditionEvaluator Protocol Tests
# ---------------------------------------------------------------------------

class TestConditionEvaluatorProtocol:
    """Tests verifying ConditionEvaluator protocol compliance."""

    def test_jinja2_evaluator_satisfies_protocol(self):
        """Jinja2Evaluator implements ConditionEvaluator protocol."""
        evaluator: ConditionEvaluator = Jinja2Evaluator()
        assert evaluator.evaluate("laptop", {"laptop": True}) is True

    def test_dict_evaluator_satisfies_protocol(self):
        """DictEvaluator implements ConditionEvaluator protocol."""
        evaluator: ConditionEvaluator = DictEvaluator({"laptop": True})
        assert evaluator.evaluate("laptop", {}) is True


# ---------------------------------------------------------------------------
# Existing Profile Dispatcher Tests (ensure no regression)
# ---------------------------------------------------------------------------

class TestResolvedProfile:
    """Tests for ResolvedProfile dataclass."""

    def test_resolved_profile_is_immutable(self):
        """ResolvedProfile is frozen and cannot be modified after creation."""
        profile = ResolvedProfile(
            profile="test",
            display_manager="lightdm",
            has_display=True,
            desktop_environment="i3",
            is_i3=True,
            is_hyprland=False,
            is_gnome=False,
            is_awesomewm=False,
            is_kde=False,
        )

        with pytest.raises(Exception):  # FrozenInstanceError or similar
            profile.profile = "changed"


class TestLoadProfile:
    """Tests for profile loading."""

    def test_load_nonexistent_profile_raises(self):
        """Loading a non-existent profile raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            load_profile("profiles", "nonexistent")

        assert "not found" in str(exc_info.value)

    def test_load_profile_with_path_traversal_raises(self):
        """Profile names with path traversal are rejected."""
        with pytest.raises(ValueError) as exc_info:
            load_profile("profiles", "../../../etc/passwd")

        assert "invalid path characters" in str(exc_info.value)

    def test_load_profile_with_slash_raises(self):
        """Profile names with slashes are rejected."""
        with pytest.raises(ValueError) as exc_info:
            load_profile("profiles", "subdir/profile")

        assert "invalid path characters" in str(exc_info.value)


class TestMergeProfileData:
    """Tests for profile data merging."""

    def test_merge_child_scalar_overrides_parent(self):
        """Child scalar values override parent values."""
        parent = {"display_manager_default": "gdm", "desktop_environment": "gnome"}
        child = {"display_manager_default": "lightdm"}

        result = _merge_profile_data(parent, child)

        assert result["display_manager_default"] == "lightdm"
        assert result["desktop_environment"] == "gnome"  # Unchanged from parent

    def test_merge_roles_concatenates(self):
        """Role lists are concatenated (parent first, child appended)."""
        parent = {"roles": ["base", "system"]}
        child = {"roles": ["i3"]}

        result = _merge_profile_data(parent, child)

        assert result["roles"] == ["base", "system", "i3"]

    def test_merge_extends_field_ignored(self):
        """The 'extends' field is not included in merged result."""
        parent = {"roles": ["base"]}
        child = {"extends": "base", "roles": ["i3"]}

        result = _merge_profile_data(parent, child)

        assert "extends" not in result


class TestResolveManualMode:
    """Tests for manual mode resolution."""

    def test_manual_mode_with_display_manager(self):
        """Manual mode with display manager sets has_display=True."""
        result = _resolve_manual_mode(
            display_manager="lightdm",
            desktop_environment=None,
            disable_i3=False,
            disable_hyprland=False,
            disable_gnome=False,
            disable_awesomewm=False,
            disable_kde=False,
        )

        assert result.profile == "manual"
        assert result.has_display is True
        assert result.display_manager == "lightdm"

    def test_manual_mode_without_display_manager(self):
        """Manual mode without display manager sets has_display=False."""
        result = _resolve_manual_mode(
            display_manager=None,
            desktop_environment=None,
            disable_i3=False,
            disable_hyprland=False,
            disable_gnome=False,
            disable_awesomewm=False,
            disable_kde=False,
        )

        assert result.profile == "manual"
        assert result.has_display is False
        assert result.display_manager is None

    def test_manual_mode_i3_dual_desktop(self):
        """i3 is enabled by default when has_display=True and no DE specified."""
        result = _resolve_manual_mode(
            display_manager="lightdm",
            desktop_environment=None,
            disable_i3=False,
            disable_hyprland=False,
            disable_gnome=False,
            disable_awesomewm=False,
            disable_kde=False,
        )

        assert result.is_i3 is True
        assert result.is_hyprland is True

    def test_manual_mode_disable_i3(self):
        """disable_i3 flag suppresses i3 even when it would otherwise be enabled."""
        result = _resolve_manual_mode(
            display_manager="lightdm",
            desktop_environment=None,
            disable_i3=True,
            disable_hyprland=False,
            disable_gnome=False,
            disable_awesomewm=False,
            disable_kde=False,
        )

        assert result.is_i3 is False

    def test_manual_mode_specific_de(self):
        """When desktop_environment is set, only that DE is enabled."""
        result = _resolve_manual_mode(
            display_manager="gdm",
            desktop_environment="gnome",
            disable_i3=False,
            disable_hyprland=False,
            disable_gnome=False,
            disable_awesomewm=False,
            disable_kde=False,
        )

        assert result.is_gnome is True
        assert result.is_i3 is False
        assert result.is_hyprland is False
