"""Behavioral test of the resilience mechanism with a real ansible-playbook run.

Builds a scratch playbook whose structure is byte-identical (same emitter,
same shared task files) to the generated play.yml:

    pre_tasks:  include tasks/resilience/init.yml          (tags: always)
    tasks:      resilient_role_wrapper_lines(...) per role  (block/rescue)
    post_tasks: include tasks/resilience/failure-report.yml (tags: always)

with three stub roles where the middle one always fails, then proves with a
dry-run style execution (stub roles only debug/set_fact/fail; nothing on the
machine is modified) that:

* a failing role no longer aborts the run -- later roles still execute
* the failure is collected and reported clearly at the end of the run
* the machine-readable report names the role, task and error
* the play still exits non-zero so the failure cannot go unnoticed
* `--tags <role>` reruns just the affected role and exits 0 when clean
* check mode behaves the same way and still writes the report
* roles listed in resilience_fatal_roles still abort the run
* a stale report from a previous run cannot leak into a new one

Requires ansible-playbook on PATH; skipped otherwise (CI has no Ansible).
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _PROFILES_DIR  # noqa: F401  (ensures scripts/ on sys.path)
from profile_dispatcher import resilient_role_wrapper_lines

REPO_ROOT = Path(__file__).resolve().parent.parent
RESILIENCE_TASKS = REPO_ROOT / "tasks" / "resilience"

ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook")

STUB_ALPHA = """---
- name: Alpha ok task
  ansible.builtin.debug:
    msg: "alpha ran"
- name: Alpha set marker
  ansible.builtin.set_fact:
    alpha_ran: true
- name: Alpha inner-tagged task
  ansible.builtin.debug:
    msg: "alpha inner-tagged task ran"
  tags: [alpha_inner]
"""

STUB_BETA = """---
- name: Beta simulated package failure
  ansible.builtin.fail:
    msg: "failed to install package: definitely-not-a-package-xyz (target not found)"
"""

STUB_GAMMA = """---
- name: Gamma ok task
  ansible.builtin.debug:
    msg: "gamma ran after the beta failure"
