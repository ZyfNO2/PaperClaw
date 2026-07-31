"""FastAPI/SSE adapter for PaperClaw application services.

Import this module only when the optional ``service`` dependencies are installed.
"""

import asyncio
from importlib.resources import files
import json
from pathlib import Path
import secrets
from typing import Annotated, Any, Literal

from paperclaw.harness import RunLimits
from paperclaw.tasks.contracts import (
    TaskConflictError,
    TaskNotFoundError,
    TaskRuntimeError,
)

from .contracts import ServiceError, ServiceRunRequest


def create_app(
    service: Any,
    *,
    paper_workspace_roots: list[str | Path] | tuple[str | Path, ...] = (),
) -> Any:
    academic_artifact_types = frozenset(
        {
            "evidence_bundle",
            "paper_comparison",
            "baseline_card",
            "module_card",
            "compatibility_matrix",
            "experiment_matrix",
            "method_draft",
            "review_report",
        }
    )
    try:
        from fastapi import FastAPI, Header, HTTPException, Request, Response
        from fastapi.responses import StreamingResponse
        from pydantic import BaseModel, Field, model_validator
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            'FastAPI service dependencies are missing; install "paperclaw[service]"'
        ) from exc

    class LimitsBody(BaseModel):
        max_steps: int = Field(default=20, ge=1, le=10_000)
        max_model_calls: int = Field(default=10, ge=1, le=10_000)
        max_tool_calls: int = Field(default=20, ge=1, le=10_000)

    class RunBody(BaseModel):
        task: str = Field(min_length=1, max_length=100_000)
        workspace: str = Field(min_length=1, max_length=4_096)
        conversation_id: str | None = None
        client_id: str | None = None
        enable_verification_gate: bool = True
        disconnect_policy: str = Field(default="detach_on_disconnect")
        limits: LimitsBody = Field(default_factory=LimitsBody)

    class TaskBody(BaseModel):
        objective: str = Field(min_length=1, max_length=100_000)
        workspace: str = Field(min_length=1, max_length=4_096)
        task_id: str | None = Field(default=None, max_length=200)
        parent_run_id: str | None = Field(default=None, max_length=200)
        dependencies: list[str] = Field(default_factory=list, max_length=100)
        max_steps: int = Field(default=20, ge=1, le=10_000)
        timeout_seconds: float = Field(default=600.0, gt=0, le=86_400)
        max_attempts: int = Field(default=2, ge=1, le=20)
        title: str | None = Field(default=None, max_length=200)
        acceptance_criteria: list[str] = Field(default_factory=list, max_length=100)
        allowed_paths: list[str] = Field(default_factory=lambda: ["."], max_length=100)
        writable_paths: list[str] = Field(default_factory=list, max_length=100)
        allowed_tools: list[str] = Field(
            default_factory=lambda: ["file_read", "grep"],
            max_length=20,
        )

    class PaperImportBody(BaseModel):
        source_path: str = Field(min_length=1, max_length=4_096)
        paper_id: str | None = Field(default=None, max_length=200)

    class ProjectCreateBody(BaseModel):
        name: str = Field(min_length=1, max_length=200)

    class EvidenceBoundClaimBody(BaseModel):
        text: str = Field(min_length=1)
        evidence_ids: list[str] = Field(min_length=1)
        limitations: list[str] = Field(default_factory=list)

    class AcademicDraftBody(BaseModel):
        schema_version: Literal["academic.v1"] = "academic.v1"
        title: str = Field(min_length=1, max_length=500)
        project_id: str = Field(min_length=1, max_length=200)
        summary: str = Field(min_length=1)
        evidence_ids: list[str] = Field(min_length=1)
        claims: list[EvidenceBoundClaimBody] = Field(min_length=1)
        state: Literal["draft"] = "draft"
        review_note: None = None

        @model_validator(mode="after")
        def validate_claim_bindings(self):
            allowed = set(self.evidence_ids)
            if any(not set(claim.evidence_ids) <= allowed for claim in self.claims):
                raise ValueError("artifact claim references undeclared evidence")
            return self

    class EvidenceBundleDraft(AcademicDraftBody):
        artifact_type: Literal["evidence_bundle"]

    class PaperComparisonDraft(AcademicDraftBody):
        artifact_type: Literal["paper_comparison"]

    class BaselineCardDraft(AcademicDraftBody):
        artifact_type: Literal["baseline_card"]

    class ModuleCardDraft(AcademicDraftBody):
        artifact_type: Literal["module_card"]

    class CompatibilityMatrixDraft(AcademicDraftBody):
        artifact_type: Literal["compatibility_matrix"]

    class ExperimentMatrixDraft(AcademicDraftBody):
        artifact_type: Literal["experiment_matrix"]

    class MethodDraft(AcademicDraftBody):
        artifact_type: Literal["method_draft"]

    class ReviewReportDraft(AcademicDraftBody):
        artifact_type: Literal["review_report"]

    AcademicDraft = Annotated[
        EvidenceBundleDraft
        | PaperComparisonDraft
        | BaselineCardDraft
        | ModuleCardDraft
        | CompatibilityMatrixDraft
        | ExperimentMatrixDraft
        | MethodDraft
        | ReviewReportDraft,
        Field(discriminator="artifact_type"),
    ]

    class AcademicArtifactCreateBody(BaseModel):
        idempotency_key: str = Field(min_length=1, max_length=500)
        artifact_type: str = Field(min_length=1, max_length=100)
        title: str = Field(min_length=1, max_length=500)
        draft: AcademicDraft

    class AcademicArtifactReviewBody(BaseModel):
        idempotency_key: str = Field(min_length=1, max_length=500)
        decision: str = Field(pattern="^(approved|rejected|revise)$")
        note: str = Field(min_length=1, max_length=2_000)

    class PaperMetadataBody(BaseModel):
        expected_revision: int = Field(ge=1)
        title: str | None = Field(default=None, max_length=1_000)
        authors: list[str] | None = Field(default=None, max_length=200)
        year: int | None = Field(default=None, ge=1, le=9999)
        doi: str | None = Field(default=None, max_length=500)
        arxiv_id: str | None = Field(default=None, max_length=500)
        language: str | None = Field(default=None, max_length=100)

    class AcademicQueryBody(BaseModel):
        query: str = Field(min_length=1, max_length=10_000)
        channels: list[str] = Field(
            default_factory=lambda: ["lexical", "dense", "visual"], max_length=4
        )
        paper_ids: list[str] = Field(default_factory=list, max_length=100)
        version_ids: list[str] = Field(default_factory=list, max_length=100)
        object_types: list[str] = Field(default_factory=list, max_length=20)
        section_scope: list[str] = Field(default_factory=list, max_length=50)
        max_candidates: int = Field(default=10, ge=1, le=100)
        max_chars: int = Field(default=12_000, ge=1, le=1_000_000)
        include_neighbors: bool = False
        neighbor_count: int = Field(default=1, ge=0, le=5)
        include_assets: bool = False
        max_asset_bytes: int = Field(
            default=10 * 1024 * 1024, ge=1, le=50 * 1024 * 1024
        )

    class AcademicResolveBody(BaseModel):
        locator: dict[str, Any]

    class AcademicAssetBody(BaseModel):
        locator: dict[str, Any]
        asset_hash: str = Field(min_length=64, max_length=64)

    class BoundingBoxWire(BaseModel):
        x0: float
        y0: float
        x1: float
        y1: float

    class EvidenceLocatorWire(BaseModel):
        schema_version: str
        paper_id: str
        version_id: str
        object_id: str
        page_number: int
        object_type: str
        source_hash: str
        section_path: list[str]
        bounding_box: BoundingBoxWire | None = None
        paragraph_index: int | None = None
        line_range: list[int] | None = None
        table_row: int | None = None
        table_column: int | None = None

    class AssetReferenceWire(BaseModel):
        asset_hash: str
        kind: str
        media_type: str
        width_px: int | None = None
        height_px: int | None = None
        dpi: int

    class AcademicObjectWire(BaseModel):
        schema_version: str
        object_id: str
        object_type: str
        reading_order: int
        locator: EvidenceLocatorWire
        text: str | None = None
        assets: list[AssetReferenceWire]
        structured_content: dict[str, Any]
        provenance: str

    class RetrievalCandidateWire(BaseModel):
        locator: EvidenceLocatorWire
        text: str
        channel_scores: dict[str, float]
        fused_score: float
        explanation: list[str]
        provenance: str

    class RetrievalTraceWire(BaseModel):
        trace_id: str
        request_fingerprint: str
        index_generation_id: str
        channels: list[str]
        model_fingerprints: dict[str, str]
        rounds_used: dict[str, int]
        degraded_channels: list[str]
        stop_reason: str
        corrective_details: dict[str, Any] | None = None

    class EvidenceBundleWire(BaseModel):
        schema_version: str
        bundle_id: str
        project_id: str
        query: str
        candidates: list[RetrievalCandidateWire]
        sufficiency: str
        reasons: list[str]
        trace: RetrievalTraceWire

    class GroundedHitWire(BaseModel):
        object: AcademicObjectWire
        neighbor_context: list[AcademicObjectWire]
        assets: list[AssetReferenceWire]

    class RetrievalResponseWire(BaseModel):
        bundle: EvidenceBundleWire
        hits: list[GroundedHitWire]
        asset_bytes_used: int
        assets_truncated: bool
        text_chars_used: int
        text_truncated: bool
        index_metadata: dict[str, str]

    class AcademicIndexEntryWire(BaseModel):
        paper_id: str
        version_id: str
        source_hash: str
        object_id: str
        object_type: str
        page_number: int
        reading_order: int
        locator: EvidenceLocatorWire
        text_hash: str | None = None
        asset_hashes: list[str]
        provenance: str
        schema_version: str
        index_version: str

    class AcademicIndexManifestWire(BaseModel):
        generation_id: str
        corpus_hash: str
        model_fingerprint: str
        entries: list[AcademicIndexEntryWire]
        content_hash: str
        schema_version: str
        index_version: str

    app = FastAPI(title="PaperClaw Service API", version="0.19.0")
    app.state.paperclaw_service = service
    task_service = getattr(service, "task_service", None)
    if task_service is not None:
        app.state.paperclaw_task_service = task_service
    app.state.paper_workspace_roots = tuple(
        Path(root).resolve(strict=True) for root in paper_workspace_roots
    )

    def paper_service(project_id: str, source_path: str | None = None):
        from paperclaw.papers import PaperService
        from paperclaw.projects import ProjectManifestStore

        candidates: list[Path] = []
        if source_path is not None:
            try:
                source = Path(source_path).resolve(strict=True)
            except (OSError, ValueError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "paper_source_invalid",
                        "message": "Paper source is unavailable.",
                    },
                ) from exc
            for root in app.state.paper_workspace_roots:
                try:
                    source.relative_to(root)
                except ValueError:
                    continue
                candidate = source.parent
                while True:
                    candidates.append(candidate)
                    if candidate == root:
                        break
                    candidate = candidate.parent
        else:
            candidates.extend(app.state.paper_workspace_roots)
            for root in app.state.paper_workspace_roots:
                candidates.extend(
                    path.parent.parent
                    for path in root.glob("**/.paperclaw/project.json")
                )
        seen: set[Path] = set()
        for workspace in candidates:
            if workspace in seen:
                continue
            seen.add(workspace)
            try:
                manifest = ProjectManifestStore(workspace).load()
            except (FileNotFoundError, ValueError):
                continue
            if manifest.project_id == project_id:
                return PaperService.for_workspace(workspace, project_id=project_id)
        raise HTTPException(
            status_code=400,
            detail={
                "code": "paper_workspace_denied",
                "message": "Paper workspace is not allowed.",
            },
        )

    def paper_error(exc: Exception) -> HTTPException:
        from paperclaw.academic.errors import AcademicRetrievalError
        from paperclaw.artifacts import ArtifactError, ArtifactNotFoundError
        from paperclaw.papers import (
            PaperCapacityError,
            PaperConflictError,
            PaperNotFoundError,
        )

        if isinstance(exc, AcademicRetrievalError):
            return HTTPException(
                exc.status_code,
                detail={"code": exc.code, "message": str(exc)[:500]},
            )
        if isinstance(exc, ArtifactNotFoundError):
            return HTTPException(
                404,
                detail={"code": exc.code, "message": "Artifact was not found."},
            )
        if isinstance(exc, ArtifactError):
            return HTTPException(
                409,
                detail={"code": exc.code, "message": str(exc)[:500]},
            )
        if isinstance(exc, PaperNotFoundError):
            return HTTPException(
                404,
                detail={
                    "code": "paper_not_found",
                    "message": "Paper resource was not found.",
                },
            )
        if isinstance(exc, PaperConflictError):
            detail = {"code": "paper_conflict", "message": str(exc)[:500]}
            if exc.current_revision is not None:
                detail["current_revision"] = exc.current_revision
            return HTTPException(409, detail=detail)
        if isinstance(exc, PaperCapacityError):
            return HTTPException(
                413, detail={"code": "paper_too_large", "message": str(exc)[:500]}
            )
        if isinstance(exc, (ValueError, TypeError)):
            return HTTPException(
                422,
                detail={"code": "paper_validation_error", "message": str(exc)[:500]},
            )
        return HTTPException(
            500,
            detail={
                "code": "paper_runtime_error",
                "message": "Paper operation failed.",
            },
        )

    def project_manifests() -> list[tuple[Path, Any]]:
        from paperclaw.projects import ProjectManifestStore

        projects: list[tuple[Path, Any]] = []
        seen: set[Path] = set()
        for root in app.state.paper_workspace_roots:
            candidates = [root]
            candidates.extend(
                path.parent.parent for path in root.glob("**/.paperclaw/project.json")
            )
            for workspace in candidates:
                if workspace in seen:
                    continue
                seen.add(workspace)
                try:
                    manifest = ProjectManifestStore(workspace).load()
                except (FileNotFoundError, OSError, ValueError):
                    continue
                projects.append((workspace, manifest))
        projects.sort(key=lambda item: (item[1].name.casefold(), item[1].project_id))
        return projects

    def artifact_store(project_id: str):
        from paperclaw.artifacts import FileArtifactStore

        resolved = paper_service(project_id)
        return FileArtifactStore(
            resolved.workspace / ".paperclaw" / "artifacts",
            confinement_root=resolved.workspace,
        )

    def artifact_payload(store: Any, artifact_id: str) -> dict[str, Any]:
        bundle = store.get_bundle(artifact_id, max_revisions=100)
        revisions: list[dict[str, Any]] = []
        for revision in bundle.revisions:
            raw = store.read_revision(artifact_id, revision.revision_number)
            try:
                content = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("academic artifact revision is not UTF-8 JSON") from exc
            revisions.append({**revision.to_dict(), "content": content})
        return {"artifact": bundle.artifact.to_dict(), "revisions": revisions}

    def academic_artifact_payload(
        store: Any, project_id: str, artifact_id: str
    ) -> dict[str, Any]:
        payload = artifact_payload(store, artifact_id)
        artifact = payload["artifact"]
        revisions = payload["revisions"]
        latest = revisions[-1]["content"] if revisions else {}
        try:
            AcademicDraftBody.model_validate(
                {**latest, "state": "draft", "review_note": None}
                if isinstance(latest, dict)
                else latest
            )
        except (TypeError, ValueError):
            latest = {}
        if (
            artifact.get("artifact_type") not in academic_artifact_types
            or not isinstance(latest, dict)
            or latest.get("project_id") != project_id
            or latest.get("artifact_type") != artifact.get("artifact_type")
            or latest.get("schema_version") != "academic.v1"
            or latest.get("state") not in {"draft", "approved", "rejected", "final"}
            or not (
                latest.get("review_note") is None
                or isinstance(latest.get("review_note"), str)
            )
        ):
            raise HTTPException(
                404,
                detail={
                    "code": "academic_artifact_not_found",
                    "message": "Artifact is outside the bounded academic.v1 collection.",
                },
            )
        return payload

    @app.get("/v1/projects")
    def list_projects():
        projects = project_manifests()
        return {
            "projects": [manifest.to_dict() for _, manifest in projects],
            "count": len(projects),
        }

    @app.post("/v1/projects", status_code=201)
    def create_project(body: ProjectCreateBody):
        from paperclaw.projects import ProjectManifestStore

        if not app.state.paper_workspace_roots:
            raise HTTPException(
                503,
                detail={
                    "code": "project_root_unavailable",
                    "message": "No writable PaperClaw project root is configured.",
                },
            )
        root = app.state.paper_workspace_roots[0]
        workspace = root / f"project-{secrets.token_hex(8)}"
        try:
            workspace.mkdir(parents=False, exist_ok=False)
            manifest = ProjectManifestStore(workspace).initialize(body.name)
        except (FileExistsError, OSError, ValueError) as exc:
            raise HTTPException(
                422,
                detail={"code": "project_create_failed", "message": str(exc)[:500]},
            ) from exc
        return {"project": manifest.to_dict()}

    @app.get("/v1/projects/{project_id}")
    def get_project(project_id: str):
        resolved = paper_service(project_id)
        from paperclaw.projects import ProjectManifestStore

        return {"project": ProjectManifestStore(resolved.workspace).load().to_dict()}

    @app.get("/v1/projects/{project_id}/artifacts")
    def list_academic_artifacts(project_id: str, limit: int = 50):
        if not 1 <= limit <= 100:
            raise HTTPException(422, detail={"code": "artifact_invalid_limit"})
        try:
            store = artifact_store(project_id)
            values = []
            for item in store.list_artifacts(project_id=project_id, limit=100):
                try:
                    academic_artifact_payload(store, project_id, item.artifact_id)
                except HTTPException:
                    continue
                values.append(item)
                if len(values) == limit:
                    break
            return {
                "artifacts": [item.to_dict() for item in values],
                "count": len(values),
            }
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.post("/v1/projects/{project_id}/artifacts", status_code=201)
    def create_academic_artifact(project_id: str, body: AcademicArtifactCreateBody):
        from paperclaw.artifacts import ArtifactSourceLinks

        draft = body.draft.model_dump(mode="json")
        if (
            body.artifact_type not in academic_artifact_types
            or draft.get("artifact_type") != body.artifact_type
            or draft.get("title") != body.title
            or draft.get("project_id") != project_id
            or draft.get("state") != "draft"
        ):
            raise HTTPException(
                422,
                detail={
                    "code": "artifact_validation_error",
                    "message": (
                        "Academic artifact type and draft must match the route project "
                        "and the bounded academic.v1 artifact contract."
                    ),
                },
            )
        try:
            store = artifact_store(project_id)
            record, revision, created = store.create_artifact(
                idempotency_key=body.idempotency_key,
                artifact_type=body.artifact_type,
                title=body.title,
                media_type="application/json",
                content=json.dumps(
                    draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8"),
                source=ArtifactSourceLinks(project_id=project_id),
                metadata={"academic_state": "draft"},
                revision_message="academic draft",
            )
            return {
                "artifact": record.to_dict(),
                "revision": revision.to_dict(),
                "created": created,
            }
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.get("/v1/projects/{project_id}/artifacts/{artifact_id}")
    def get_academic_artifact(project_id: str, artifact_id: str):
        try:
            return academic_artifact_payload(artifact_store(project_id), project_id, artifact_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.post("/v1/projects/{project_id}/artifacts/{artifact_id}/review")
    def review_academic_artifact(
        project_id: str,
        artifact_id: str,
        body: AcademicArtifactReviewBody,
    ):
        try:
            store = artifact_store(project_id)
            payload = academic_artifact_payload(store, project_id, artifact_id)
            current = payload["revisions"][-1]["content"]
            if not isinstance(current, dict) or current.get("state") == "final":
                raise ValueError("final or malformed artifact cannot be reviewed")
            requested_state = "draft" if body.decision == "revise" else body.decision
            replay = (
                current.get("state") == requested_state
                and current.get("review_note") == body.note
            )
            if current.get("state") != "draft" and not replay:
                raise ValueError("only a draft artifact can be reviewed")
            next_state = requested_state
            current.update({"state": next_state, "review_note": body.note})
            revision, created = store.add_revision(
                artifact_id,
                idempotency_key=body.idempotency_key,
                media_type="application/json",
                content=json.dumps(
                    current, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode("utf-8"),
                message=f"academic review: {body.decision}",
                metadata={"academic_state": next_state, "decision": body.decision},
            )
            return {"revision": revision.to_dict(), "created": created}
        except HTTPException:
            raise
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.post("/v1/projects/{project_id}/papers/import", status_code=201)
    def import_paper(project_id: str, body: PaperImportBody):
        from paperclaw.papers import PaperImportRequest

        resolved = paper_service(project_id, body.source_path)
        try:
            imported = resolved.import_paper(
                PaperImportRequest(project_id, body.source_path, paper_id=body.paper_id)
            )
            return {
                "paper": resolved.canonical_record(
                    project_id, imported.paper.paper_id
                ).to_dict(),
                "created": imported.created,
                "warnings": list(imported.warnings),
            }
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.get("/v1/projects/{project_id}/papers")
    def list_papers(project_id: str, cursor: str | None = None, limit: int = 50):
        resolved = paper_service(project_id)
        try:
            return {
                "papers": [
                    resolved.canonical_record(project_id, item.paper_id).to_dict()
                    for item in resolved.list_papers(project_id, cursor, limit)
                ]
            }
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.get("/v1/projects/{project_id}/papers/{paper_id}")
    def get_paper(project_id: str, paper_id: str):
        resolved = paper_service(project_id)
        try:
            return resolved.canonical_record(project_id, paper_id).to_dict()
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.get("/v1/projects/{project_id}/papers/{paper_id}/versions")
    def list_paper_versions(project_id: str, paper_id: str):
        resolved = paper_service(project_id)
        try:
            return {
                "versions": [
                    item.to_public_dict()
                    for item in resolved.list_versions(project_id, paper_id)
                ]
            }
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.patch("/v1/projects/{project_id}/papers/{paper_id}/metadata")
    def confirm_paper_metadata(project_id: str, paper_id: str, body: PaperMetadataBody):
        from paperclaw.papers import MetadataPatch

        resolved = paper_service(project_id)
        try:
            updated = resolved.confirm_metadata(
                project_id,
                paper_id,
                MetadataPatch(
                    title=body.title,
                    authors=tuple(body.authors) if body.authors is not None else None,
                    year=body.year,
                    doi=body.doi,
                    arxiv_id=body.arxiv_id,
                    language=body.language,
                ),
                body.expected_revision,
            )
            return resolved.canonical_record(project_id, updated.paper_id).to_dict()
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.post("/v1/projects/{project_id}/papers/{paper_id}/parse")
    def parse_academic_paper(project_id: str, paper_id: str):
        from paperclaw.academic import AcademicRuntime

        resolved = paper_service(project_id)
        try:
            result = AcademicRuntime.for_workspace(
                resolved.workspace, project_id
            ).parse_paper(paper_id)
            return result.to_public_summary()
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.post("/v1/projects/{project_id}/academic/index")
    def build_academic_index(project_id: str):
        from paperclaw.academic import AcademicRuntime

        resolved = paper_service(project_id)
        try:
            generation = AcademicRuntime.for_workspace(
                resolved.workspace, project_id
            ).build_index()
            return {
                "generation_id": generation.generation_id,
                "state": generation.state,
                "object_count": generation.object_count,
                "model_fingerprint": generation.model_fingerprint,
            }
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.post(
        "/v1/projects/{project_id}/academic/search",
        response_model=RetrievalResponseWire,
    )
    def retrieve_academic_evidence(project_id: str, body: AcademicQueryBody):
        from paperclaw.academic import (
            AcademicRuntime,
            RetrievalBudget,
            RetrievalRequest,
        )

        from paperclaw.academic.retrieval_service import RetrievalService

        resolved = paper_service(project_id)
        try:
            runtime = AcademicRuntime.for_workspace(resolved.workspace, project_id)
            response = RetrievalService(runtime).search(
                RetrievalRequest(
                    body.query,
                    tuple(body.channels),
                    tuple(body.paper_ids),
                    tuple(body.object_types),
                    RetrievalBudget(
                        max_candidates=body.max_candidates,
                        max_chars=body.max_chars,
                    ),
                    tuple(body.version_ids),
                    tuple(body.section_scope),
                ),
                include_assets=body.include_assets,
                include_neighbor_context=body.include_neighbors,
                neighbor_count=body.neighbor_count,
                max_asset_bytes=body.max_asset_bytes,
            )
            return response.to_dict()
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.post("/v1/projects/{project_id}/academic/retrieve", deprecated=True)
    def retrieve_academic_evidence_legacy(project_id: str, body: AcademicQueryBody):
        """One-release compatibility adapter; wire output remains EvidenceBundle."""

        return retrieve_academic_evidence(project_id, body)["bundle"]

    @app.post(
        "/v1/projects/{project_id}/academic/resolve",
        response_model=AcademicObjectWire,
    )
    def resolve_academic_object(project_id: str, body: AcademicResolveBody):
        from paperclaw.academic import AcademicRuntime, EvidenceLocator
        from paperclaw.academic.retrieval_service import RetrievalService

        resolved = paper_service(project_id)
        try:
            runtime = AcademicRuntime.for_workspace(resolved.workspace, project_id)
            locator = EvidenceLocator.from_dict(body.locator)
            return RetrievalService(runtime).resolve_locator(locator).to_dict()
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.post("/v1/projects/{project_id}/academic/asset")
    def read_academic_asset(project_id: str, body: AcademicAssetBody):
        from paperclaw.academic import AcademicRuntime, EvidenceLocator

        resolved = paper_service(project_id)
        try:
            runtime = AcademicRuntime.for_workspace(resolved.workspace, project_id)
            locator = EvidenceLocator.from_dict(body.locator)
            return Response(
                content=runtime.read_asset(locator, body.asset_hash),
                media_type="image/png",
                headers={
                    "ETag": f'"{body.asset_hash}"',
                    "Cache-Control": "private, immutable",
                },
            )
        except Exception as exc:
            raise paper_error(exc) from exc

    @app.get(
        "/v1/projects/{project_id}/academic/index",
        response_model=AcademicIndexManifestWire,
    )
    def inspect_academic_index(project_id: str):
        from paperclaw.academic import AcademicRuntime
        from paperclaw.academic.index import AcademicObjectIndex

        resolved = paper_service(project_id)
        try:
            manifest = AcademicObjectIndex(
                AcademicRuntime.for_workspace(resolved.workspace, project_id)
            ).snapshot()
            return {
                **manifest.__dict__,
                "entries": [entry.to_dict() for entry in manifest.entries],
            }
        except Exception as exc:
            raise paper_error(exc) from exc

    def public_error(exc: Exception) -> HTTPException:
        if isinstance(exc, ServiceError):
            return HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)[:500]},
            )
        if isinstance(exc, TaskNotFoundError):
            return HTTPException(
                status_code=404,
                detail={"code": "task_not_found", "message": str(exc)[:500]},
            )
        if isinstance(exc, TaskConflictError):
            return HTTPException(
                status_code=409,
                detail={"code": "task_conflict", "message": str(exc)[:500]},
            )
        if isinstance(exc, TaskRuntimeError):
            return HTTPException(
                status_code=409,
                detail={"code": "task_runtime_error", "message": str(exc)[:500]},
            )
        if isinstance(exc, (ValueError, TypeError)):
            return HTTPException(
                status_code=422,
                detail={"code": "invalid_request", "message": str(exc)[:500]},
            )
        return HTTPException(
            status_code=500,
            detail={"code": "internal_error", "message": "internal service error"},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/runs", status_code=202)
    async def create_run(
        body: RunBody,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        try:
            request = ServiceRunRequest(
                task=body.task,
                workspace=body.workspace,
                conversation_id=body.conversation_id,
                client_id=body.client_id,
                enable_verification_gate=body.enable_verification_gate,
                disconnect_policy=body.disconnect_policy,
                limits=RunLimits(
                    max_steps=body.limits.max_steps,
                    max_model_calls=body.limits.max_model_calls,
                    max_tool_calls=body.limits.max_tool_calls,
                ),
            )
            outcome = service.submit(request, idempotency_key=idempotency_key)
            return {
                "created": outcome.created,
                "run": outcome.run.to_dict(),
            }
        except Exception as exc:
            raise public_error(exc) from exc

    @app.get("/v1/runs/{service_run_id}")
    async def get_run(service_run_id: str) -> dict[str, Any]:
        try:
            return service.get_run(service_run_id).to_dict()
        except Exception as exc:
            raise public_error(exc) from exc

    @app.post("/v1/runs/{service_run_id}/cancel", status_code=202)
    async def cancel_run(
        service_run_id: str,
        reason: str = "user_requested",
    ) -> dict[str, Any]:
        try:
            return service.cancel(service_run_id, reason=reason).to_dict()
        except Exception as exc:
            raise public_error(exc) from exc

    @app.get("/v1/runs/{service_run_id}/events")
    async def stream_events(
        request: Request,
        service_run_id: str,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            after = int(last_event_id or "0")
            if after < 0:
                raise ValueError("Last-Event-ID must not be negative")
            service.get_run(service_run_id)
            disconnect_policy = (
                service.get_disconnect_policy(service_run_id)
                if hasattr(service, "get_disconnect_policy")
                else "detach_on_disconnect"
            )
        except Exception as exc:
            raise public_error(exc) from exc

        async def generate():
            cursor = after
            while True:
                if await request.is_disconnected():
                    if disconnect_policy == "cancel_on_disconnect":
                        try:
                            await asyncio.to_thread(
                                service.cancel,
                                service_run_id,
                                reason="client_disconnected",
                            )
                        except Exception:
                            pass
                    break
                events, terminal = await asyncio.to_thread(
                    service.wait_for_events,
                    service_run_id,
                    after_sequence=cursor,
                    timeout=1.0,
                )
                if not events:
                    yield ": heartbeat\n\n"
                for event in events:
                    cursor = event.sequence
                    payload = json.dumps(
                        event.to_dict(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield (
                        f"id: {event.sequence}\n"
                        f"event: {event.event_type}\n"
                        f"data: {payload}\n\n"
                    )
                if terminal and not service.list_events(
                    service_run_id, after_sequence=cursor
                ):
                    break

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    if task_service is not None:

        @app.post("/v1/tasks", status_code=202)
        async def create_task(
            body: TaskBody,
            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        ) -> dict[str, Any]:
            try:
                task, created = task_service.submit(
                    objective=body.objective,
                    workspace=body.workspace,
                    task_id=body.task_id,
                    parent_run_id=body.parent_run_id,
                    dependencies=body.dependencies,
                    max_steps=body.max_steps,
                    timeout_seconds=body.timeout_seconds,
                    max_attempts=body.max_attempts,
                    idempotency_key=idempotency_key,
                    metadata={
                        "title": body.title or body.objective[:80],
                        "acceptance_criteria": body.acceptance_criteria
                        or ["Return a structured task result."],
                        "allowed_paths": body.allowed_paths,
                        "writable_paths": body.writable_paths,
                        "allowed_tools": body.allowed_tools,
                    },
                )
                return {"created": created, "task": task.to_dict()}
            except Exception as exc:
                raise public_error(exc) from exc

        @app.get("/v1/tasks/{task_id}")
        async def get_task(task_id: str) -> dict[str, Any]:
            try:
                return task_service.get(task_id).to_dict()
            except Exception as exc:
                raise public_error(exc) from exc

        @app.get("/v1/runs/{parent_run_id}/tasks")
        async def list_run_tasks(parent_run_id: str) -> dict[str, Any]:
            try:
                tasks = task_service.list(parent_run_id=parent_run_id)
                return {
                    "parent_run_id": parent_run_id,
                    "tasks": [task.to_dict() for task in tasks],
                }
            except Exception as exc:
                raise public_error(exc) from exc

        @app.post("/v1/tasks/{task_id}/cancel", status_code=202)
        async def cancel_task(
            task_id: str,
            reason: str = "user_requested",
        ) -> dict[str, Any]:
            try:
                return task_service.cancel(task_id, reason=reason).to_dict()
            except Exception as exc:
                raise public_error(exc) from exc

        @app.get("/v1/tasks/{task_id}/output")
        async def task_output(task_id: str) -> dict[str, Any]:
            try:
                return task_service.output(task_id)
            except Exception as exc:
                raise public_error(exc) from exc

        @app.get("/v1/tasks/{task_id}/events")
        async def stream_task_events(
            request: Request,
            task_id: str,
            last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        ) -> StreamingResponse:
            try:
                after = int(last_event_id or "0")
                if after < 0:
                    raise ValueError("Last-Event-ID must not be negative")
                task_service.get(task_id)
            except Exception as exc:
                raise public_error(exc) from exc

            async def generate_tasks():
                cursor = after
                while True:
                    if await request.is_disconnected():
                        # Background tasks detach from SSE clients by default.
                        break
                    events = await asyncio.to_thread(
                        task_service.events,
                        task_id,
                        after_sequence=cursor,
                        limit=500,
                    )
                    if not events:
                        yield ": heartbeat\n\n"
                    for event in events:
                        cursor = event.sequence
                        payload = json.dumps(
                            event.to_dict(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        yield (
                            f"id: {event.sequence}\n"
                            f"event: {event.event_type}\n"
                            f"data: {payload}\n\n"
                        )
                    task = await asyncio.to_thread(task_service.get, task_id)
                    if task.terminal and not await asyncio.to_thread(
                        task_service.events,
                        task_id,
                        after_sequence=cursor,
                        limit=1,
                    ):
                        break
                    await asyncio.sleep(0.25)

            return StreamingResponse(
                generate_tasks(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

    @app.get("/v1/contracts/academic.v1")
    def get_academic_v1_contract():
        return json.loads(
            files("paperclaw.academic")
            .joinpath("schemas/academic.v1.schema.json")
            .read_text(encoding="utf-8")
        )

    default_openapi = app.openapi

    def academic_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = default_openapi()
        schema["x-paperclaw-academic-contract"] = {
            "schema_version": "academic.v1",
            "schema_path": "/v1/contracts/academic.v1",
            "owner": "PaperClaw",
        }
        contract = json.loads(
            files("paperclaw.academic")
            .joinpath("schemas/academic.v1.schema.json")
            .read_text(encoding="utf-8")
        )
        schema.setdefault("components", {}).setdefault("schemas", {})[
            "AcademicV1Contract"
        ] = contract
        canonical_components = schema["components"]["schemas"]
        canonical_components["EvidenceLocatorWire"] = {
            "$ref": "#/components/schemas/AcademicV1Contract/$defs/evidence_locator"
        }
        canonical_components["AcademicObjectWire"] = {
            "$ref": "#/components/schemas/AcademicV1Contract/$defs/academic_object"
        }
        canonical_components["EvidenceBundleWire"] = {
            "$ref": "#/components/schemas/AcademicV1Contract/$defs/evidence_bundle"
        }
        for body_name in ("AcademicResolveBody", "AcademicAssetBody"):
            canonical_components[body_name]["properties"]["locator"] = {
                "$ref": (
                    "#/components/schemas/AcademicV1Contract/$defs/evidence_locator"
                )
            }
        response_refs = {
            "/v1/projects/{project_id}/academic/retrieve": "evidence_bundle",
            "/v1/projects/{project_id}/academic/resolve": "academic_object",
        }
        for path, definition in response_refs.items():
            operation = schema["paths"][path]["post"]
            operation["responses"]["200"]["content"]["application/json"]["schema"] = {
                "$ref": (f"#/components/schemas/AcademicV1Contract/$defs/{definition}")
            }
        paper_record_paths = (
            ("/v1/projects/{project_id}/papers/{paper_id}", "get"),
            ("/v1/projects/{project_id}/papers/{paper_id}/metadata", "patch"),
        )
        for path, method in paper_record_paths:
            schema["paths"][path][method]["responses"]["200"]["content"][
                "application/json"
            ]["schema"] = {
                "$ref": ("#/components/schemas/AcademicV1Contract/$defs/paper_record")
            }
        app.openapi_schema = schema
        return schema

    app.openapi = academic_openapi

    return app
