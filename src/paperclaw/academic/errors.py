"""Stable failure taxonomy shared by Python and REST retrieval seams."""

from __future__ import annotations


class AcademicRetrievalError(RuntimeError):
    code = "academic_retrieval_error"
    status_code = 500


class AcademicIndexNotReadyError(AcademicRetrievalError):
    code = "academic_index_not_ready"
    status_code = 409


class AcademicStaleSchemaError(AcademicRetrievalError):
    code = "academic_stale_schema"
    status_code = 409


class AcademicStaleIndexError(AcademicRetrievalError):
    code = "academic_stale_index"
    status_code = 409


class AcademicFingerprintMismatchError(AcademicRetrievalError):
    code = "academic_fingerprint_mismatch"
    status_code = 409


class AcademicIntegrityError(AcademicRetrievalError):
    code = "academic_integrity_failure"
    status_code = 409


class AcademicLocatorNotFoundError(AcademicRetrievalError):
    code = "academic_locator_not_found"
    status_code = 404


class AcademicInvalidBudgetError(AcademicRetrievalError, ValueError):
    code = "academic_invalid_budget"
    status_code = 422