"""


def _build_project(tmp_path: Path) -> Path:
    """Scratch playbook+roles mirroring the generated play.yml structure."""
    for role, body in (("alpha_ok", STUB_ALPHA), ("beta_fail", STUB_BETA), ("gamma_ok", STUB_GAMMA)):
        role_tasks = tmp_path / "roles" / role / "tasks"
        role_tasks.mkdir(parents=True)
        (role_tasks / "main.yml").write_text(body, encoding="utf-8")

    # Share the real resilience task files (symlink, so the test always runs
    # the exact artifacts play.yml includes).
    shared = tmp_path / "tasks"
    shared.mkdir()
    (shared / "resilience").symlink_to(RESILIENCE_TASKS, target_is_directory=True)

    lines = [
        "---",
        "- name: Resilience behavioral test",
        "  hosts: localhost",
        "  gather_facts: false",
        "  connection: local",
        "  pre_tasks:",
        "    - name: Initialize resilience failure collection",
        "      ansible.builtin.include_tasks:",
        "        file: tasks/resilience/init.yml",
        "        apply:",
        "          tags: always",
        "      tags: always",
        "  tasks:",
    ]
    for role, tag in (("alpha_ok", "alpha"), ("beta_fail", "beta"), ("gamma_ok", "gamma")):
        lines.extend(resilient_role_wrapper_lines(role, None, (tag,)))
    lines.extend([
        "  post_tasks:",
        "    - name: Report resilience failures at the end of the run",
        "      ansible.builtin.include_tasks:",
        "        file: tasks/resilience/failure-report.yml",
        "        apply:",
        "          tags: always",
        "      tags: always",
    ])
    playbook = tmp_path / "playbook.yml"
    playbook.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return playbook


def _run(playbook: Path, report: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ANSIBLE_CONFIG", None)
    assert ANSIBLE_PLAYBOOK is not None
    return subprocess.run(
        [
            ANSIBLE_PLAYBOOK,
            "-i", "localhost,",
            "-e", f"resilience_report_path={report}",
            *extra,
            str(playbook),
        ],
        cwd=str(playbook.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.mark.skipif(ANSIBLE_PLAYBOOK is None, reason="ansible-playbook not installed")
class TestResilientPlaybookBehavior:
    def test_failing_role_does_not_abort_and_is_reported(self, tmp_path):
        playbook = _build_project(tmp_path)
        report = tmp_path / "report.json"

        result = _run(playbook, report)

        # The run reached the end: alpha AND gamma both executed.
        assert "alpha ran" in result.stdout
        assert "gamma ran after the beta failure" in result.stdout

        # The failure was rescued, not fatal...
        assert "Continuing past role failure" in result.stdout
        assert "role 'beta_fail' failed at task" in result.stdout
        # ...and summarized at the end with the rerun hint.
        assert "1 failure(s) were rescued" in result.stdout
        assert "make rerun-failed" in result.stdout

        # Non-zero exit: everything ran, but the status reflects the failure.
        assert result.returncode != 0

        # The machine-readable report names role, task and error.
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["failure_count"] == 1
        assert data["run_tags"] == ["all"]
        failure = data["failures"][0]
        assert failure["kind"] == "role"
        assert failure["role"] == "beta_fail"
        assert failure["task"] == "Beta simulated package failure"
        assert "target not found" in failure["error"]

    def test_tag_rerun_runs_only_the_failed_role_and_exits_clean(self, tmp_path):
        playbook = _build_project(tmp_path)
        report = tmp_path / "report.json"

        result = _run(playbook, report, "--tags", "beta")

        assert result.returncode != 0  # beta still fails in isolation
        assert "alpha ran" not in result.stdout
        assert "gamma ran after the beta failure" not in result.stdout

        # A clean tag-scoped run exits 0 and rewrites the report.
        clean = _run(playbook, report, "--tags", "gamma")
        assert clean.returncode == 0
        assert "gamma ran after the beta failure" in clean.stdout
        assert "no failures had to be rescued" in clean.stdout
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["failure_count"] == 0

    def test_check_mode_still_collects_and_writes_the_report(self, tmp_path):
        playbook = _build_project(tmp_path)
        report = tmp_path / "report.json"

        result = _run(playbook, report, "--check")

        assert result.returncode != 0
        assert "gamma ran after the beta failure" in result.stdout
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["check_mode"] is True
        assert data["failures"][0]["role"] == "beta_fail"

    def test_fatal_role_aborts_but_preserves_the_report(self, tmp_path):
        playbook = _build_project(tmp_path)
        report = tmp_path / "report.json"

        # A stale report from an earlier run must not survive init verbatim.
        report.write_text(json.dumps({"failure_count": 99, "failures": []}), encoding="utf-8")

        result = _run(
            playbook,
            report,
            "-e",
            '{"resilience_fatal_roles": ["beta_fail"]}',
        )

        assert result.returncode != 0
        assert "resilience_fatal_roles" in result.stdout
        # The run aborted mid-play: gamma never ran...
        assert "gamma ran after the beta failure" not in result.stdout
        # ...but the in-progress report written after the recorded failure
        # survives the abort, so rerun-failed still has something to act on.
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["status"] == "in-progress"
        assert data["failure_count"] == 1
        assert data["failures"][0]["role"] == "beta_fail"
        assert data["failure_count"] != 99  # stale content replaced

    def test_nonzero_exit_can_be_disabled(self, tmp_path):
        playbook = _build_project(tmp_path)
        report = tmp_path / "report.json"

        result = _run(playbook, report, "-e", "resilience_exit_nonzero=false")

        # All roles ran, the failure is still reported...
        assert "gamma ran after the beta failure" in result.stdout
        assert "[role] beta_fail" in result.stdout
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["failure_count"] == 1
        # ...but the exit code stays clean when asked to.
        assert result.returncode == 0

    def test_inner_role_tags_stay_selectable(self, tmp_path):
        """TAGS=<task-level tag> must still reach tasks inside a role.

        The first resilience iteration used include_role + apply, which hid
        inner tags from tag selection (e.g. TAGS=asdf could no longer run the
        system role's asdf-tagged tasks). The wrappers now use static
        import_role, which keeps task-level tags selectable exactly like the
        old roles: keyword did.
        """
        playbook = _build_project(tmp_path)
        report = tmp_path / "report.json"

        result = _run(playbook, report, "--tags", "alpha_inner")

        assert result.returncode == 0
        assert "alpha inner-tagged task ran" in result.stdout
        assert "alpha ran" not in result.stdout  # only the tagged task ran
        assert "gamma ran after the beta failure" not in result.stdout

    def test_report_records_profile_context_for_rerun(self, tmp_path):
        """The report captures the run's profile context so rerun-failed can
        restore it (a plain configure on a host without those -e overrides
        would skip the very roles that failed)."""
        playbook = _build_project(tmp_path)
        report = tmp_path / "report.json"

        result = _run(
            playbook,
            report,
            "-e",
            '{"profile": "hyprland", "desktop_environment": "hyprland", "display_manager": "sddm"}',
        )
        assert result.returncode != 0

        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["status"] == "complete"
        assert data["profile"] == "hyprland"
        assert data["desktop_environment"] == "hyprland"
        assert data["display_manager"] == "sddm"
        assert data["disabled_roles"] == []
