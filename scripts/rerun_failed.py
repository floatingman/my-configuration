#!/usr/bin/env python3
"""Pick the roles to rerun from the resilience failure report.

Reads the report written at the end of every playbook run (default
``~/.cache/my-configuration/failures.json``, see tasks/resilience/
failure-report.yml), maps each failed role to its playbook tags by parsing
play.yml, and prints the comma-separated tag list for:

    make configure TAGS="<tags>"

which is what ``make rerun-failed`` runs for you.

Exit codes:
    0 - tags printed on stdout (possibly empty when there is nothing to do)
    1 - the report exists but cannot be parsed, or play.yml cannot be read

Diagnostics always go to stderr; stdout carries only the tag list.
"""

from __future__ import annotations

import argparse
import json
import os
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


def default_report_path() -> Path:
    """Report path: $RESILIENCE_FAILURES_PATH, else the playbook default."""
    env = os.environ.get(ENV_REPORT_VAR)
    if env:
        return Path(env).expanduser()
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rerun_failed.py",
        description="Derive the roles to rerun from the resilience failure report.",
    )
    parser.add_argument(
        "--report",
        default=None,
        help=f"Failure report path (default: ${ENV_REPORT_VAR} or {DEFAULT_REPORT})",
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
    args = parser.parse_args(argv)

    report_path = Path(args.report).expanduser() if args.report else default_report_path()
    report = load_report(report_path)
    if report is None:
        if not args.tags_only:
            print(
                f"No failure report at {report_path}: the last run either had no"
                " failures or did not reach the end-of-run report"
                " (e.g. it was aborted).",
                file=sys.stderr,
            )
        print("")
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
    if tags:
        print("Rerun just the affected roles with:")
        print(f'  make configure TAGS="{",".join(tags)}"')
        print("or simply: make rerun-failed")
    else:
        print("No rerunnable roles could be derived from the report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
