#!/usr/bin/env python3
"""Golden-JSON characterization harness for the resolve-role-manifest wire.

PRD-176 Slice 1 (issue #177): pins the stdout of the `resolve-role-manifest`
CLI subcommand for 60 cases — 6 profiles x {Archlinux, Debian} x 5 host_vars
shapes — captured from the pre-refactor implementation.

Purpose: the ManifestResolver refactor (FR1-FR3) must be behavior-neutral
(golden diff empty), and the sequenced behavior commits (FR4-FR6) must show
diffs confined to their accepted deltas. These goldens arbitrate every
byte-stability dispute (PRD-176 NFR2).

Goldens live in ``tests/golden/`` named ``<os>__<profile>__<host_vars>.json``.

Regenerate after an *accepted* behavior change::

    UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py -q
    git diff --stat tests/golden/   # review the delta before committing

Cross-commit diff procedure: commit goldens on the pre-refactor HEAD; on a
refactor branch re-run without UPDATE_GOLDEN — any behavioral change fails
the test with a byte-level mismatch (``git diff tests/golden/`` after
regenerating shows exactly what moved).
"""

import json
import os
from itertools import product
from pathlib import Path

import pytest

from conftest import _PROFILES_DIR  # noqa: E402
from profile_dispatcher import main  # noqa: E402

PROFILES = ["headless", "i3", "hyprland", "gnome", "awesomewm", "kde"]
OS_FAMILIES = ["Archlinux", "Debian"]

# Host_vars shapes from PRD-176 FR3. Order matters: it fixes golden filenames.
HOST_VARS_CASES = {
    "default": {},
    "laptop_true": {"laptop": True},
    "bluetooth_disabled": {"bluetooth": {"disable": True}},
    "user_env_false": {"user_environment": False},
    "dotfiles_true": {"dotfiles_config": True},
}

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# Keep --profiles-dir explicit (absolute) so results are cwd-independent.
_MATRIX_PARAMS = [
    (os_family, profile, hv_name)
    for os_family, profile, hv_name in product(OS_FAMILIES, PROFILES, HOST_VARS_CASES)
]


def _golden_name(os_family: str, profile: str, hv_name: str) -> str:
    return f"{os_family}__{profile}__{hv_name}.json"


def _run_case(os_family: str, profile: str, hv_name: str, capsys) -> str:
    """Run one resolve-role-manifest case in-process and return stdout."""
    host_vars = HOST_VARS_CASES[hv_name]
    argv = [
        "resolve-role-manifest",
        "--profile",
        profile,
        "--os-family",
        os_family,
        "--host-vars",
        json.dumps(host_vars),
        "--profiles-dir",
        _PROFILES_DIR,
    ]
    rc = main(argv)
    out = capsys.readouterr().out
    assert rc == 0, f"{_golden_name(os_family, profile, hv_name)}: rc={rc}"
    json.loads(out)  # stdout must be valid JSON
    return out


class TestGoldenMatrix:
    """60-case golden matrix over the resolve-role-manifest wire (PRD-176 FR3)."""

    @pytest.mark.parametrize(
        "os_family,profile,hv_name", _MATRIX_PARAMS, ids=[_golden_name(*p) for p in _MATRIX_PARAMS]
    )
    def test_stdout_matches_golden(self, os_family, profile, hv_name, capsys):
        out = _run_case(os_family, profile, hv_name, capsys)
        golden = GOLDEN_DIR / _golden_name(os_family, profile, hv_name)
        if os.environ.get("UPDATE_GOLDEN") == "1":
            golden.parent.mkdir(parents=True, exist_ok=True)
            golden.write_text(out, encoding="utf-8")
            pytest.skip(f"regenerated {golden.name}")
        assert golden.exists(), (
            f"missing golden {golden.name}; run UPDATE_GOLDEN=1 "
            f"python -m pytest tests/test_golden.py -q to capture"
        )
        expected = golden.read_text(encoding="utf-8")
        assert out == expected, (
            f"wire output drifted for {golden.name}\n"
            f"--- golden\n+++ actual\n"
            + "\n".join(
                f"  {line}" for line in _first_diff(expected, out)
            )
        )


def _first_diff(expected: str, actual: str):
    """Yield a bounded line-level diff preview for the failure message."""
    import difflib

    diff = list(
        difflib.unified_diff(
            expected.splitlines(), actual.splitlines(), lineterm="", n=1
        )
    )
    return diff[:40] or ["(no line-level difference; check trailing bytes)"]
