#!/usr/bin/env python3
"""Tests for scripts/bump_base_versions.py (PRD-176 follow-up: base.yml bot).

Pure-function coverage only: the HTTP layer is a thin shell around
latest_release() and is deliberately untested (same precedent as
bump_plugin_versions.py). base.yml is read-only here — no test writes to it.
"""

from datetime import date, timedelta

import pytest

import bump_base_versions as bbv  # noqa: E402


class TestPrereleaseFilter:
    def test_prerelease_tags_detected(self):
        for tag in ("v1.2.0-alpha", "2.0.0-beta.1", "v3.0.0-rc2", "1.0.0-dev", "0.8.1-alpha.2"):
            assert bbv.is_prerelease(tag) is True, tag

    def test_stable_tags_pass(self):
        for tag in ("v1.19.0", "2.11.0", "0.10.0", "v1.1.0", "r26"):
            assert bbv.is_prerelease(tag) is False, tag

    def test_pick_latest_tag_skips_prereleases(self):
        assert bbv.pick_latest_tag(["v2.0.0-alpha", "v1.19.0", "v1.18.0"]) == "v1.19.0"
        assert bbv.pick_latest_tag(["v1.19.0", "v1.18.0"]) == "v1.19.0"
        assert bbv.pick_latest_tag([]) is None
        assert bbv.pick_latest_tag(["v2.0.0-rc1"]) is None  # only prereleases


class TestPrefixConventions:
    """tag_prefix / var_style round trips, pinned to real manifest entries."""

    def test_url_style_strips_prefix(self):
        tool = bbv.MANIFEST["aws_vault_version"]  # URL carries v, scalar bare
        assert bbv.var_value_for("v7.14.0", tool) == "7.14.0"
        assert bbv.current_full_tag("7.13.6", tool) == "v7.13.6"

    def test_value_style_keeps_prefix(self):
        tool = bbv.MANIFEST["rke_version"]  # scalar carries v itself
        assert bbv.var_value_for("v1.8.14", tool) == "v1.8.14"
        assert bbv.current_full_tag("v1.8.4", tool) == "v1.8.4"

    @pytest.mark.parametrize("var", sorted(bbv.MANIFEST))
    def test_round_trip_is_identity(self, var):
        tool = bbv.MANIFEST[var]
        tag = "v9.9.9" if tool.tag_prefix == "v" else "9.9.9"
        value = bbv.var_value_for(tag, tool)
        assert bbv.current_full_tag(value, tool) == tag


class TestStaleness:
    def test_three_year_old_release_is_stale(self):
        old = (date.today() - timedelta(days=365 * 3 + 2)).isoformat()
        assert bbv.is_stale(old) is True

    def test_recent_release_is_not_stale(self):
        recent = (date.today() - timedelta(days=30)).isoformat()
        assert bbv.is_stale(recent) is False

    def test_empty_date_is_not_stale(self):
        assert bbv.is_stale("") is False


class TestLineSurgery:
    TEXT = (
        "# tools comment\n"
        "aws_vault_version: 7.13.6\n"
        "# a comment between entries\n"
        "bit_version: 1.1.2\n"
    )

    def test_rewrites_only_target_line(self):
        new_text, old, new = bbv.rewrite_var(self.TEXT, "aws_vault_version", "7.14.0")
        assert (old, new) == ("7.13.6", "7.14.0")
        assert new_text == (
            "# tools comment\n"
            "aws_vault_version: 7.14.0\n"
            "# a comment between entries\n"
            "bit_version: 1.1.2\n"
        )

    def test_missing_var_raises(self):
        with pytest.raises(ValueError, match="nope_version"):
            bbv.rewrite_var(self.TEXT, "nope_version", "1.0")

    def test_no_change_is_reported(self):
        new_text, old, new = bbv.rewrite_var(self.TEXT, "bit_version", "1.1.2")
        assert (old, new) == ("1.1.2", "1.1.2")
        assert new_text == self.TEXT


class TestCoverageGuard:
    def test_scan_finds_all_version_vars(self):
        vars_ = bbv.scan_version_vars(
            "a_version: 1.0\nb_version: 2.0\n# c_version: comment\n"
        )
        assert vars_ == ["a_version", "b_version"]

    def test_undocumented_vars_detected(self):
        text = "aws_vault_version: 7.13.6\nmystery_version: 9.9\n"
        assert bbv.undocumented_vars(text) == ["mystery_version"]


class TestManifestSyncsWithBaseYml:
    """Contract: every *_version scalar in the real base.yml has a manifest
    entry, and every manifest entry exists in base.yml. Guards against new
    pins silently escaping the bot and against manifest drift."""

    def test_base_yml_and_manifest_are_in_sync(self):
        text = bbv.BASE_YML.read_text()
        assert bbv.undocumented_vars(text) == []
        for var in bbv.MANIFEST:
            assert f"\n{var}:" in text, var

    def test_unmanaged_tools_have_no_version_var(self):
        text = bbv.BASE_YML.read_text()
        for name in bbv.UNMANAGED:
            assert f"\n{name}_version:" not in text, name
