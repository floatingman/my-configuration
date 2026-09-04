#!/usr/bin/env python3
"""
Bump pinned binary versions in group_vars/all/base.yml.

The `binaries:` entries download directly from upstream release assets; their
versions live in `*_version:` scalars that the URLs interpolate via Jinja.
This script queries each tool's GitHub API for the latest stable release
(`releases/latest`, falling back to tags with prereleases filtered out) and
rewrites the pinned scalars in place via targeted line surgery — comments,
ordering and formatting are preserved.

Managed tools are declared in MANIFEST below. The manifest is also the
exclusion list: entries may be `unmanaged` (no usable versioned upstream) or
`exempt` (deliberately frozen, with a reason). Every `*_version:` scalar in
base.yml must have a manifest entry; undocumented scalars are reported as
warnings so new pins can't silently escape the bot.

Run by the monthly job in .github/workflows/bump-versions.yml, which commits
the result and opens a PR.

Usage:
    python3 scripts/bump_base_versions.py           # rewrite + report
    python3 scripts/bump_base_versions.py --check   # exit 1 if any pin is stale

GITHUB_TOKEN (optional) raises the API rate limit from 60/hour.
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE_YML = (
    Path(__file__).resolve().parent.parent / "group_vars" / "all" / "base.yml"
)

STALE_YEARS = 3
PRERELEASE_RE = re.compile(r"(alpha|beta|rc|dev|pre)", re.IGNORECASE)


@dataclass(frozen=True)
class Tool:
    """A versioned binary in base.yml.

    tag_prefix: prefix on the upstream tag ('v' for most, '' otherwise).
    var_style:  'url'  -> the prefix lives in the URL template; the scalar is bare.
                'value'-> the scalar carries the prefix itself.
    """

    repo: str
    tag_prefix: str
    var_style: str  # 'url' | 'value'


# tag_prefix / var_style verified against each entry's URL template in base.yml
# and the upstream's current release assets (2026-09 audit).
MANIFEST = {
    "aws_vault_version": Tool("ByteNess/aws-vault", "v", "url"),
    "bit_version": Tool("chriswalz/bit", "v", "url"),
    "dog_version": Tool("ogham/dog", "v", "value"),
    "gh_md_toc_version": Tool("ekalinin/github-markdown-toc", "", "url"),
    "git_quick_stats_version": Tool("arzzen/git-quick-stats", "", "url"),
    "prettyping_version": Tool("denilsonsa/prettyping", "v", "value"),
    "rke_version": Tool("rancher/rke", "v", "value"),
    "tfswitch_version": Tool("warrensbox/terraform-switcher", "v", "url"),
}

# base.yml binaries without a version variable — documented so nobody has to
# rediscover why the bot ignores them.
UNMANAGED = {
    "hey": "storage.googleapis.com bucket URL is always-latest by design; "
    "upstream (rakyll/hey) publishes no releases.",
    "aws-iam-authenticator": "version is baked into the EKS S3 asset path and "
    "tracks the EKS platform, not upstream releases.",
}


def is_prerelease(tag: str) -> bool:
    return bool(PRERELEASE_RE.search(tag))


def pick_latest_tag(tags: list[str]) -> str | None:
    """Newest non-prerelease tag from a newest-first tag list (tag fallback)."""
    for tag in tags:
        if not is_prerelease(tag):
            return tag
    return None


def var_value_for(tag: str, tool: Tool) -> str:
    """Scalar value to write for an upstream tag, per the entry's convention."""
    if tool.var_style == "url":
        assert tag.startswith(tool.tag_prefix), f"{tag} missing prefix {tool.tag_prefix!r}"
        return tag[len(tool.tag_prefix):]
    return tag


def current_full_tag(value: str, tool: Tool) -> str:
    """Full upstream tag implied by the scalar currently in base.yml."""
    return value if tool.var_style == "value" else tool.tag_prefix + value


def is_stale(published_iso: str, today: datetime.date | None = None) -> bool:
    """True when the upstream's latest release is older than STALE_YEARS."""
    if not published_iso:
        return False
    today = today or datetime.date.today()
    published = datetime.date.fromisoformat(published_iso[:10])
    return (today - published).days > int(STALE_YEARS * 365.25)


def github_get(path: str, token: str | None) -> Any:
    headers = {"User-Agent": "base-version-bot", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def latest_release(repo: str, token: str | None) -> tuple[str | None, str]:
    """(tag, published_iso) for the latest stable release.

    Falls back to the newest non-prerelease tag for repos that publish no
    GitHub releases (published date then comes from the tag's commit, best
    effort; '' if unavailable).
    """
    try:
        rel = github_get(f"/repos/{repo}/releases/latest", token)
        return rel["tag_name"], (rel.get("published_at") or "")[:10]
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    tags = github_get(f"/repos/{repo}/tags?per_page=20", token)
    tag = pick_latest_tag([t["name"] for t in tags])
    return tag, ""


def scan_version_vars(text: str) -> list[str]:
    return re.findall(r"^(\w+_version):", text, re.M)


def undocumented_vars(text: str) -> list[str]:
    return [v for v in scan_version_vars(text) if v not in MANIFEST]


def rewrite_var(text: str, var: str, new_value: str) -> tuple[str, str, str]:
    """Replace the scalar of `var` via line surgery. Returns (text, old, new)."""
    pattern = re.compile(rf"^(?P<indent>({var}):\s*)(?P<value>\S+)\s*$", re.M)
    match = pattern.search(text)
    if not match:
        raise ValueError(f"version scalar for {var} not found in base.yml")
    old = match.group("value")
    if old == new_value:
        return text, old, new_value
    # group(0) excludes the trailing newline; replacing the exact matched span
    # leaves surrounding whitespace/newlines untouched.
    replaced = match.group("indent") + new_value
    return text.replace(match.group(0), replaced, 1), old, new_value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any pin is stale (no writes)")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or None
    text = BASE_YML.read_text()

    undocumented = undocumented_vars(text)
    for var in undocumented:
        print(f"WARNING: {var} has no MANIFEST entry — the bot will not manage it")

    report: list[str] = []
    drift = False
    for var, tool in sorted(MANIFEST.items()):
        match = re.search(rf"^{var}:\s*(\S+)", text, re.M)
        if not match:
            report.append(f"- {var}: NOT FOUND in base.yml (manifest entry stale?)")
            drift = True
            continue
        current = match.group(1)
        try:
            tag, published = latest_release(tool.repo, token)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError) as exc:
            report.append(f"- {var}: ERROR querying {tool.repo}: {exc}")
            drift = True
            continue
        if tag is None:
            report.append(f"- {var}: no stable release/tag found for {tool.repo}")
            continue
        note = ""
        if is_stale(published):
            note = " **upstream dormant >3y — removal candidate**"
        current_tag = current_full_tag(current, tool)
        if current_tag == tag:
            report.append(f"- {var}: {current} (up to date){note}")
            continue
        new_value = var_value_for(tag, tool)
        report.append(
            f"- {var}: {current} -> {new_value} ({tool.repo} {tag}, {published or 'date n/a'}){note}"
        )
        drift = True
        if not args.check:
            text, old, new_value = rewrite_var(text, var, new_value)
            assert new_value == var_value_for(tag, tool)

    for name, reason in UNMANAGED.items():
        report.append(f"- {name}: unmanaged — {reason}")

    print("\n".join(report))

    if args.check:
        return 1 if drift else 0

    if drift and not undocumented:
        BASE_YML.write_text(text)
    elif drift:
        print("\nNot writing: undocumented version vars present — add them to MANIFEST first")

    return 0


if __name__ == "__main__":
    sys.exit(main())
