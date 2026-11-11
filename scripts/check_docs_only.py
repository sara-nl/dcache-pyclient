"""Check that only documentation changed in src/ada compared to a git ref.

Parses each module, before (at the given git ref) and after (in the
working tree), into an abstract syntax tree (AST), removes all
docstrings, and compares the trees. Comments, blank lines and formatting
are not part of the AST either, so the trees are only different when
something changed that affects how the code runs.

Usage::

    python scripts/check_docs_only.py            # compare with main
    python scripts/check_docs_only.py upstream/main

Exits with status 0 when only documentation changed, 1 otherwise.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SOURCE_DIR = "src/ada"


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """Remove the docstring from every module, class and function."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                # Keep the body non-empty, so a function that only had a
                # docstring still parses the same way.
                node.body = body[1:] or [ast.Pass()]
    return tree


def _definitions(tree: ast.AST, prefix: str = "") -> dict[str, str]:
    """Map the qualified name of every class/function to a dump of its AST."""
    result = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}{node.name}"
            result[name] = ast.dump(node)
            result.update(_definitions(node, prefix=f"{name}."))
    return result


def _parse(source: str) -> ast.AST:
    return _strip_docstrings(ast.parse(source))


def _source_at_ref(ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], capture_output=True, text=True
    )
    return result.stdout if result.returncode == 0 else None


def _files_at_ref(ref: str) -> set[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", SOURCE_DIR],
        capture_output=True, text=True, check=True,
    )
    return {line for line in result.stdout.splitlines() if line.endswith(".py")}


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "main"
    old_files = _files_at_ref(ref)
    new_files = {str(p) for p in Path(SOURCE_DIR).rglob("*.py")}
    problems = []

    for path in sorted(old_files - new_files):
        problems.append(f"{path}: removed")
    for path in sorted(new_files - old_files):
        problems.append(f"{path}: added")

    for path in sorted(old_files & new_files):
        old_tree = _parse(_source_at_ref(ref, path))
        new_tree = _parse(Path(path).read_text(encoding="utf-8"))
        if ast.dump(old_tree) == ast.dump(new_tree):
            continue
        old_defs, new_defs = _definitions(old_tree), _definitions(new_tree)
        changed = sorted(
            name for name in old_defs.keys() | new_defs.keys()
            if old_defs.get(name) != new_defs.get(name)
        )
        # Only report the innermost changed definitions: when a method
        # changed, its class changed too.
        innermost = [n for n in changed if not any(o.startswith(f"{n}.") for o in changed)]
        if innermost:
            problems.extend(f"{path}: code changed in {name}" for name in innermost)
        else:
            problems.append(f"{path}: module-level code changed")

    if problems:
        print(f"Code changed compared to {ref}, not only documentation:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"OK: only documentation changed in {SOURCE_DIR} compared to {ref}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
