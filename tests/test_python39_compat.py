import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Python39CompatibilityTests(unittest.TestCase):
    def test_runtime_does_not_import_datetime_utc_constant(self):
        for path in (PROJECT_ROOT / "core").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "from datetime import UTC",
                text,
                f"{path.relative_to(PROJECT_ROOT)} uses datetime.UTC, unavailable on Python 3.9",
            )

    def test_pep604_annotations_are_future_guarded(self):
        for root_name in ("core", "web"):
            for path in (PROJECT_ROOT / root_name).rglob("*.py"):
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text)
                uses_pep604 = any(_annotation_uses_pep604(annotation) for annotation in _iter_annotations(tree))
                if not uses_pep604:
                    continue
                self.assertIn(
                    "from __future__ import annotations",
                    text,
                    f"{path.relative_to(PROJECT_ROOT)} uses PEP 604 annotations without future annotations",
                )


def _iter_annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                if arg.annotation is not None:
                    yield arg.annotation
            if node.args.vararg and node.args.vararg.annotation is not None:
                yield node.args.vararg.annotation
            if node.args.kwarg and node.args.kwarg.annotation is not None:
                yield node.args.kwarg.annotation
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def _annotation_uses_pep604(annotation):
    return any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
        for node in ast.walk(annotation)
    )


if __name__ == "__main__":
    unittest.main()
