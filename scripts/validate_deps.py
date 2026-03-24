#!/usr/bin/env python3
"""Validate Ansible role dependency graph.

Walks all roles/*/meta/main.yml files, builds the dependency graph, and fails
with a clear message if:
  - A dependency references a role that does not exist (MISSING)
  - The dependency graph contains a cycle (CYCLE)
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("ERROR: PyYAML not installed. Run: pip install pyyaml")


def load_graph(roles_dir: Path) -> dict[str, list[str]]:
    """Return {role_name: [dep_role_name, ...]} for every role."""
    graph: dict[str, list[str]] = {}

    for meta_file in sorted(roles_dir.glob("*/meta/main.yml")):
        role_name = meta_file.parts[-3]  # roles/<role>/meta/main.yml
        with meta_file.open() as fh:
            data = yaml.safe_load(fh) or {}

        deps_raw = data.get("dependencies") or []
        deps: list[str] = []
        for dep in deps_raw:
            if isinstance(dep, str):
                deps.append(dep)
            elif isinstance(dep, dict):
                deps.append(dep.get("role") or dep.get("name") or "")
        deps = [d for d in deps if d]  # drop empty strings

        graph[role_name] = deps

    return graph


def check_missing(graph: dict[str, list[str]]) -> list[str]:
    """Return list of error strings for deps referencing nonexistent roles."""
    errors: list[str] = []
    known = set(graph.keys())
    for role, deps in sorted(graph.items()):
        for dep in deps:
            if dep not in known:
                errors.append(f"MISSING: role '{role}' depends on '{dep}' which does not exist")
    return errors


def detect_cycles(graph: dict[str, list[str]]) -> list[str]:
    """Return list of error strings for each cycle found (DFS)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    errors: list[str] = []

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for dep in graph.get(node, []):
            if dep not in color:
                continue  # already reported as MISSING
            if color[dep] == GRAY:
                cycle_start = path.index(dep)
                cycle = " -> ".join(path[cycle_start:] + [dep])
                errors.append(f"CYCLE: {cycle}")
            elif color[dep] == WHITE:
                dfs(dep, path)
        path.pop()
        color[node] = BLACK

    for node in sorted(graph):
        if color[node] == WHITE:
            dfs(node, [])

    return errors


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    roles_dir = repo_root / "roles"

    if not roles_dir.is_dir():
        sys.exit(f"ERROR: roles directory not found at {roles_dir}")

    graph = load_graph(roles_dir)

    if not graph:
        sys.exit("ERROR: no roles found")

    print(f"Validating dependency graph for {len(graph)} roles...")

    errors = check_missing(graph) + detect_cycles(graph)

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        sys.exit(1)

    print("OK: dependency graph is valid (no missing roles, no cycles)")


if __name__ == "__main__":
    main()
