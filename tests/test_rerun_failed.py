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
