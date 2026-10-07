#!/usr/bin/env python3
"""Package liveness checker for the playbook.

Verifies every package name the playbook can install on Arch against the
live official repos (archlinux.org JSON API) and the AUR (RPC v5), the same
failure classes this project hit repeatedly on fresh machines:

  * dead source URLs behind healthy packages (hey-bin, clion)
  * packages removed entirely (windsurf-next, kubecm*)
  * repo <-> AUR migrations (chezmoi/kind -> extra, xautolock -> AUR)
  * renamed packages (xorg-server-xwayland, gnu-netcat, p7zip)

Rules:
  * tasks guarded `os_family != "Archlinux"` are skipped (Debian names)
  * a name behind pacman/package that only exists in the AUR  -> MOVED
  * a name behind kewlfft.aur that only exists in the repos   -> MOVED
  * a name that exists nowhere                                -> DEAD
  * package GROUPS (e.g. gnome-extra) are allowlisted

Exit code 1 if anything is dead or misplaced. Intended for a scheduled CI
job (monthly) and manual runs: python3 scripts/package_liveness.py
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# Groups / meta-things the pacman API does not list as packages.
ALLOWED_GROUPS = {"gnome-extra"}

REPO_MODULES = ("ansible.builtin.package", "community.general.pacman")
AUR_MODULES = ("kewlfft.aur.aur",)


def flatten(name) -> list[str]:
    if isinstance(name, list):
        out = []
        for n in name:
            out.extend(flatten(n))
        return out
    if isinstance(name, str):
        return [name.strip()]
    return []


def is_arch_task(task: dict) -> bool:
    """False when the task is explicitly Debian-only."""
    cond = str(task.get("when", "")).replace("'", '"')
    if '"Debian"' in cond and "!=" not in cond:
        return False
    return 'os_family' not in cond or '!= "Archlinux"' not in cond


def extract(root: Path) -> tuple[set[str], set[str]]:
    """Return (repo_names, aur_names) referenced on Arch."""
    repo_names: set[str] = set()
    aur_names: set[str] = set()

    for path in sorted((root / "roles").glob("*/tasks/*.yml")):
        if path.name.endswith("-debian.yml"):
            continue  # included only on Debian; names are apt-side
        try:
            docs = yaml.safe_load(path.read_text()) or []
        except yaml.YAMLError:
            print(f"warn: unparseable {path}", file=sys.stderr)
            continue
        for task in docs:
            if not isinstance(task, dict) or not is_arch_task(task):
                continue
            for mod in (*REPO_MODULES, *AUR_MODULES):
                if mod in task:
                    if task[mod].get("state") == "absent":
                        continue  # removals reference dead names on purpose
                    if mod in REPO_MODULES:
                        repo_names |= set(flatten(task[mod].get("name")))
                    else:
                        aur_names |= set(flatten(task[mod].get("name")))

    base = yaml.safe_load((root / "group_vars/all/base.yml").read_text())
    repo_names |= set(base.get("base_packages", []))
    repo_names |= set(base.get("base_fonts", []))
    aur_names |= set(base.get("aur", {}).get("packages", []))
    aur_names |= set(base.get("aur_fonts", []))

    def usable(n: str) -> bool:
        return bool(n) and "{{" not in n and "*" not in n and " " not in n

    return ({n for n in repo_names if usable(n)} - ALLOWED_GROUPS,
            {n for n in aur_names if usable(n)} - ALLOWED_GROUPS)


def fetch_json(url: str, tries: int = 4) -> object:
    import time

    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "my-configuration-liveness/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


ARCH_MIRROR = "https://geo.mirror.pkgbuild.com"


def fetch_raw(url: str) -> bytes:
    import time

    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "my-configuration-liveness/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except OSError:
            if attempt == 4:
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def load_arch_repo_names() -> set[str]:
    """All package names in core/extra/multilib straight from the repo
    databases — three downloads instead of hundreds of API calls, immune
    to rate limiting. Repo .db files are zstd-compressed tars; tarfile
    handles that from Python 3.14 (pin CI to >=3.14)."""
    import io
    import tarfile

    names: set[str] = set()
    for repo in ("core", "extra", "multilib"):
        data = fetch_raw(f"{ARCH_MIRROR}/{repo}/os/x86_64/{repo}.db")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            for member in tar:
                if member.name.endswith("/desc"):
                    text = tar.extractfile(member).read().decode()
                    for block in text.split("\n\n"):
                        if block.startswith("%NAME%"):
                            names.add(block.splitlines()[1].strip())
                            break
    return names


def aur_has(name: str) -> bool:
    url = "https://aur.archlinux.org/rpc/v5/info?" + urllib.parse.urlencode({"arg[]": name})
    return bool(fetch_json(url).get("results"))


def check(root: Path) -> int:
    from concurrent.futures import ThreadPoolExecutor

    repo_names, aur_names = extract(root)
    print(f"checking {len(repo_names)} repo-side + {len(aur_names)} AUR-side names")
    print("loading core/extra/multilib databases...")
    arch_repos = load_arch_repo_names()
    print(f"  {len(arch_repos)} package names in official repos")

    def probe(name: str) -> tuple[str, bool, bool]:
        return name, name in arch_repos, aur_has(name)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = {n: (r, a) for n, r, a
                        in pool.map(probe, sorted(repo_names | aur_names))}
    except OSError as exc:
        print(f"error querying package APIs: {exc}", file=sys.stderr)
        return 2

    problems = []
    for name in sorted(repo_names):
        in_repo, in_aur = statuses[name]
        if not in_repo and not in_aur:
            problems.append(f"DEAD  {name}: in no repo and not in AUR")
        elif not in_repo:
            problems.append(f"MOVED {name}: official-repo task, but package only exists in the AUR")

    for name in sorted(aur_names):
        in_repo, in_aur = statuses[name]
        if not in_repo and not in_aur:
            problems.append(f"DEAD  {name}: AUR task, package exists nowhere")
        elif not in_aur:
            problems.append(f"MOVED {name}: AUR task, but package now lives in official repos")

    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} problem(s) found")
        return 1
    print("all package names alive and correctly sourced")
    return 0


def selftest() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "roles/ok/tasks").mkdir(parents=True)
        (root / "group_vars/all").mkdir(parents=True)
        (root / "roles/ok/tasks/main.yml").write_text(
            "- name: arch task\n"
            "  ansible.builtin.package:\n"
            "    name: [realpkg, '{{ templated }}']\n"
            "- name: debian task\n"
            "  ansible.builtin.package:\n"
            "    name: debian-only-name\n"
            "  when: ansible_facts['os_family'] != \"Archlinux\"\n"
            "- name: aur task\n"
            "  kewlfft.aur.aur:\n"
            "    name: aur-only-pkg\n"
        )
        (root / "group_vars/all/base.yml").write_text(
            "base_packages: [basepkg, gnome-extra]\n"
            "base_fonts: []\n"
            "aur:\n  packages: [aurpkg]\n"
            "aur_fonts: []\n"
        )
        repo, aur = extract(root)
        assert "realpkg" in repo and "basepkg" in repo, repo
        assert "debian-only-name" not in repo, repo
        assert "{{ templated }}" not in repo, repo
        assert "gnome-extra" not in repo, repo
        assert {"aur-only-pkg", "aurpkg"} <= aur, aur
        print("selftest ok")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--selftest", action="store_true",
                    help="run extractor selftest without network")
    args = ap.parse_args()
    return selftest() if args.selftest else check(Path(args.root))


if __name__ == "__main__":
    sys.exit(main())
