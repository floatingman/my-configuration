#!/usr/bin/env python3
"""
Bump pinned asdf plugin versions in group_vars/all/base.yml.

The `asdf_plugins:` list in base.yml is the single source of truth for asdf
pins: the external ansible-role-asdf installs those versions system-wide, and
the dotfiles role renders ~/.tool-versions from the same list. This script
queries each plugin's upstream for the latest stable release and rewrites the
pinned scalars in place via targeted line surgery — comments, ordering and
formatting are preserved (mirrors scripts/bump_base_versions.py).

Upstream sources (audited 2026-09):
  - GitHub `releases/latest` (respects upstream prerelease flags), falling
    back to newest-first tags for repos that publish no releases
    (aws/aws-cli).
  - golang: go.dev/dl/?mode=json — golang/go publishes no GitHub releases and
    its tag listing is not newest-first.
  - gcloud: unmanaged — Google publishes no queryable release feed
    (release notes live on cloud.google.com; the cloud-sdk-docker tag mirror
    stopped tracking at 427.0.0).

Run by the monthly job in .github/workflows/bump-versions.yml, which commits
the result together with the base.yml binary bumps and opens a PR.

Usage:
    python3 scripts/bump_asdf_versions.py           # rewrite + report
    python3 scripts/bump_asdf_versions.py --check   # exit 1 if any pin is stale or unmanageable

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
from typing import Any

BASE_YML = (
    Path(__file__).resolve().parent.parent / "group_vars" / "all" / "base.yml"
)

STALE_YEARS = 3
PRERELEASE_RE = re.compile(r"(alpha|beta|rc|dev|pre|nightly)", re.IGNORECASE)
GODEV_URL = "https://go.dev/dl/?mode=json"


@dataclass(frozen=True)
class Plugin:
    """An asdf plugin pin in base.yml's asdf_plugins list.

    repo:         GitHub owner/name for release/tag queries (None for
                  non-GitHub sources).
    source:       'github' -> GitHub API; 'godev' -> go.dev/dl JSON feed.
    tag_prefix:   prefix on the upstream tag, stripped to form the asdf
                  version scalar ('v' for most, 'go' for golang, '' otherwise).
    underscore_dots: ruby tags versions v3_4_7; asdf scalars use 3.4.7.
    """

    repo: str | None
    source: str  # 'github' | 'godev'
    tag_prefix: str
    underscore_dots: bool = False


# Upstream mapping verified against each plugin's current asdf version
# resolution and the upstream's release/tags feed (2026-09 audit).
MANIFEST = {
    "awscli": Plugin("aws/aws-cli", "github", ""),
    "concourse": Plugin("concourse/concourse", "github", "v"),
    "dotnet-core": Plugin("dotnet/sdk", "github", "v"),
    "golang": Plugin(None, "godev", "go"),
    "helm": Plugin("helm/helm", "github", "v"),
    "kubectl": Plugin("kubernetes/kubernetes", "github", "v"),
    "minikube": Plugin("kubernetes/minikube", "github", "v"),
    "nodejs": Plugin("nodejs/node", "github", "v"),
    "opentofu": Plugin("opentofu/opentofu", "github", "v"),
    "packer": Plugin("hashicorp/packer", "github", "v"),
    "ruby": Plugin("ruby/ruby", "github", "v", underscore_dots=True),
    "terraform": Plugin("hashicorp/terraform", "github", "v"),
}

# asdf plugins without a queryable upstream — documented so nobody has to
# rediscover why the bot ignores them.
UNMANAGED = {
    "gcloud": "Google publishes no queryable release feed (release notes on "
    "cloud.google.com; the cloud-sdk-docker tag mirror stopped tracking at "
    "427.0.0).",
}


def is_prerelease(tag: str) -> bool:
    return bool(PRERELEASE_RE.search(tag))


def pick_latest_tag(tags: list[str]) -> str | None:
    """Newest non-prerelease tag from a newest-first tag list (tag fallback)."""
    for tag in tags:
        if not is_prerelease(tag):
            return tag
    return None


def tag_to_version(tag: str, plugin: Plugin) -> str:
    """asdf version scalar implied by an upstream tag."""
    version = tag
    if plugin.tag_prefix and version.startswith(plugin.tag_prefix):
        version = version[len(plugin.tag_prefix):]
    if plugin.underscore_dots:
        version = version.replace("_", ".")
    return version


def version_to_tag(version: str, plugin: Plugin) -> str:
    """Full upstream tag implied by the asdf scalar currently in base.yml."""
    if plugin.underscore_dots:
        version = version.replace(".", "_")
    return plugin.tag_prefix + version


def is_stale(published_iso: str, today: datetime.date | None = None) -> bool:
    """True when the upstream's latest release is older than STALE_YEARS."""
    if not published_iso:
        return False
    if today is None:
        today = datetime.date.today()
    published = datetime.date.fromisoformat(published_iso.split("T")[0])
    return (today - published).days > int(STALE_YEARS * 365.25)


