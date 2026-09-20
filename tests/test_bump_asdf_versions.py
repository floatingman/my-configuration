#!/usr/bin/env python3
"""Tests for scripts/bump_asdf_versions.py.

Pure-function coverage for the parsing/line-surgery logic plus main()'s
check/write semantics against tmp_path copies. The HTTP/go.dev layer
(github_get, latest_release, latest_golang) is a thin shell and is
deliberately untested (same precedent as test_bump_base_versions.py);
network-dependent behavior is monkeypatched via latest_for. The real
base.yml is read-only here — no test writes to it.
"""

import datetime
import re

import pytest

import bump_asdf_versions as bav  # noqa: E402


class TestPrereleaseFilter:
    def test_prerelease_tags_detected(self):
        for tag in ("v1.2.0-alpha", "2.0.0-beta.1", "v3.0.0-rc2", "1.0.0-dev",
                    "v26.0.0-nightly20260101abcdef"):
            assert bav.is_prerelease(tag) is True, tag

    def test_stable_tags_pass(self):
        for tag in ("v4.1.3", "2.36.40", "v3_4_7", "go1.26.1"):
            assert bav.is_prerelease(tag) is False, tag

    def test_pick_latest_tag_skips_prereleases(self):
        assert bav.pick_latest_tag(["v2.0.0-alpha", "v1.9.0", "v1.8.0"]) == "v1.9.0"
        assert bav.pick_latest_tag(["v1.9.0", "v1.8.0"]) == "v1.9.0"
        assert bav.pick_latest_tag([]) is None
        assert bav.pick_latest_tag(["v2.0.0-rc1"]) is None


class TestTagVersionConventions:
    """tag_prefix / underscore_dots round trips, pinned to real entries."""

    def test_v_prefix_stripped(self):
        plugin = bav.MANIFEST["helm"]
        assert bav.tag_to_version("v4.2.4", plugin) == "4.2.4"
        assert bav.version_to_tag("4.1.3", plugin) == "v4.1.3"

    def test_go_prefix_stripped(self):
        plugin = bav.MANIFEST["golang"]
        assert bav.tag_to_version("go1.26.1", plugin) == "1.26.1"
        assert bav.version_to_tag("1.26.1", plugin) == "go1.26.1"

    def test_ruby_underscores_become_dots(self):
        plugin = bav.MANIFEST["ruby"]
        assert bav.tag_to_version("v4_0_6", plugin) == "4.0.6"
        assert bav.version_to_tag("3.4.7", plugin) == "v3_4_7"

    def test_awscli_bare_tag(self):
        plugin = bav.MANIFEST["awscli"]
        assert bav.tag_to_version("2.36.40", plugin) == "2.36.40"
        assert bav.version_to_tag("2.34.9", plugin) == "2.34.9"

    @pytest.mark.parametrize("name", sorted(bav.MANIFEST))
    def test_round_trip_is_identity(self, name):
        plugin = bav.MANIFEST[name]
        version = "9.9.9"
        tag = bav.version_to_tag(version, plugin)
        assert bav.tag_to_version(tag, plugin) == version


class TestStaleness:
    def test_three_year_old_release_is_stale(self):
        assert bav.is_stale("2020-01-01T00:00:00Z",
                            today=datetime.date(2024, 1, 2)) is True

    def test_recent_release_is_not_stale(self):
        assert bav.is_stale("2099-01-01T00:00:00Z",
                            today=datetime.date(2026, 9, 4)) is False

    def test_unknown_date_is_not_stale(self):
        assert bav.is_stale("") is False


# alpha/beta pin the same version: their block text is identical when both
# are followed by another plugin entry (same boundary shape) — the case
# where a text-replace-based rewrite could hit the wrong plugin.
SYNTHETIC = """\
asdf_plugins:
  - name: "alpha"
    versions:
      - 1.0.0
    global: 1.0.0
  - name: "beta"
    versions:
      - 1.0.0
    global: 1.0.0
  - name: "gamma"
    versions:
      - 3.0.0
    global: 3.0.0

base_packages:
  - curl
"""


