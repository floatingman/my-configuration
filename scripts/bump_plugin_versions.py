#!/usr/bin/env python3
"""
Bump pinned plugin versions in roles/shell/defaults/main.yml.

Queries the GitHub API for each plugin's latest tag (releases/latest,
falling back to tags for repos that don't publish releases) and rewrites
the pinned versions in place, preserving comments and formatting via
targeted line surgery (no YAML re-serialization).

Run by the scheduled workflow (.github/workflows/bump-plugin-versions.yml),
which commits the result and opens a PR.

Usage:
    python3 scripts/bump_plugin_versions.py           # rewrite + report
    python3 scripts/bump_plugin_versions.py --check   # exit 1 if any pin is stale

GITHUB_TOKEN (optional) raises the API rate limit from 60/hour; the
1-2 queries per repo fit comfortably in the unauthenticated budget.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULTS_PATH = (
    Path(__file__).resolve().parent.parent / "roles" / "shell" / "defaults" / "main.yml"
)

# The TPM repo URL lives in tasks/tmux.yml rather than the defaults file, so
# its repo mapping is carried here. Plugin repos are read from defaults.
TPM_REPO = "tmux-plugins/tpm"
TPM_VAR_LINE = re.compile(r'^(shell_tpm_version:\s*")([^"]+)(")')
REPO_LINE = re.compile(r'^(\s+-\s+repo:\s*")([^"]+)(")')
VERSION_LINE = re.compile(r'^(\s+version:\s*")([^"]+)(")')


def github_get(path: str, token: str | None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "plugin-version-bumper",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def latest_tag(repo: str, token: str | None) -> str:
    """Latest release tag, or the newest tag for repos without releases."""
    try:
        return github_get(f"/repos/{repo}/releases/latest", token)["tag_name"]
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    return github_get(f"/repos/{repo}/tags?per_page=1", token)[0]["name"]


def repo_slug(repo_url: str) -> str:
    """https://github.com/owner/name(.git) -> owner/name"""
    match = re.match(r"^https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", repo_url)
    if not match:
        raise ValueError(f"Unsupported repo URL: {repo_url}")
    return match.group(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bump pinned plugin versions in roles/shell/defaults/main.yml",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if any pinned version is behind upstream (no file rewrite)",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or None
    lines = DEFAULTS_PATH.read_text().splitlines()

    # Pass 1: collect the repo slug governing each line.
    slug_at: dict[int, str] = {}
    current_repo: str | None = None
    slugs = {TPM_REPO}
    for idx, line in enumerate(lines):
        if TPM_VAR_LINE.match(line):
            slug_at[idx] = TPM_REPO
        elif match := REPO_LINE.match(line):
            current_repo = repo_slug(match.group(2))
            slugs.add(current_repo)
        elif VERSION_LINE.match(line):
            if current_repo:
                slug_at[idx] = current_repo
                current_repo = None

    # Pass 2: query upstream once per repo.
    upstream = {slug: latest_tag(slug, token) for slug in sorted(slugs)}

    # Pass 3: find stale pins.
    updates: dict[int, tuple[str, str, str]] = {}  # line -> (slug, old, new)
    for idx, slug in slug_at.items():
        match = TPM_VAR_LINE.match(lines[idx]) or VERSION_LINE.match(lines[idx])
        old = match.group(2)
        if upstream[slug] != old:
            updates[idx] = (slug, old, upstream[slug])

    if not updates:
        print("All pinned plugin versions are current.")
        return 0

    for slug, old, new in updates.values():
        print(f"- {slug}: `{old}` -> `{new}`")

    if args.check:
        return 1

    for idx, (_slug, _old, new) in updates.items():
        match = TPM_VAR_LINE.match(lines[idx]) or VERSION_LINE.match(lines[idx])
        lines[idx] = match.group(1) + new + match.group(3)
    DEFAULTS_PATH.write_text("\n".join(lines) + "\n")
    print(f"\nUpdated {len(updates)} pin(s) in {DEFAULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