def github_get(path: str, token: str | None) -> Any:
    headers = {"User-Agent": "asdf-version-bot", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def latest_release(repo: str, token: str | None) -> tuple[str | None, str]:
    """(tag, published_iso) for the latest stable release.

    Uses /releases/latest (upstream's own stable flag), falling back to the
    newest-first tag list with prereleases filtered out for repos that
    publish no GitHub releases (aws/aws-cli).
    """
    try:
        data = github_get(f"/repos/{repo}/releases/latest", token)
        return data["tag_name"], data.get("published_at", "")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    tags = [
        t["name"]
        for t in github_get(f"/repos/{repo}/tags?per_page=100", token)
    ]
    return pick_latest_tag(tags), ""


def latest_golang(token: str | None) -> tuple[str | None, str]:
    """Newest stable Go release from the official go.dev download feed."""
    req = urllib.request.Request(GODEV_URL, headers={"User-Agent": "asdf-version-bot"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        releases = json.load(resp)
    for release in releases:
        if release.get("stable"):
            return release["version"], ""
    return None, ""


def latest_for(plugin: Plugin, token: str | None) -> tuple[str | None, str]:
    if plugin.source == "godev":
        return latest_golang(token)
    assert plugin.repo is not None
    return latest_release(plugin.repo, token)


def scan_plugin_names(text: str) -> list[str]:
    """Plugin names under asdf_plugins, in file order."""
    match = re.search(r"^asdf_plugins:\s*$", text, re.M)
    if not match:
        return []
    names = []
    for line in text[match.end():].splitlines():
        if re.match(r"^\S", line):
            break  # next top-level key — asdf_plugins block ended
        entry = re.match(r'^\s+-\s+name:\s*"([^"]+)"', line)
        if entry:
            names.append(entry.group(1))
    return names


def undocumented_plugins(text: str) -> list[str]:
    known = set(MANIFEST) | set(UNMANAGED)
    return [name for name in scan_plugin_names(text) if name not in known]


def rewrite_plugin(text: str, name: str, new_version: str) -> tuple[str, str, str]:
    """Rewrite the versions: item and global: scalar of one plugin.

    Returns (text, old, new). Raises ValueError when the plugin block is not
    the single-version shape the role expects (multiple versions or missing
    global) — such plugins are reported, not rewritten.
    """
    name_re = re.compile(rf'^(\s+-\s+name:\s*)"{re.escape(name)}"(\s*)$', re.M)
    name_match = name_re.search(text)
    if not name_match:
        raise ValueError(f"plugin {name} not found under asdf_plugins in base.yml")
    block = text[name_match.end():]
    block = block[: re.search(r"^\S|^\s+-\s+name:", block, re.M).start()]

    versions = re.findall(r"^\s+-\s+(\S+)\s*$", block, re.M)
    if len(versions) != 1:
        raise ValueError(
            f"plugin {name} pins {len(versions)} versions — manual review required"
        )
    global_match = re.search(r"^(\s+global:\s*)(\S+)(?=\s*$)", block, re.M)
    if not global_match:
        raise ValueError(f"plugin {name} has no global: key")

    old = versions[0]
    # Each replacement is anchored to its own unique span: the versions item
    # is the only "- <scalar>" list line in the block, the global scalar is
    # the only "global: <scalar>" line. Surrounding text is untouched.
    version_line = re.search(rf"^(\s+-\s+){re.escape(old)}(?=\s*$)", block, re.M)
    updated_block = block.replace(version_line.group(0),
                                  f"{version_line.group(1)}{new_version}", 1)
    updated_block = updated_block.replace(
        global_match.group(0), f"{global_match.group(1)}{new_version}", 1)
    return text.replace(block, updated_block, 1), old, new_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any pin is stale, unmanageable, or a query/error occurs (no writes)")
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN") or None
    text = BASE_YML.read_text()

    undocumented = undocumented_plugins(text)
    for name in undocumented:
        print(f"WARNING: asdf plugin {name} has no MANIFEST entry — the bot will not manage it")

    report: list[str] = []
    drift = False
    for name, plugin in sorted(MANIFEST.items()):
        try:
            tag, published = latest_for(plugin, token)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError) as exc:
            report.append(f"- asdf {name}: ERROR querying upstream: {exc}")
            drift = True
            continue
        if tag is None:
            report.append(f"- asdf {name}: no stable release/tag found upstream")
            continue
        note = ""
        if is_stale(published):
            note = " **upstream dormant >3y — removal candidate**"
        source = plugin.repo or "go.dev/dl"
        try:
            new_text, old, _ = rewrite_plugin(text, name, tag_to_version(tag, plugin))
        except ValueError as exc:
            # --check must fail too: a block the bot cannot manage is a
            # validation failure, not a clean skip (matches the base bot's
            # NOT FOUND handling).
            report.append(f"- asdf {name}: SKIPPED — {exc}{note}")
            drift = True
            continue
        if version_to_tag(old, plugin) == tag or old == tag_to_version(tag, plugin):
            report.append(f"- asdf {name}: {old} (up to date){note}")
            continue
        report.append(
            f"- asdf {name}: {old} -> {tag_to_version(tag, plugin)} ({source} {tag}, {published or 'date n/a'}){note}"
        )
        drift = True
        if not args.check:
            text = new_text

    for name, reason in UNMANAGED.items():
        report.append(f"- asdf {name}: unmanaged — {reason}")

    print("\n".join(report))

    if args.check:
        return 1 if drift else 0

    if drift and not undocumented:
        BASE_YML.write_text(text)
    elif drift:
        print("\nNot writing: undocumented asdf plugins present — add them to MANIFEST first")

    return 0


if __name__ == "__main__":
    sys.exit(main())
