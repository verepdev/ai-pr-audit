"""Hallucination detector — combines AST imports + dep manifest + stdlib + known aliases.

Strict-bar policy (per PROJECT.md M1 decisions): zero false positives matter more than
recall. We only flag an import when its top-level module is *unambiguously* not
available — not in stdlib, not declared in the manifest, not a known import-name alias
of a declared distribution. Conditional and relative imports are always skipped.
"""

import sys
from dataclasses import dataclass

from ai_pr_audit.ast_imports import ImportRef
from ai_pr_audit.dep_manifest import DepManifest

# Conservative import-name → distribution-name mappings. Only common, unambiguous
# cases. Ambiguous namespaces (e.g. `google.*`) are intentionally excluded so we
# don't risk flagging legitimate code.
_KNOWN_ALIASES: dict[str, str] = {
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
}


@dataclass(frozen=True)
class Hallucination:
    """An import that doesn't resolve against stdlib, declared deps, or known aliases."""

    module: str
    line: int
    col: int
    reason: str


def _top_level(dotted: str) -> str:
    return dotted.split(".", 1)[0]


def detect_hallucinations(
    imports: list[ImportRef],
    manifest: DepManifest,
) -> list[Hallucination]:
    """Return the subset of `imports` that fail every "is this a real package?" check.

    An import survives (is NOT flagged) when any of these is true:
      - It's conditional (`try/except ImportError` body) — explicit fallback, ignore
      - It's relative (`from . import x`) — intra-package, manifest doesn't apply
      - Its top-level module is in `sys.stdlib_module_names`
      - Its top-level module matches a declared dist (after PEP 503 normalisation)
      - Its top-level module is a known alias of a declared dist (e.g. `cv2` → `opencv-python`)

    Anything else gets flagged. The point is to fire only on imports that almost
    certainly don't exist on the runtime — the AI hallucination signal.
    """
    flagged: list[Hallucination] = []
    for ref in imports:
        if ref.is_conditional or ref.is_relative:
            continue
        top = _top_level(ref.module)
        if top in sys.stdlib_module_names:
            continue
        if manifest.is_declared(top):
            continue
        aliased_dist = _KNOWN_ALIASES.get(top)
        if aliased_dist and manifest.is_declared(aliased_dist):
            continue
        flagged.append(
            Hallucination(
                module=ref.module,
                line=ref.line,
                col=ref.col,
                reason=(
                    f"`{top}` is not in the project's dependencies and not a "
                    f"stdlib module — possible AI hallucination."
                ),
            )
        )
    return flagged
