"""RFC-RUNTIME-001 persistence primitives.

This package is intentionally not imported by the production model registry in
Phase 1A.  The tables are installed only by the isolated migration acceptance
tests until live shadow capture receives separate authorization.
"""

from .models import RuntimeBase
from .repository import RuntimePersistence

__all__ = ["RuntimeBase", "RuntimePersistence"]
