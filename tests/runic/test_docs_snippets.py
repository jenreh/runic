"""Guard the Python snippets embedded in ``docs/``.

The documentation carries hundreds of fenced ``python`` blocks, and nothing
checked that any of them still parsed or that the symbols they import still
existed — so a rename in ``runic/`` could leave every published example
pointing at a name that no longer resolves, with a green test run.

Blocks are parsed, never *executed*, so the guard is fast and side-effect
free.  Imports are resolved for every ``runic`` package the repo ships, add-ons
under ``packages/`` included.  Fragments that are prose rather than code (a
constructor signature, a method-chain excerpt) belong in a ``text`` fence, not a
``python`` one.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS = _REPO_ROOT / "docs"
_SKIP_DIRS = {"node_modules", ".vitepress"}
_FENCE = re.compile(r"^(\s*)```([A-Za-z0-9_+-]*)\s*$")

# Optional add-ons such as ``runic_rag_docling`` ship as separate distributions
# under ``packages/`` and are not installed into the root env.  Their public
# surface is importable from source anyway — the heavy extras behind them
# (docling, docling-core) are imported lazily — so put those source roots on the
# path and hold their docs snippets to the same standard as everything else.
_PACKAGE_ROOTS = sorted(
    package.parent
    for package in (_REPO_ROOT / "packages").glob("*/*/__init__.py")
    if package.parent.parent.joinpath("pyproject.toml").exists()
)
for _root in _PACKAGE_ROOTS:
    _entry = str(_root.parent)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


class _Block(NamedTuple):
    """One fenced ``python`` block, tagged with where it came from."""

    location: str
    source: str


class _Symbol(NamedTuple):
    """One ``from <module> import <name>`` pair found in a doc block."""

    location: str
    module: str
    name: str


def _collect_blocks() -> list[_Block]:
    blocks: list[_Block] = []
    for path in sorted(_DOCS.rglob("*.md")):
        if _SKIP_DIRS & set(path.parts):
            continue
        rel = path.relative_to(_REPO_ROOT)
        lines = path.read_text(encoding="utf-8").splitlines()
        index = 0
        while index < len(lines):
            opening = _FENCE.match(lines[index])
            if opening is None:
                index += 1
                continue
            indent, tag = opening.groups()
            closing = re.compile(rf"^{re.escape(indent)}```\s*$")
            start = index + 1
            end = start
            while end < len(lines) and not closing.match(lines[end]):
                end += 1
            if tag == "python":
                body = "\n".join(line.removeprefix(indent) for line in lines[start:end])
                blocks.append(_Block(f"{rel}:{start + 1}", body))
            index = end + 1
    return blocks


def _collect_symbols(blocks: list[_Block]) -> list[_Symbol]:
    seen: dict[tuple[str, str], _Symbol] = {}
    for block in blocks:
        try:
            tree = ast.parse(block.source)
        except SyntaxError:
            continue  # reported by test_doc_block_parses
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if node.module != "runic" and not node.module.startswith(
                ("runic.", "runic_")
            ):
                continue
            for alias in node.names:
                seen.setdefault(
                    (node.module, alias.name),
                    _Symbol(block.location, node.module, alias.name),
                )
    return sorted(seen.values(), key=lambda symbol: (symbol.module, symbol.name))


_BLOCKS = _collect_blocks()
_SYMBOLS = _collect_symbols(_BLOCKS)


def test_walker_found_the_docs() -> None:
    """Guard the guard: a walker that finds nothing would pass everything."""
    assert len(_BLOCKS) > 300, f"only {len(_BLOCKS)} python blocks found in {_DOCS}"
    assert len(_SYMBOLS) > 50, f"only {len(_SYMBOLS)} runic imports found in {_DOCS}"


@pytest.mark.parametrize("block", _BLOCKS, ids=lambda block: block.location)
def test_doc_block_parses(block: _Block) -> None:
    try:
        ast.parse(block.source)
    except SyntaxError as exc:
        pytest.fail(
            f"{block.location}: ```python block does not parse ({exc.msg}). "
            "Re-fence it as ```text if it is a signature or fragment."
        )


@pytest.mark.parametrize(
    "symbol",
    _SYMBOLS,
    ids=lambda symbol: f"{symbol.module}.{symbol.name}",
)
def test_doc_import_resolves(symbol: _Symbol) -> None:
    try:
        module = importlib.import_module(symbol.module)
    except ImportError as exc:
        pytest.fail(f"{symbol.location}: cannot import {symbol.module} ({exc})")
    assert hasattr(module, symbol.name), (
        f"{symbol.location}: {symbol.module} has no attribute {symbol.name!r}"
    )
