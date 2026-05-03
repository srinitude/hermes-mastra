"""Top-level export of MastraMemoryProvider.

Hermes loads `__init__.py` as the plugin entry. Tests + dev-shell tools
that want to import the class without going through package machinery
do `from provider import MastraMemoryProvider`. Both paths share one
implementation — this module re-exports from `__init__`.
"""

from __future__ import annotations

from __init__ import MastraMemoryProvider, register  # type: ignore[no-redef]

__all__ = ["MastraMemoryProvider", "register"]
