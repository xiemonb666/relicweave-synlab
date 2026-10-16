"""Tiny unused-module-level-name checker (stdlib only) for the files this task added."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

for rel in sys.argv[1:]:
    path = Path(rel)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined[node.name] = node.lineno
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined[target.id] = node.lineno
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined[node.target.id] = node.lineno
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            pass
    exported = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            exported = {str(x.value) for x in getattr(node.value, "elts", [])}
    unused = sorted(name for name in defined
                    if name not in used and name not in exported
                    and not name.startswith("__"))
    print(f"{rel}: {len(defined)} module-level names; unused: {unused}")
