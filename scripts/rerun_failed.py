#!/usr/bin/env python3
"""Pick the roles to rerun from the resilience failure report.

Reads the report written during every playbook run (default
``~/.cache/my-configuration/failures.json``; honors a ``resilience_report_path``
set in group_vars, see tasks/resilience/write-report.yml), maps each failed
role to its playbook tags by parsing play.yml, and prints the comma-separated
tag list plus the -e arguments that restore the original run's profile
context, for:

    make configure TAGS="<tags>" ANSIBLE_EXTRA="<-e ... restore args>"

which is what ``make rerun-failed`` runs for you.

Exit codes:
    0 - tags printed on stdout (possibly empty when there is nothing to do)
    1 - the report exists but cannot be parsed, or play.yml cannot be read

Diagnostics always go to stderr; stdout carries only the requested values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from profile_dispatcher import extract_playbook_roles  # noqa: E402

DEFAULT_REPORT = Path("~/.cache/my-configuration/failures.json").expanduser()
ENV_REPORT_VAR = "RESILIENCE_FAILURES_PATH"
GROUP_VARS_DIR = REPO_ROOT / "group_vars" / "all"
# group_vars precedence: base.yml first, machine-local local.yml overrides.
GROUP_VARS_FILES = ("base.yml", "local.yml")

# Profile context keys recorded in the report and restored via -e on rerun.
PROFILE_KEYS = ("profile", "display_manager", "desktop_environment")
DISABLE_FLAGS = ("i3", "hyprland", "gnome", "awesomewm", "kde")

_HOME_LOOKUP_RE = re.compile(
    r"\{\{\s*lookup\(\s*[\"']env[\"']\s*,\s*[\"']HOME[\"']\s*\)\s*\}\}", re.IGNORECASE
)


def _expand_home_lookup(value: str) -> Optional[str]:
    """Expand the lookup('env','HOME') idiom; None if other Jinja remains."""
    expanded = _HOME_LOOKUP_RE.sub(os.environ.get("HOME", "~"), value)
    if "{{" in expanded or "{%" in expanded:
        return None
    return expanded


def report_path_from_group_vars() -> Optional[Path]:
    """Read resilience_report_path from group_vars (local.yml overrides base).

    Keeps the reader on the same path the playbook writer uses when a machine
    overrides it in group_vars/all/local.yml, so `make rerun-failed` can never
    read a different (stale) report than the run just wrote.
    """
    try:
        import yaml
    except ImportError:
        return None

    path_value: Optional[str] = None
    for name in GROUP_VARS_FILES:
        gv = GROUP_VARS_DIR / name
        if not gv.is_file():
            continue
        try:
            data = yaml.safe_load(gv.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 - a broken group_vars file is fatal elsewhere
            return None
        if isinstance(data, dict) and data.get("resilience_report_path"):
            path_value = str(data["resilience_report_path"])

    if not path_value:
        return None
    expanded = _expand_home_lookup(path_value)
    if expanded is None:
        print(
            "note: group_vars resilience_report_path uses unsupported Jinja;"
            " falling back to the default report path",
            file=sys.stderr,
        )
        return None
    return Path(expanded).expanduser()


def default_report_path() -> Path:
    """Report path: $RESILIENCE_FAILURES_PATH, group_vars, else the default."""
    env = os.environ.get(ENV_REPORT_VAR)
    if env:
        return Path(env).expanduser()
    from_group_vars = report_path_from_group_vars()
    if from_group_vars is not None:
        return from_group_vars
    return DEFAULT_REPORT


def load_report(path: Path) -> Optional[dict]:
    """Load the failure report; None when missing or empty."""
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: cannot parse failure report {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    return data if isinstance(data, dict) else None


def role_to_tags_map(playbook_path: Path) -> dict:
    """Map role name -> tag list from play.yml (resilient wrapper format)."""
    import yaml

    try:
        with open(playbook_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as exc:
        print(f"error: cannot parse playbook {playbook_path}: {exc}", file=sys.stderr)
        raise SystemExit(1)

    mapping: dict = {}
    for entry in extract_playbook_roles(data):
        if entry.role not in mapping and entry.tags:
            mapping[entry.role] = list(entry.tags)
    return mapping


def failed_role_tags(report: dict, playbook_path: Path) -> List[str]:
    """Ordered, deduplicated tags covering every failure in the report."""
    failures = report.get("failures", [])
    if not isinstance(failures, list):
        return []

    tag_map = role_to_tags_map(playbook_path)
    tags: List[str] = []
    unmapped: List[str] = []

    for failure in failures:
        if not isinstance(failure, dict):
            continue
        role = failure.get("role")
        if not role:
            continue
        role_tags = tag_map.get(role)
        if role_tags is None:
            unmapped.append(str(role))
            continue
        for tag in role_tags:
            if tag not in tags:
                tags.append(tag)

    if unmapped:
        print(
            "note: failure role(s) not present in play.yml (no tag to rerun,"
            " fix or remove them): " + ", ".join(sorted(set(unmapped))),
            file=sys.stderr,
        )
    return tags


def profile_restore_args(report: dict) -> List[str]:
    """-e arguments restoring the failed run's profile context.

    A plain `make configure` on a host whose local vars select a different
    (or no) profile would skip the very roles that failed -- e.g. a failed
    hyprland role is skipped when nothing sets desktop_environment=hyprland.
    Restoring the recorded values makes the rerun re-select them.
    """
    args: List[str] = []
    for key in PROFILE_KEYS:
        value = report.get(key)
        if isinstance(value, str) and value.strip():
            args.append(f"-e {key}={value.strip()}")
    disabled = report.get("disabled_roles")
    if isinstance(disabled, list):
        for role in disabled:
            if role in DISABLE_FLAGS:
                args.append(f"-e disable_{role}=true")
    return args


def _warn_incomplete(report: dict) -> None:
    status = report.get("status")
    if status and status != "complete":
        print(
            f"note: the report status is '{status}' (the run did not reach its"
            " end-of-run report); the failures listed are those collected"
            " before the abort and may be partial",
            file=sys.stderr,
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rerun_failed.py",
        description="Derive the roles to rerun from the resilience failure report.",
    )
    parser.add_argument(
        "--report",
        default=None,
        help=f"Failure report path (default: ${ENV_REPORT_VAR}, group_vars resilience_report_path, or {DEFAULT_REPORT})",
    )
    parser.add_argument(
        "--playbook",
        default=str(REPO_ROOT / "play.yml"),
        help="play.yml used to map role names to tags (default: repo play.yml)",
    )
    parser.add_argument(
        "--tags-only",
        action="store_true",
        help="Print only the comma-separated tag list (for scripting)",
    )
    parser.add_argument(
        "--extra-vars-only",
        action="store_true",
        help="Print only the -e arguments restoring the failed run's profile context",
    )
    args = parser.parse_args(argv)

    report_path = Path(args.report).expanduser() if args.report else default_report_path()
    report = load_report(report_path)
    if report is None:
        if not args.tags_only and not args.extra_vars_only:
            print(
                f"No failure report at {report_path}: the last run either had no"
                " failures or did not reach the end-of-run report"
                " (e.g. it was aborted).",
                file=sys.stderr,
            )
        print("")
        return 0

    _warn_incomplete(report)

    if args.extra_vars_only:
        print(" ".join(profile_restore_args(report)))
        return 0

    tags = failed_role_tags(report, Path(args.playbook))
    failures = report.get("failures", [])

    if not failures:
        if not args.tags_only:
            print(
                f"Nothing to rerun: the last run ({report_path}) recorded no failures.",
                file=sys.stderr,
            )
        print("")
        return 0

    if args.tags_only:
        print(",".join(tags))
        return 0

    print(f"Failure report: {report_path}")
    print(f"Failures recorded: {len(failures)}")
    for failure in failures:
        if isinstance(failure, dict):
            where = failure.get("role", "?")
            if failure.get("package"):
                where += f" (package {failure['package']})"
            print(f"  - {where}: {failure.get('error', '?')}")
    print()
    extra = profile_restore_args(report)
    if tags:
        print("Rerun just the affected roles with:")
        line = f'  make configure TAGS="{",".join(tags)}"'
        if extra:
            line += f' ANSIBLE_EXTRA="{" ".join(extra)}"'
        print(line)
        print("or simply: make rerun-failed")
    else:
        print("No rerunnable roles could be derived from the report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
