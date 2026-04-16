#!/usr/bin/env python3
"""Tests for condition evaluation (DictEvaluator, overlays validation)."""

import tempfile
from pathlib import Path

import pytest

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import (  # noqa: E402
    validate_overlays,
    DictEvaluator,
    EvaluationError,
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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
