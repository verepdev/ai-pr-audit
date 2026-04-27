"""Pure AST-based import extractor.

Walks Python source and returns every `import` and `from ... import ...` reference
with its location, marking relative imports and imports inside `try/except ImportError`
blocks (the "conditional imports" the M1 detector ignores).
"""

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class ImportRef:
    """A single name brought into scope by an import statement.

    `module` is the dotted module path being imported from. `name` is the specific
    attribute pulled out of it (`None` for plain `import x`). `is_relative` is True
    for `from . import y` style. `is_conditional` is True when the statement sits
    inside the body of a `try` block whose `except` catches `ImportError`.
    """

    module: str
    name: str | None
    line: int
    col: int
    is_relative: bool
    is_conditional: bool


def extract_imports(source: str) -> list[ImportRef]:
    """Parse `source` and return every import as an `ImportRef`.

    Raises `SyntaxError` if the source is not valid Python — callers decide whether
    to propagate or swallow.
    """
    tree = ast.parse(source)
    collector = _ImportCollector()
    collector.visit(tree)
    return collector.imports


def _handler_catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return False
    if isinstance(handler.type, ast.Name):
        return handler.type.id == "ImportError"
    if isinstance(handler.type, ast.Tuple):
        return any(
            isinstance(elt, ast.Name) and elt.id == "ImportError" for elt in handler.type.elts
        )
    return False


class _ImportCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports: list[ImportRef] = []
        self._conditional_depth = 0

    def visit_Try(self, node: ast.Try) -> None:
        catches = any(_handler_catches_import_error(h) for h in node.handlers)
        if catches:
            self._conditional_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        if catches:
            self._conditional_depth -= 1
        for handler in node.handlers:
            self.visit(handler)
        for stmt in node.orelse:
            self.visit(stmt)
        for stmt in node.finalbody:
            self.visit(stmt)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ImportRef(
                    module=alias.name,
                    name=None,
                    line=node.lineno,
                    col=node.col_offset,
                    is_relative=False,
                    is_conditional=self._conditional_depth > 0,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        is_relative = node.level > 0
        module = ("." * node.level) + (node.module or "") if is_relative else (node.module or "")
        for alias in node.names:
            self.imports.append(
                ImportRef(
                    module=module,
                    name=alias.name,
                    line=node.lineno,
                    col=node.col_offset,
                    is_relative=is_relative,
                    is_conditional=self._conditional_depth > 0,
                )
            )
