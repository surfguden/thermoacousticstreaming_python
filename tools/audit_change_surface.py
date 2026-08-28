"""Report Python symbol definitions, uses, overrides, tests, and doc references."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess


SCAN_ROOTS = ("src", "tests", "tools", "hardware_tests")
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache", "dcamsdk4", "qmix_sdk_for_codex"}


@dataclass(frozen=True)
class Definition:
    name: str
    path: str
    line: int
    end_line: int
    kind: str
    owner: str | None
    bases: tuple[str, ...] = ()
    calls_super: bool = False


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ast.unparse(node)


def _calls_super_method(node: ast.AST, symbol: str) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
            continue
        if child.func.attr != symbol:
            continue
        value = child.func.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "super":
            return True
    return False


def _python_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for scan_root in SCAN_ROOTS:
        base = root / scan_root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if not EXCLUDED_PARTS.intersection(path.parts):
                files.add(path)
    return sorted(files)


def _index(root: Path) -> tuple[list[Definition], dict[str, ast.AST]]:
    definitions: list[Definition] = []
    trees: dict[str, ast.AST] = {}
    for path in _python_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError):
            continue
        trees[relative] = tree

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.classes: list[ast.ClassDef] = []

            def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
                definitions.append(
                    Definition(
                        name=node.name,
                        path=relative,
                        line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                        kind="class",
                        owner=None,
                        bases=tuple(_base_name(base) for base in node.bases),
                    )
                )
                self.classes.append(node)
                self.generic_visit(node)
                self.classes.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
                owner = self.classes[-1].name if self.classes else None
                definitions.append(
                    Definition(
                        name=node.name,
                        path=relative,
                        line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                        kind="method" if owner else "function",
                        owner=owner,
                        calls_super=_calls_super_method(node, node.name),
                    )
                )
                self.generic_visit(node)

            visit_AsyncFunctionDef = visit_FunctionDef

        Visitor().visit(tree)
    return definitions, trees


def _changed_lines(root: Path) -> dict[str, set[int]]:
    diff = _git(root, "diff", "--unified=0", "HEAD", "--", "*.py", check=False)
    changed: dict[str, set[int]] = {}
    current_path: str | None = None
    new_line = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:].replace("\\", "/")
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                new_line = int(match.group(1))
        elif current_path and line.startswith("+") and not line.startswith("+++"):
            changed.setdefault(current_path, set()).add(new_line)
            new_line += 1
        elif current_path and not line.startswith("-"):
            new_line += 1

    for path_text in _git(root, "ls-files", "--others", "--exclude-standard", "--", "*.py", check=False).splitlines():
        path = root / path_text
        if path.is_file():
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            changed[path_text.replace("\\", "/")] = set(range(1, line_count + 1))
    return changed


def changed_symbols(root: Path, definitions: list[Definition]) -> list[str]:
    lines = _changed_lines(root)
    symbols: set[str] = set()
    for definition in definitions:
        touched = lines.get(definition.path, set())
        if any(definition.line <= line <= definition.end_line for line in touched):
            symbols.add(definition.name)
    return sorted(symbols)


def _reference_rows(trees: dict[str, ast.AST], symbol: str) -> list[dict[str, object]]:
    rows: set[tuple[str, int, str]] = set()
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == symbol:
                rows.add((path, node.lineno, "name"))
            elif isinstance(node, ast.Attribute) and node.attr == symbol:
                rows.add((path, node.lineno, "attribute"))
            elif isinstance(node, ast.ImportFrom):
                if any(alias.name == symbol for alias in node.names):
                    rows.add((path, node.lineno, "import"))
    return [
        {"path": path, "line": line, "kind": kind}
        for path, line, kind in sorted(rows)
    ]


def _doc_rows(root: Path, symbol: str) -> list[dict[str, object]]:
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")
    rows: list[dict[str, object]] = []
    docs = root / "docs"
    if not docs.exists():
        return rows
    for path in sorted(docs.rglob("*.md")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line):
                rows.append({"path": path.relative_to(root).as_posix(), "line": line_number})
    return rows


def _definition_row(definition: Definition) -> dict[str, object]:
    return {
        "path": definition.path,
        "line": definition.line,
        "kind": definition.kind,
        "owner": definition.owner,
        "bases": list(definition.bases),
        "calls_super": definition.calls_super,
    }


def audit_symbols(root: Path, symbols: list[str]) -> dict[str, object]:
    root = root.resolve()
    definitions, trees = _index(root)
    class_defs = {item.name: item for item in definitions if item.kind == "class"}
    method_defs = [item for item in definitions if item.kind == "method"]

    def ancestors(class_name: str) -> set[str]:
        result: set[str] = set()
        pending = list(class_defs.get(class_name, Definition("", "", 0, 0, "", None)).bases)
        while pending:
            name = pending.pop()
            if name in result:
                continue
            result.add(name)
            if name in class_defs:
                pending.extend(class_defs[name].bases)
        return result

    ui_override_summary: list[dict[str, object]] = []
    for item in method_defs:
        if item.owner not in {"MainWindowV2", "MainWindowV3"}:
            continue
        inherited_from = sorted(
            ancestor
            for ancestor in ancestors(item.owner)
            if any(method.name == item.name and method.owner == ancestor for method in method_defs)
        )
        if inherited_from:
            ui_override_summary.append(
                {
                    "symbol": item.name,
                    "owner": item.owner,
                    "path": item.path,
                    "line": item.line,
                    "inherited_from": inherited_from,
                    "calls_super": item.calls_super,
                    "override_without_super": not item.calls_super,
                }
            )

    reports: dict[str, object] = {}
    for symbol in sorted(set(symbols)):
        symbol_defs = [item for item in definitions if item.name == symbol]
        overrides: list[dict[str, object]] = []
        for item in symbol_defs:
            if item.kind != "method" or item.owner is None:
                continue
            inherited_from = sorted(
                ancestor
                for ancestor in ancestors(item.owner)
                if any(method.name == symbol and method.owner == ancestor for method in method_defs)
            )
            if inherited_from:
                row = _definition_row(item)
                row["inherited_from"] = inherited_from
                row["override_without_super"] = not item.calls_super
                overrides.append(row)
        references = _reference_rows(trees, symbol)
        reports[symbol] = {
            "definitions": [_definition_row(item) for item in symbol_defs],
            "references": references,
            "test_references": [row for row in references if str(row["path"]).startswith("tests/")],
            "documentation_references": _doc_rows(root, symbol),
            "overrides": overrides,
            "multiple_implementations": len(symbol_defs) > 1,
        }
    return {
        "repository_root": str(root),
        "ui_inheritance_overrides": sorted(
            ui_override_summary,
            key=lambda row: (str(row["owner"]), str(row["symbol"]), int(row["line"])),
        ),
        "symbols": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--symbol", action="append", default=[], help="Symbol to audit; repeat as needed.")
    args = parser.parse_args()
    definitions, _trees = _index(args.root.resolve())
    symbols = args.symbol or changed_symbols(args.root.resolve(), definitions)
    print(json.dumps(audit_symbols(args.root, symbols), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
