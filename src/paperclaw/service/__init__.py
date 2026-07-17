"""Optional HTTP service and plugin contracts for PaperClaw."""

from .application import RunApplicationService
from .contracts import (
    PublicRunEvent,
    PublicRunView,
    ServiceRunRequest,
    SubmitOutcome,
)
from .plugins import ServicePlugin, ServicePluginRegistry
from .production_application import DurableRunApplicationService
from .resilience import LayerTimeoutError, TimeoutPolicy

__all__ = [
    "DurableRunApplicationService",
    "LayerTimeoutError",
    "PublicRunEvent",
    "PublicRunView",
    "RunApplicationService",
    "ServicePlugin",
    "ServicePluginRegistry",
    "ServiceRunRequest",
    "SubmitOutcome",
    "TimeoutPolicy",
]
