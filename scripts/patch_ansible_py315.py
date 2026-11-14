#!/usr/bin/env python3
"""Tolerate removed CPython patch targets in ansible-core's CallablePatch.

ansible-core (through at least 2.22) monkey-patches private CPython helpers
such as ``dataclasses._is_type``. CPython 3.15 removed that helper (the bug
the patch worked around was fixed upstream), so ``CallablePatch.patch()``
crashes with ``AttributeError`` at import time when module_utils loads under
Python 3.15 — which is Fedora 45's system interpreter, the only one carrying
the ``libdnf5`` bindings the package modules need.

This script edits the ``_internal/_patches/__init__.py`` inside an installed
ansible (pipx venv by default) so that:

* ``get_current_implementation()`` returns ``None`` for a missing target
  (a patch whose target no longer exists cannot be needed);
* ``is_patched()`` treats ``None`` as unpatched;
* ``patch()`` returns early when there is no unpatched implementation to
  wrap, letting the existing ``is_patch_needed()`` probe decide.

Idempotent: exits 0 without changes when the tolerance shim is already
present (or the ansible version in place no longer matches the upstream
pattern, in which case it reports that and exits 2 so stale docs get
noticed).

Usage:
    python3 scripts/patch_ansible_py315.py            # pipx 'ansible' venv
    python3 scripts/patch_ansible_py315.py --path DIR # any ansible tree
"""

from __future__ import annotations

import argparse
import pathlib
import sys

REL = pathlib.Path("ansible/module_utils/_internal/_patches/__init__.py")

OLD_GET = (
    "    def get_current_implementation(cls) -> t.Any:\n"
    '        """Get the current (possibly patched) implementation from the patch target container."""\n'
    "        return getattr(cls.target_container, cls.target_attribute)\n"
)
NEW_GET = OLD_GET.replace(
    "        return getattr(cls.target_container, cls.target_attribute)\n",
    "        # Python 3.15 removed patch targets like dataclasses._is_type (the\n"
    "        # CPython bugs they worked around were fixed upstream). A missing\n"
    "        # target means the patch cannot be needed; None lets is_patched()\n"
    "        # report False so patch() bails out via is_patch_needed().\n"
    "        return getattr(cls.target_container, cls.target_attribute, None)\n",
)

OLD_ISP = (
    "        return isinstance(cls.get_current_implementation(), PatchedTarget)"
    "  # using a protocol lets us be more resilient to module unload weirdness\n"
)
NEW_ISP = (
    "        current = cls.get_current_implementation()"
    "  # using a protocol lets us be more resilient to module unload weirdness\n"
    "        return current is not None and isinstance(current, PatchedTarget)\n"
)

OLD_PATCH = (
    "        cls.unpatched_implementation = cls.get_current_implementation()\n"
    "\n"
    "        if not cls.is_patch_needed():\n"
    "            return\n"
)
NEW_PATCH = OLD_PATCH.replace(
    "        if not cls.is_patch_needed():\n",
    "        if cls.unpatched_implementation is None or not cls.is_patch_needed():\n",
)


def find_default() -> pathlib.Path:
    home = pathlib.Path.home()
    for candidate in (
        home / ".local/share/pipx/venvs/ansible/lib",
    ):
        for py in sorted(candidate.glob("python3.*/site-packages"), reverse=True):
            if (py / REL).is_file():
                return py
    raise SystemExit("no pipx ansible venv found; pass --path explicitly")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--path",
        type=pathlib.Path,
        default=None,
        help="site-packages directory containing the ansible package "
        "(default: auto-detect the pipx 'ansible' venv)",
    )
    args = parser.parse_args()

    base = args.path if args.path else find_default()
    target = base / REL
    if not target.is_file():
        print(f"error: {target} not found", file=sys.stderr)
        return 2

    text = target.read_text()
    if NEW_GET in text and NEW_ISP in text and NEW_PATCH in text:
        print(f"already patched: {target}")
        return 0

    for old in (OLD_GET, OLD_ISP, OLD_PATCH):
        if text.count(old) != 1:
            print(
                f"error: upstream pattern not found exactly once in {target}; "
                "ansible-core changed — review the shim (see INSTALL.md).",
                file=sys.stderr,
            )
            return 2

    text = text.replace(OLD_GET, NEW_GET).replace(OLD_ISP, NEW_ISP).replace(OLD_PATCH, NEW_PATCH)
    target.write_text(text)
    print(f"patched: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
