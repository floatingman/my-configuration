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
    """Role names in generated play order from play.yml-shaped text."""
    play = yaml.safe_load(playbook_text)
    names = []
    for entry in play[0].get("roles", []):
        role = entry.get("role") if isinstance(entry, dict) else None
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
