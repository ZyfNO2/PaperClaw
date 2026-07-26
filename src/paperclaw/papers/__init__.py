"""Project-scoped academic paper ingestion and versioning."""

from .contracts import (
    MetadataPatch,
    MetadataValue,
    PaperImportRequest,
    PaperImportResult,
    PaperMetadata,
    PaperRecord,
    PaperVersion,
)
from .repository import (
    PaperConflictError,
    PaperNotFoundError,
    PaperRepository,
    SQLitePaperRepository,
)
from .service import PaperCapacityError, PaperService

__all__ = [
    "MetadataPatch", "MetadataValue", "PaperCapacityError", "PaperConflictError",
    "PaperImportRequest", "PaperImportResult", "PaperMetadata", "PaperNotFoundError",
    "PaperRecord", "PaperRepository", "PaperService", "PaperVersion",
    "SQLitePaperRepository",
]
