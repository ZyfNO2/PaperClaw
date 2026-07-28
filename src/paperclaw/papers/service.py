"""Deep paper-ingestion module shared by Python, REST, CLI and Desktop."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
from uuid import uuid4

from .contracts import (
    MetadataPatch,
    MetadataValue,
    PaperImportRequest,
    PaperImportResult,
    PaperMetadata,
    PaperRecord,
    PaperVersion,
)
from .repository import PaperConflictError, SQLitePaperRepository


class PaperCapacityError(ValueError):
    pass


class PaperService:
    def __init__(
        self,
        workspace: str | Path,
        project_id: str,
        repository: SQLitePaperRepository,
        *,
        max_file_bytes: int = 100 * 1024 * 1024,
    ) -> None:
        self.workspace = Path(workspace).resolve(strict=True)
        self.project_id = project_id
        self.repository = repository
        self.max_file_bytes = max_file_bytes
        self._blob_root = self.workspace / ".paperclaw" / "papers" / "blobs"

    @classmethod
    def for_workspace(cls, workspace: str | Path, *, project_id: str) -> "PaperService":
        root = Path(workspace).resolve(strict=True)
        return cls(root, project_id, SQLitePaperRepository(root / ".paperclaw" / "papers.sqlite3"))

    def import_paper(self, request: PaperImportRequest) -> PaperImportResult:
        self._project(request.project_id)
        source = Path(request.source_path)
        if source.is_symlink():
            raise ValueError("paper source must not be a symbolic link")
        resolved = source.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("paper source must be a regular file")
        suffix = resolved.suffix.lower()
        if suffix not in {".pdf", ".md", ".txt", ".tex"}:
            raise ValueError("unsupported paper format")
        size = resolved.stat().st_size
        if size > self.max_file_bytes:
            raise PaperCapacityError("paper exceeds configured byte limit")
        content, digest = self._read_and_validate(resolved, suffix)
        duplicate = self.repository.get_by_hash(request.project_id, digest)
        if duplicate is not None:
            return PaperImportResult(duplicate[0], duplicate[1], False)

        existing = request.paper_id is not None
        prior = self.get_paper(request.project_id, request.paper_id) if existing else None
        metadata, warnings = _extract_metadata(resolved, suffix, content)
        metadata = _apply_patch(metadata, request.metadata, confirmed=True)
        now = _now()
        paper_id = prior.paper_id if prior else f"paper-{uuid4().hex}"
        number = prior.current_version_number + 1 if prior else 1
        version_id = f"version-{uuid4().hex}"
        locator = f"sha256/{digest[:2]}/{digest}"
        target = self._blob_root / digest[:2] / digest
        self._write_blob(target, content)
        record = PaperRecord(
            paper_id, request.project_id, version_id, number,
            prior.metadata if prior else metadata,
            prior.metadata_revision if prior else 1,
            prior.created_at if prior else now, now,
        )
        version = PaperVersion(
            version_id, paper_id, number, suffix[1:], resolved.name, size, digest,
            locator, str(resolved), now,
        )
        try:
            self.repository.insert(record, version, existing=existing)
        except PaperConflictError:
            concurrent = self.repository.get_by_hash(request.project_id, digest)
            if concurrent is not None:
                return PaperImportResult(concurrent[0], concurrent[1], False)
            raise
        return PaperImportResult(self.get_paper(request.project_id, paper_id), version, True, warnings)

    def list_papers(self, project_id: str, cursor: str | None = None, limit: int = 50) -> tuple[PaperRecord, ...]:
        self._project(project_id)
        return self.repository.list_papers(project_id, cursor=cursor, limit=limit)

    def get_paper(self, project_id: str, paper_id: str | None) -> PaperRecord:
        self._project(project_id)
        if not paper_id:
            raise ValueError("paper_id is required")
        return self.repository.get_paper(project_id, paper_id)

    def canonical_record(self, project_id: str, paper_id: str) -> object:
        """Return the sole cross-repository ``academic.v1`` paper contract."""

        from paperclaw.academic.contracts import (
            PaperRecord as AcademicPaperRecord,
            PaperVersion as AcademicPaperVersion,
        )

        paper = self.get_paper(project_id, paper_id)
        version = self.repository.get_version(
            project_id, paper_id, paper.current_version_id
        )
        return AcademicPaperRecord(
            paper_id=paper.paper_id,
            project_id=paper.project_id,
            current_version=AcademicPaperVersion(
                version_id=version.version_id,
                version_number=version.version_number,
                source_hash=version.sha256,
                format=version.format,
                original_filename=version.original_filename,
                byte_length=version.byte_length,
                created_at=version.created_at,
            ),
            metadata=paper.metadata.to_dict(),
            metadata_revision=paper.metadata_revision,
            source={
                "kind": "local_import",
                "filename": version.original_filename,
            },
            created_at=paper.created_at,
            updated_at=paper.updated_at,
        )

    def list_versions(self, project_id: str, paper_id: str) -> tuple[PaperVersion, ...]:
        self._project(project_id)
        return self.repository.list_versions(project_id, paper_id)

    def read_version(self, project_id: str, paper_id: str, version_id: str) -> bytes:
        self._project(project_id)
        version = self.repository.get_version(project_id, paper_id, version_id)
        target = self._blob_root / version.sha256[:2] / version.sha256
        if target.is_symlink() or not target.is_file():
            raise RuntimeError("managed paper blob is missing or unsafe")
        content = target.read_bytes()
        if len(content) != version.byte_length or hashlib.sha256(content).hexdigest() != version.sha256:
            raise RuntimeError("managed paper blob failed integrity validation")
        return content

    def delete_version(
        self, project_id: str, paper_id: str, version_id: str
    ) -> PaperVersion | None:
        """Remove a canonical version record without deleting its managed blob."""

        self._project(project_id)
        return self.repository.delete_version(project_id, paper_id, version_id)

    def confirm_metadata(self, project_id: str, paper_id: str, patch: MetadataPatch, expected_revision: int) -> PaperRecord:
        paper = self.get_paper(project_id, paper_id)
        return self.repository.update_metadata(
            project_id, paper_id, _apply_patch(paper.metadata, patch, confirmed=True), expected_revision
        )

    def _project(self, project_id: str) -> None:
        if project_id != self.project_id:
            raise ValueError("project_id does not match configured workspace")

    def _read_and_validate(self, source: Path, suffix: str) -> tuple[bytes, str]:
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        total = 0
        with source.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if total > self.max_file_bytes:
                    raise PaperCapacityError("paper exceeds configured byte limit")
                digest.update(chunk)
                chunks.append(chunk)
        content = b"".join(chunks)
        if suffix == ".pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("paper is not a valid PDF file")
            try:
                from pypdf import PdfReader

                reader = PdfReader(BytesIO(content), strict=True)
                _ = reader.metadata
                _ = len(reader.pages)
            except Exception as exc:
                raise ValueError("paper is not a valid PDF file") from exc
        if suffix in {".md", ".txt", ".tex"}:
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("paper text must be valid UTF-8") from exc
        return content, digest.hexdigest()

    def _write_blob(self, target: Path, content: bytes) -> bool:
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise RuntimeError("managed paper blob path is unsafe")
            existing = target.read_bytes()
            if len(existing) != len(content) or hashlib.sha256(existing).digest() != hashlib.sha256(content).digest():
                raise RuntimeError("managed paper blob failed pre-import integrity validation")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                temporary.unlink(missing_ok=True)
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)


def _extract_metadata(path: Path, suffix: str, content: bytes) -> tuple[PaperMetadata, tuple[str, ...]]:
    title = path.stem.replace("_", " ").strip()
    values: dict[str, MetadataValue] = {
        "title": MetadataValue(title, "filename", "candidate"),
    }
    warnings: list[str] = []
    if suffix == ".md":
        text = content.decode("utf-8")
        if text.startswith("---\n") and "\n---\n" in text[4:]:
            front = text[4:].split("\n---\n", 1)[0]
            parsed = {}
            for line in front.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    parsed[key.strip().lower()] = value.strip().strip("\"'")
            if parsed.get("title"):
                values["title"] = MetadataValue(parsed["title"], "front_matter", "candidate")
            if parsed.get("authors"):
                authors = tuple(x.strip() for x in re.split(r"[;,]", parsed["authors"]) if x.strip())
                values["authors"] = MetadataValue(authors, "front_matter", "candidate")
            if parsed.get("year", "").isdigit():
                values["year"] = MetadataValue(int(parsed["year"]), "front_matter", "candidate")
            for name in ("doi", "arxiv_id", "language"):
                if parsed.get(name):
                    values[name] = MetadataValue(parsed[name], "front_matter", "candidate")
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            info = reader.metadata or {}
            if info.get("/Title"):
                values["title"] = MetadataValue(str(info["/Title"]).strip(), "pdf_metadata", "candidate")
            if info.get("/Author"):
                authors = tuple(x.strip() for x in re.split(r"[;,]", str(info["/Author"])) if x.strip())
                values["authors"] = MetadataValue(authors, "pdf_metadata", "candidate")
        except ImportError:
            warnings.append("pdf_metadata_dependency_unavailable")
        except Exception:
            warnings.append("pdf_metadata_unreadable")
    return PaperMetadata(**values), tuple(warnings)


def _apply_patch(metadata: PaperMetadata, patch: MetadataPatch | None, *, confirmed: bool) -> PaperMetadata:
    if patch is None:
        return metadata
    changes = {}
    for name in ("title", "authors", "year", "doi", "arxiv_id", "language"):
        value = getattr(patch, name)
        if value is not None:
            changes[name] = MetadataValue(value, "user", "confirmed" if confirmed else "candidate")
    return replace(metadata, **changes)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
