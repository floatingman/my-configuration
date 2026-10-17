"""Fresh-machine safety invariants for the generated playbook.

Bugs this suite guards against were all found the hard way, on pristine
hardware (see FRESH_MACHINE.md):

* The `aur` role creates the `aur_builder` user, but it runs in the packages
  section — AFTER roles like grub and archive that already use
  `kewlfft.aur`/`become_user: aur_builder`. On a machine where aur_builder
  does not already exist, every such task dies with "failed to set
  permissions on the temporary files ... becoming an unprivileged user".
  The base role now bootstraps the user early; this test pins that ordering
  so a future profile/section reshuffle cannot silently reintroduce it.

Pure Python + PyYAML: no Ansible required, safe for CI.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAY_YML = REPO_ROOT / "play.yml"
ROLES_DIR = REPO_ROOT / "roles"


def _ordered_role_names(playbook_text: str) -> list[str]:
    """Role names in generated play order from play.yml-shaped text.

    Understands both playbook shapes: legacy ``roles:`` entries and the
    resilient block/rescue wrappers (``tasks:`` with include_role) that
    `make generate-playbook` emits today.
    """
    play = yaml.safe_load(playbook_text)
    names = []
    for entry in play[0].get("roles", []) or []:
        role = entry.get("role") if isinstance(entry, dict) else None
        if role:
            names.append(role)
    for task in play[0].get("tasks", []) or []:
        if not isinstance(task, dict) or "block" not in task:
            continue
        for sub in task["block"]:
            if not isinstance(sub, dict):
                continue
            include = sub.get("ansible.builtin.include_role") or sub.get("include_role")
            if not include:
                continue
            role = include.get("name") if isinstance(include, dict) else include
            if role:
                names.append(role)
    return names


def _role_task_texts(role_name: str) -> list[str]:
    """Text of every tasks/*.yml under roles/<role_name> (local roles only)."""
    tasks_dir = ROLES_DIR / role_name / "tasks"
    if not tasks_dir.is_dir():
        return []
    return [p.read_text() for p in sorted(tasks_dir.rglob("*.yml"))]


def _uses_aur_become(role_name: str) -> bool:
    return any(
        "kewlfft.aur" in text or "become_user: aur_builder" in text
        for text in _role_task_texts(role_name)
    )


def test_playbook_role_order_keeps_base_before_every_aur_consumer():
    names = _ordered_role_names(PLAY_YML.read_text())
    assert "base" in names, "base role missing from generated play.yml"
    base_pos = names.index("base")
    offenders = [n for n in names[:base_pos] if _uses_aur_become(n)]
    assert not offenders, (
        "Roles running before 'base' use kewlfft.aur/become_user: aur_builder, "
        "but 'base' bootstraps the aur_builder user and the module tmp dir. "
        f"Offenders: {offenders}. Move them after 'base' (or extend the base "
        "bootstrap). See FRESH_MACHINE.md."
    )


def test_checker_detects_reversed_order_on_synthetic_play():
    """The ordering check itself must fail when base comes too late."""
    good = """
- name: play
  hosts: localhost
  roles:
    - { role: base, tags: ["base"] }
    - { role: archive, tags: ["archive"] }
"""
    bad = """
- name: play
  hosts: localhost
  roles:
    - { role: archive, tags: ["archive"] }
    - { role: base, tags: ["base"] }
"""
    # archive uses kewlfft.aur in tasks/archive-arch.yml, so the synthetic
    # reversed order must place it before base.
    good_names = _ordered_role_names(good)
    bad_names = _ordered_role_names(bad)
    for names, expect_offenders in ((good_names, False), (bad_names, True)):
        base_pos = names.index("base")
        offenders = [n for n in names[:base_pos] if _uses_aur_become(n)]
        assert bool(offenders) is expect_offenders, names


def test_resilient_packages_repo_leg_runs_before_aur_bootstrap():
    """Official-repo installs must not depend on the AUR bootstrap.

    Regression: on a pristine machine the pacman-module install of yay
    failed ("Failed to list package yay" -- yay is AUR-only), and because
    the yay bootstrap ran first, base_packages repo entries (ripgrep,
    cowsay, ...) never installed. The repo leg now runs before any
    aur_builder/yay bootstrap task, so an AUR-side problem can only ever
    block AUR packages.
    """
    path = ROLES_DIR / "resilient_packages" / "tasks" / "main.yml"
    tasks = yaml.safe_load(path.read_text())
    names = [t.get("name", "") for t in tasks if isinstance(t, dict)]

    def pos(fragment):
        indexes = [i for i, n in enumerate(names) if fragment in n]
        assert indexes, f"task containing {fragment!r} not found in {path}"
        return indexes[0]

    repo_install = pos("Install packages that live in the official repos")
    aur_builder = pos("Ensure the aur_builder user exists")
    yay_repo = pos("Ensure yay is installed from the official repos")
    yay_aur = pos("Ensure yay is built from the AUR")
    assert repo_install < aur_builder < yay_repo
    assert repo_install < yay_aur
