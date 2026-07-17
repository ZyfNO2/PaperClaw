"""Optional HTTP service and plugin contracts for PaperClaw."""

from .application import RunApplicationService
from .contracts import (
    PublicRunEvent,
    PublicRunView,
    ServiceRunRequest,
    SubmitOutcome,
)
from .plugins import ServicePlugin, ServicePluginRegistry

__all__ = [
    "PublicRunEvent",
    "PublicRunView",
    "RunApplicationService",
    "ServicePlugin",
    "ServicePluginRegistry",
    "ServiceRunRequest",
    "SubmitOutcome",
]