def helm_block(version):
    return f'  - name: "helm"\n    versions:\n      - {version}\n    global: {version}'


def current_helm_version(text):
    match = re.search(
        r'^  - name: "helm"\n    versions:\n      - (\S+)\n    global: \1$',
        text,
        re.M,
    )
    assert match
    return match.group(1)


class TestRewritePlugin:
    def test_rewrites_exactly_two_scalars_in_real_base_yml(self):
        text = bav.BASE_YML.read_text()
        helm_version = current_helm_version(text)
        new_text, old, new = bav.rewrite_plugin(text, "helm", "9.9.9")
        assert (old, new) == (helm_version, "9.9.9")
        before, after = text.splitlines(), new_text.splitlines()
        assert len(before) == len(after)
        assert [(a, b) for a, b in zip(before, after) if a != b] == [
            (f"      - {helm_version}", "      - 9.9.9"),
            (f"    global: {helm_version}", "    global: 9.9.9"),
        ]

    def test_targets_the_named_plugin_when_blocks_are_identical(self):
        """The rewrite must anchor on the named plugin's position, not the
        first textually-matching block (alpha and beta have identical
        versions:/global: lines here)."""
        new_text, old, _ = bav.rewrite_plugin(SYNTHETIC, "beta", "2.0.0")
        assert old == "1.0.0"
        assert '  - name: "alpha"\n    versions:\n      - 1.0.0\n    global: 1.0.0' in new_text
        assert '  - name: "beta"\n    versions:\n      - 2.0.0\n    global: 2.0.0' in new_text
        assert '  - name: "gamma"\n    versions:\n      - 3.0.0' in new_text
        assert "2.0.0" not in new_text.split('name: "alpha"')[0].split("asdf_plugins:")[-1]

    def test_asdf_plugins_as_last_key(self):
        text = SYNTHETIC[: SYNTHETIC.index("\nbase_packages:")] + "\n"
        new_text, _, _ = bav.rewrite_plugin(text, "beta", "2.0.0")
        assert "      - 2.0.0" in new_text
        assert "      - 1.0.0" in new_text  # alpha untouched
        assert "      - 3.0.0" in new_text  # gamma untouched

    def test_missing_plugin_raises(self):
        with pytest.raises(ValueError, match="nope"):
            bav.rewrite_plugin(SYNTHETIC, "nope", "1.0")

    def test_multi_version_pin_raises(self):
        text = SYNTHETIC.replace(
            '  - name: "beta"\n    versions:\n      - 1.0.0\n    global: 1.0.0',
            '  - name: "beta"\n    versions:\n      - 1.0.0\n      - 2.0.0\n    global: 1.0.0')
        with pytest.raises(ValueError, match="2 versions"):
            bav.rewrite_plugin(text, "beta", "3.0.0")

    def test_missing_global_raises(self):
        text = SYNTHETIC.replace(
            '  - name: "beta"\n    versions:\n      - 1.0.0\n    global: 1.0.0',
            '  - name: "beta"\n    versions:\n      - 1.0.0')
        with pytest.raises(ValueError, match="global"):
            bav.rewrite_plugin(text, "beta", "3.0.0")

    def test_trailing_comment_raises_not_crashes(self):
        text = SYNTHETIC.replace(
            '  - name: "beta"\n    versions:\n      - 1.0.0\n    global: 1.0.0',
            '  - name: "beta"\n    versions:\n      - 1.0.0  # latest\n    global: 1.0.0')
        with pytest.raises(ValueError):
            bav.rewrite_plugin(text, "beta", "3.0.0")


