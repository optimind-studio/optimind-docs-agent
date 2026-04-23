"""Dynamic renderer dispatch for DS-Extender components.

Generated renderers live at ``render/dynamic/<kind>.py`` and follow the same
contract as the static renderers: a top-level ``render(body, content)``
function that mutates ``body`` in place.

Safety: every candidate module is AST-validated before dispatch. The
validator enforces a strict template — only ``render.xml_utils``,
``render.tokens``, and stdlib ``re`` may be imported; no ``os``/``sys``/
``subprocess`` calls; no dynamic imports; a top-level ``render`` function
must exist. A module that fails validation is silently skipped (the caller
falls back to the paragraph renderer), and a warning is logged.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Callable


log = logging.getLogger(__name__)


DYNAMIC_DIR = Path(__file__).resolve().parent / "dynamic"
ALLOWED_IMPORT_ROOTS = {
    "re",
    "docx",
    "docx.shared",
    "docx.oxml",
    "docx.oxml.ns",
    "docx.enum.text",
    "docx.enum.table",
    # Relative imports from within the render package
    "..xml_utils",
    "..tokens",
    ".xml_utils",
    ".tokens",
    "render.xml_utils",
    "render.tokens",
    "polish.render.xml_utils",
    "polish.render.tokens",
    "scripts.polish.render.xml_utils",
    "scripts.polish.render.tokens",
}


_DENYLIST = {"os", "sys", "subprocess", "socket", "shutil", "pathlib",
             "requests", "urllib", "urllib3", "http", "httpx",
             "ctypes", "pickle", "marshal"}


_RENDERER_CACHE: dict[str, Callable | None] = {}


def get_dynamic_renderer(kind: str) -> Callable | None:
    """Return the dynamic renderer callable for `kind`, or None if absent/invalid."""
    if kind in _RENDERER_CACHE:
        return _RENDERER_CACHE[kind]

    module_path = DYNAMIC_DIR / f"{kind}.py"
    if not module_path.exists():
        _RENDERER_CACHE[kind] = None
        return None

    if not validate_module(module_path):
        log.warning("dynamic renderer %s failed validation — skipping", kind)
        _RENDERER_CACHE[kind] = None
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            f"polish.render.dynamic.{kind}", str(module_path)
        )
        if spec is None or spec.loader is None:
            _RENDERER_CACHE[kind] = None
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        log.warning("failed to import dynamic renderer %s: %s", kind, e)
        _RENDERER_CACHE[kind] = None
        return None

    fn = getattr(mod, "render", None)
    if not callable(fn):
        log.warning("dynamic renderer %s missing render() callable", kind)
        _RENDERER_CACHE[kind] = None
        return None

    _RENDERER_CACHE[kind] = fn
    return fn


def validate_module(path: Path) -> bool:
    """Static-analysis gate for DS-Extender-authored renderers.

    Returns True if the module looks safe to import. This is defense-in-depth
    — DS-Extender also self-validates before staging — but we re-check at
    load because extensions are committed to git and could arrive from a
    merge.
    """
    try:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
    except Exception as e:
        log.warning("dynamic %s: parse error %s", path.name, e)
        return False

    has_render = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "render":
            has_render = True
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _DENYLIST:
                return False
            full = _normalize_from_module(node)
            if full not in ALLOWED_IMPORT_ROOTS and root not in {"docx", "re"}:
                # Allow relative imports within the polish package.
                if not (node.level > 0):
                    log.warning("dynamic %s: disallowed import %r", path.name, full)
                    return False
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _DENYLIST:
                    return False
        elif isinstance(node, (ast.FunctionDef, ast.Assign, ast.AnnAssign,
                                ast.ClassDef, ast.Expr)):
            continue

    if not has_render:
        return False

    # Walk the whole tree for denied calls.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {"eval", "exec", "compile", "__import__"}:
                return False
            if isinstance(func, ast.Attribute) and func.attr in {
                "system", "popen", "spawn", "spawnlp", "remove", "unlink", "rmtree",
            }:
                return False
    return True


def _normalize_from_module(node: ast.ImportFrom) -> str:
    prefix = "." * (node.level or 0)
    return f"{prefix}{node.module or ''}"


def clear_cache() -> None:
    """Forget every cached renderer — used by tests after mutating dynamic/."""
    _RENDERER_CACHE.clear()
