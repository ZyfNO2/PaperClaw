"""Optional HTML desktop client for PaperClaw.

The package is import-safe without pywebview. Runtime and window dependencies are
loaded only by the explicit ``paperclaw gui`` entry point.
"""

from .contracts import (
    DesktopEventRow,
    DesktopPublicError,
    DesktopRunRequest,
    DesktopRunSnapshot,
)
from .controller import DesktopController

__all__ = [
    "DesktopController",
    "DesktopEventRow",
    "DesktopPublicError",
    "DesktopRunRequest",
    "DesktopRunSnapshot",
]
