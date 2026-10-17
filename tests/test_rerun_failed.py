"""Unit tests for scripts/rerun_failed.py (failed-role tag derivation).

Uses synthetic failure reports against the REAL play.yml so the role->tag
mapping (including tag != role-name cases like ansible-role-packages ->
packages) is exercised.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import rerun_failed  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAY_YML = REPO_ROOT / "play.yml"


def _write_report(tmp_path, failures, **extra):
    report = tmp_path / "failures.json"
    report.write_text(
        json.dumps({"failure_count": len(failures), "failures": failures, **extra}),
        encoding="utf-8",
    )
    return report


def test_missing_report_yields_no_tags(tmp_path, capsys):
    assert rerun_failed.main(["--report", str(tmp_path / "nope.json"), "--tags-only"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_empty_failure_list_yields_no_tags(tmp_path):
    report = _write_report(tmp_path, [])
    assert rerun_failed.main(["--report", str(report), "--tags-only"]) == 0


def test_role_failures_map_to_playbook_tags(tmp_path, capsys):
    report = _write_report(
        tmp_path,
        [
            {"kind": "role", "role": "media", "error": "boom"},
            {"kind": "role", "role": "fonts", "error": "boom"},
        ],
    )
    assert rerun_failed.main(["--report", str(report), "--tags-only"]) == 0
    tags = capsys.readouterr().out.strip().split(",")
    assert "media" in tags
    assert "fonts" in tags  # nerd-fonts shares the fonts tag; both valid


def test_tag_differs_from_role_name(tmp_path, capsys):
    report = _write_report(
        tmp_path, [{"kind": "role", "role": "ansible-role-packages", "error": "x"}]
    )
    assert rerun_failed.main(["--report", str(report), "--tags-only"]) == 0
    assert capsys.readouterr().out.strip() == "packages"


def test_package_failures_map_to_owner_role_tag(tmp_path, capsys):
    report = _write_report(
        tmp_path,
        [
            {"kind": "package", "role": "base", "package": "ghost-pkg", "error": "x"},
            {"kind": "package", "role": "aur", "package": "ghost-bin", "error": "x"},
        ],
    )
    assert rerun_failed.main(["--report", str(report), "--tags-only"]) == 0
    assert capsys.readouterr().out.strip() == "base,aur"


def test_tags_are_deduplicated_and_ordered(tmp_path, capsys):
    report = _write_report(
        tmp_path,
        [
            {"kind": "role", "role": "aur", "error": "x"},
            {"kind": "package", "role": "base", "package": "a", "error": "x"},
            {"kind": "role", "role": "aur", "error": "y"},
        ],
    )
    assert rerun_failed.main(["--report", str(report), "--tags-only"]) == 0
    assert capsys.readouterr().out.strip() == "aur,base"


def test_unknown_role_is_skipped_with_note(tmp_path, capsys):
    report = _write_report(
        tmp_path,
        [
            {"kind": "role", "role": "removed-role", "error": "x"},
            {"kind": "role", "role": "media", "error": "y"},
        ],
    )
    assert rerun_failed.main(["--report", str(report), "--tags-only"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "media"
    assert "removed-role" in captured.err


def test_invalid_json_exits_nonzero(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        rerun_failed.main(["--report", str(bad), "--tags-only"])
    assert exc.value.code == 1


def test_human_mode_prints_summary_and_command(tmp_path, capsys):
    report = _write_report(
        tmp_path,
        [{"kind": "role", "role": "media", "task": "Install media", "error": "boom"}],
    )
    assert rerun_failed.main(["--report", str(report)]) == 0
    out = capsys.readouterr().out
    assert "media: boom" in out
    assert 'make configure TAGS="media"' in out
    assert "make rerun-failed" in out


def test_report_path_from_environment(tmp_path, monkeypatch, capsys):
    report = _write_report(tmp_path, [{"kind": "role", "role": "media", "error": "x"}])
    monkeypatch.setenv(rerun_failed.ENV_REPORT_VAR, str(report))
    assert rerun_failed.main(["--tags-only"]) == 0
    assert capsys.readouterr().out.strip() == "media"


def test_real_playbook_maps_roles_to_tags():
    """Sanity: the shipped play.yml maps every wrapped role to a tag."""
    mapping = rerun_failed.role_to_tags_map(PLAY_YML)
    assert mapping.get("base") == ["base"]
    assert mapping.get("ansible-role-packages") == ["packages"]
    assert "spell" in mapping


class TestReportPathResolution:
    """The reader must use the same report path the playbook writer uses."""

    def test_group_vars_override_is_used(self, tmp_path, monkeypatch, capsys):
        gv = tmp_path / "group_vars" / "all"
        gv.mkdir(parents=True)
        (gv / "base.yml").write_text(
            "resilience_report_path: "
            "\"{{ lookup('env','HOME') }}/.cache/alt/failures.json\"\n",
            encoding="utf-8",
        )
        report = tmp_path / "failures.json"
        report.write_text(
            json.dumps({"failures": [{"kind": "role", "role": "media", "error": "x"}]}),
            encoding="utf-8",
        )
        # Point HOME so the lookup idiom resolves to the temp report
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(rerun_failed, "GROUP_VARS_DIR", gv)
        monkeypatch.delenv(rerun_failed.ENV_REPORT_VAR, raising=False)
        assert rerun_failed.default_report_path() == (
            tmp_path / ".cache" / "alt" / "failures.json"
        )

    def test_local_group_vars_overrides_base(self, tmp_path, monkeypatch):
        gv = tmp_path / "group_vars" / "all"
        gv.mkdir(parents=True)
        (gv / "base.yml").write_text(
            'resilience_report_path: "/base/path.json"\n', encoding="utf-8"
        )
        (gv / "local.yml").write_text(
            'resilience_report_path: "/local/path.json"\n', encoding="utf-8"
        )
        monkeypatch.setattr(rerun_failed, "GROUP_VARS_DIR", gv)
        assert rerun_failed.default_report_path() == Path("/local/path.json")

    def test_env_var_beats_group_vars(self, tmp_path, monkeypatch):
        gv = tmp_path / "group_vars" / "all"
        gv.mkdir(parents=True)
        (gv / "base.yml").write_text(
            'resilience_report_path: "/base/path.json"\n', encoding="utf-8"
        )
        monkeypatch.setattr(rerun_failed, "GROUP_VARS_DIR", gv)
        monkeypatch.setenv(rerun_failed.ENV_REPORT_VAR, "/env/path.json")
        assert rerun_failed.default_report_path() == Path("/env/path.json")

    def test_unresolvable_jinja_falls_back_to_default(self, tmp_path, monkeypatch):
        gv = tmp_path / "group_vars" / "all"
        gv.mkdir(parents=True)
        (gv / "base.yml").write_text(
            'resilience_report_path: "{{ playbook_dir }}/x.json"\n', encoding="utf-8"
        )
        monkeypatch.setattr(rerun_failed, "GROUP_VARS_DIR", gv)
        assert rerun_failed.default_report_path() == rerun_failed.DEFAULT_REPORT


class TestProfileRestoreDict:
    """The rerun must restore the failed run's selection context."""

    def test_profile_keys_and_disable_flags(self):
        report = {
            "profile": "hyprland",
            "display_manager": "sddm",
            "desktop_environment": "hyprland",
            "disabled_roles": ["i3", "gnome"],
        }
        restore = rerun_failed.profile_restore_dict(report, group_vars={})
        assert restore["profile"] == "hyprland"
        assert restore["display_manager"] == "sddm"
        assert restore["desktop_environment"] == "hyprland"
        assert restore["disable_i3"] is True
        assert restore["disable_gnome"] is True

    def test_values_matching_group_vars_are_not_restored(self):
        """The rerun re-reads group_vars anyway; only CLI overrides come back."""
        report = {
            "profile": "hyprland",
            "display_manager": "sddm",
            "laptop": True,
            "user_environment": True,
            "bluetooth_disable": False,
        }
        restore = rerun_failed.profile_restore_dict(
            report,
            group_vars={
                "profile": "hyprland",
                "display_manager": "sddm",
                "laptop": True,
                "bluetooth": {"disable": False},
            },
        )
        assert restore == {}  # everything matches what the rerun reads anyway

    def test_overlay_selectors_are_restored_with_native_types(self):
        report = {"laptop": True, "user_environment": False, "bluetooth_disable": True}
        restore = rerun_failed.profile_restore_dict(report, group_vars={})
        assert restore["laptop"] is True
        assert restore["user_environment"] is False
        assert restore["bluetooth"] == {"disable": True}

    def test_bluetooth_restore_keeps_other_group_vars_keys(self):
        """The override merges over the machine's dict, not replaces it."""
        restore = rerun_failed.profile_restore_dict(
            {"bluetooth_disable": True},
            group_vars={"bluetooth": {"disable": False, "future_key": "keep"}},
        )
        assert restore["bluetooth"] == {"disable": True, "future_key": "keep"}

    def test_overlay_defaults_matching_effective_state_are_skipped(self):
        # user_environment defaults to true; a report recording true on a
        # host without a group_vars override needs no restore
        restore = rerun_failed.profile_restore_dict(
            {"user_environment": True, "laptop": False}, group_vars={}
        )
        assert restore == {}

    def test_empty_context_yields_no_args(self):
        assert rerun_failed.profile_restore_dict({}, group_vars={}) == {}
        assert (
            rerun_failed.profile_restore_dict(
                {
                    "profile": "",
                    "display_manager": "",
                    "disabled_roles": [],
                    "laptop": None,
                    "user_environment": None,
                    "bluetooth_disable": None,
                },
                group_vars={},
            )
            == {}
        )

    def test_write_extra_vars_mode_prints_file_argument(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(rerun_failed, "load_group_vars", lambda: {})
        report = _write_report(
            tmp_path,
            [{"kind": "role", "role": "media", "error": "x"}],
            profile="hyprland",
            display_manager="sddm",
            laptop=True,
        )
        assert rerun_failed.main(["--report", str(report), "--write-extra-vars"]) == 0
        out = capsys.readouterr().out.strip()
        assert out.startswith("-e @")
        assert out.endswith(rerun_failed.EXTRA_VARS_FILENAME)
        # the file exists and carries native types
        data = json.loads(Path(out.split("@", 1)[1]).read_text(encoding="utf-8"))
        assert data["profile"] == "hyprland"
        assert data["laptop"] is True

    def test_write_extra_vars_removes_stale_file_when_no_overrides(self, tmp_path):
        stale = tmp_path / rerun_failed.EXTRA_VARS_FILENAME
        stale.write_text('{"stale": true}', encoding="utf-8")
        report_path = _write_report(
            tmp_path, [{"kind": "role", "role": "media", "error": "x"}]
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        arg = rerun_failed.write_extra_vars_file(report, report_path)
        assert arg == ""
        assert not stale.exists()

    def test_human_mode_shows_ansible_extra(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(rerun_failed, "load_group_vars", lambda: {})
        report = _write_report(
            tmp_path,
            [{"kind": "role", "role": "media", "error": "x"}],
            profile="hyprland",
        )
        assert rerun_failed.main(["--report", str(report)]) == 0
        out = capsys.readouterr().out
        assert 'TAGS="media" ANSIBLE_EXTRA="-e @' in out

    def test_incomplete_report_warns(self, tmp_path, capsys):
        report = _write_report(
            tmp_path,
            [{"kind": "role", "role": "media", "error": "x"}],
            status="in-progress",
        )
        assert rerun_failed.main(["--report", str(report), "--tags-only"]) == 0
        err = capsys.readouterr().err
        assert "in-progress" in err
        assert "may be partial" in err

    def test_extra_vars_argument_is_a_single_shell_word(self, tmp_path, monkeypatch):
        """The -e argument must survive unquoted $(ANSIBLE_EXTRA) expansion.

        Regression: inline JSON `{"a":1,"b":2}` is split by bash brace
        expansion when the Makefile expands ANSIBLE_EXTRA unquoted, so any
        multi-key restore crashed ansible-playbook with exit 2. A single
        `-e @/abs/path` word cannot be split, brace-expanded or globbed.
        """
        monkeypatch.setattr(rerun_failed, "load_group_vars", lambda: {})
        report_path = _write_report(
            tmp_path,
            [{"kind": "role", "role": "media", "error": "x"}],
            profile="i3",
            display_manager="lightdm",
            desktop_environment="i3",
            laptop=True,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        arg = rerun_failed.write_extra_vars_file(report, report_path)
        assert len(arg.split()) == 2  # exactly: -e @/abs/path
        path_word = arg.split()[1]
        assert "," not in path_word and "{" not in path_word
        assert path_word.startswith("@/")

    def test_extra_vars_argument_argv_shape_via_sh(self, tmp_path, monkeypatch):
        """The real executable argv: expand the argument through /bin/sh.

        Mirrors the configure recipe exactly (`$(ANSIBLE_EXTRA)` expanded
        unquoted into shell source) and asserts the two-word argv that
        ansible-playbook receives.
        """
        import subprocess

        monkeypatch.setattr(rerun_failed, "load_group_vars", lambda: {})
        report_path = _write_report(
            tmp_path,
            [{"kind": "role", "role": "media", "error": "x"}],
            profile="hyprland",
            laptop=True,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        arg = rerun_failed.write_extra_vars_file(report, report_path)
        argv = subprocess.run(
            ["/bin/sh", "-c", 'printf "%s\\n" ansible-playbook ' + arg],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        assert argv == ["ansible-playbook", "-e", arg.split()[1]]

    def test_report_path_with_spaces_falls_back_to_safe_location(self, tmp_path, monkeypatch):
        """A resilience_report_path containing spaces must not split the
        @file operand; the file moves to a space-free fallback path."""
        monkeypatch.setattr(rerun_failed, "load_group_vars", lambda: {})
        monkeypatch.setattr(
            rerun_failed, "_fallback_extra_vars_path",
            lambda: tmp_path / "safe" / "rerun-extra-vars.json",
        )
        spacey_dir = tmp_path / "run reports"
        spacey_dir.mkdir()
        report_path = spacey_dir / "failures.json"
        report_path.write_text(
            json.dumps({"failures": [{"kind": "role", "role": "media", "error": "x"}],
                        "profile": "hyprland"}),
            encoding="utf-8",
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        arg = rerun_failed.write_extra_vars_file(report, report_path)
        assert len(arg.split()) == 2
        path_word = arg.split()[1]
        assert " " not in path_word
        assert path_word.startswith("@")
        assert "safe/rerun-extra-vars.json" in path_word
        # the JSON really is at the fallback location
        assert json.loads(Path(path_word[1:]).read_text(encoding="utf-8"))["profile"] == "hyprland"