class TestScanAndCoverage:
    def test_scan_finds_plugin_names(self):
        assert bav.scan_plugin_names(SYNTHETIC) == ["alpha", "beta", "gamma"]

    def test_scan_stops_at_next_top_level_key(self):
        assert bav.scan_plugin_names(
            "asdf_plugins:\n  - name: \"a\"\nbase_packages:\n  - curl\n") == ["a"]

    def test_undocumented_plugins_detected(self):
        text = SYNTHETIC.replace('name: "alpha"', 'name: "helm"')
        assert bav.undocumented_plugins(text) == ["beta", "gamma"]
        assert bav.undocumented_plugins(bav.BASE_YML.read_text()) == []


class TestCheckSemantics:
    """main()'s --check/write behavior against a tmp base.yml with the
    network monkeypatched out."""

    @pytest.fixture
    def base_yml(self, tmp_path, monkeypatch):
        path = tmp_path / "base.yml"
        path.write_text(bav.BASE_YML.read_text())
        monkeypatch.setattr(bav, "BASE_YML", path)
        return path

    @staticmethod
    def _run(monkeypatch, capsys, argv, latest):
        def fake_latest(plugin, token):
            if plugin.source == "godev":
                return ("go1.99.0", "")
            return latest.get(plugin.repo, ("v1.0.0", ""))
        monkeypatch.setattr(bav, "latest_for", fake_latest)
        rc = bav.main(argv)
        return rc, capsys.readouterr().out

    def test_stale_pin_fails_check_and_write_updates(self, base_yml, monkeypatch, capsys):
        helm_version = current_helm_version(base_yml.read_text())
        latest = {"helm/helm": ("v9.9.9", "2026-08-01T00:00:00Z")}
        rc, out = self._run(monkeypatch, capsys, ["--check"], latest)
        assert rc == 1 and f"helm: {helm_version} -> 9.9.9" in out
        rc, _ = self._run(monkeypatch, capsys, [], latest)
        assert rc == 0
        assert "      - 9.9.9" in base_yml.read_text()

    def test_unmanageable_block_fails_check(self, base_yml, monkeypatch, capsys):
        helm_version = current_helm_version(base_yml.read_text())
        text = base_yml.read_text().replace(
            helm_block(helm_version),
            f'  - name: "helm"\n    versions:\n      - {helm_version}\n      - 4.0.0\n    global: {helm_version}')
        base_yml.write_text(text)
        rc, out = self._run(monkeypatch, capsys, ["--check"], {})
        assert rc == 1 and "SKIPPED" in out

    def test_unresolvable_upstream_fails_check_but_write_skips_only_it(self, base_yml, monkeypatch, capsys):
        helm_version = current_helm_version(base_yml.read_text())
        latest = {"helm/helm": (None, "")}
        rc, out = self._run(monkeypatch, capsys, ["--check"], latest)
        assert rc == 1 and "no stable release/tag found upstream" in out
        rc, _ = self._run(monkeypatch, capsys, [], latest)
        assert rc == 0
        written = base_yml.read_text()
        assert f"      - {helm_version}" in written  # helm untouched — no tag known
        assert "      - 1.0.0" in written  # every other plugin moved

    def test_idempotent_second_run_writes_nothing(self, base_yml, monkeypatch, capsys):
        self._run(monkeypatch, capsys, [], {})
        first = base_yml.read_text()
        rc, _ = self._run(monkeypatch, capsys, [], {})
        assert rc == 0
        assert base_yml.read_text() == first


class TestManifestSyncsWithBaseYml:
    """Contract: every plugin in the real asdf_plugins list has a manifest
    entry (or is documented as unmanaged), and every manifest entry exists
    in base.yml. Guards against new plugins silently escaping the bot."""

    def test_base_yml_and_manifest_are_in_sync(self):
        text = bav.BASE_YML.read_text()
        assert bav.undocumented_plugins(text) == []
        names = bav.scan_plugin_names(text)
        for name in bav.MANIFEST:
            assert name in names, name

    def test_unmanaged_plugins_exist_but_are_not_managed(self):
        text = bav.BASE_YML.read_text()
        names = bav.scan_plugin_names(text)
        for name in bav.UNMANAGED:
            assert name in names, name
            assert name not in bav.MANIFEST, name
