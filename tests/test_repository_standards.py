"""Repository-specific coding-standard tests for the anomaly package.

These tests intentionally inspect the production source instead of checking for
placeholder files. They codify project conventions that keep this package
maintainable as a typed, importable anomaly-monitoring library.
"""
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "kontinuum_ai_anomaly"
SOURCE_FILES = sorted(PACKAGE_ROOT.glob("*.py"))
FORBIDDEN_FUNCTION_PREFIXES = (
    "validate_",
    "enforce_",
    "ensure_",
    "harden_",
    "guard_",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _relative(path: Path) -> str:
    return str(path.relative_to(PACKAGE_ROOT.parents[0]))


def test_production_imports_are_not_hidden_inside_try_blocks():
    offenders: list[str] = []
    for path in SOURCE_FILES:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Try):
                continue
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    offenders.append(f"{_relative(path)}:{child.lineno}")

    assert offenders == []


def test_forbidden_helper_prefixes_do_not_spread_validation_across_internals():
    offenders: list[str] = []
    for path in SOURCE_FILES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                FORBIDDEN_FUNCTION_PREFIXES
            ):
                offenders.append(f"{_relative(path)}:{node.lineno}:{node.name}")

    assert offenders == []


def test_public_api_exports_resolve_to_imported_runtime_objects():
    package_init = _tree(PACKAGE_ROOT / "__init__.py")
    module = __import__("kontinuum_ai_anomaly")
    all_assignment = next(
        node for node in package_init.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    exported = ast.literal_eval(all_assignment.value)

    missing = [name for name in exported if not hasattr(module, name)]
    assert missing == []
    assert len(exported) == len(set(exported))
