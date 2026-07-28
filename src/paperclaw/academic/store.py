"""Transactional normalized storage for canonical academic objects."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable

from .contracts import AcademicObject, EvidenceLocator, ParseResult

_SCHEMA_VERSION = 1
_VISIBLE_STATES = ("ready", "partial")


class AcademicObjectStore:
    """Own schema migration, atomic manifest activation and locator replay."""

    def __init__(
        self,
        database: Path,
        assets: Path,
        *,
        version_source_hash: Callable[[str, str], str] | None = None,
    ) -> None:
        self.database = database
        self.assets = assets
        self.version_source_hash = version_source_hash
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS academic_schema(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    version INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO academic_schema VALUES(1, 1);

                CREATE TABLE IF NOT EXISTS academic_parse_manifests_v1(
                    manifest_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL CHECK(length(source_hash)=64),
                    parser_name TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    parser_fingerprint TEXT NOT NULL,
                    parse_fingerprint TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(
                        status IN ('staging','ready','partial','failed','stale')
                    ),
                    page_count INTEGER NOT NULL CHECK(page_count >= 0),
                    payload TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(paper_id, version_id, parser_fingerprint)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_academic_active_manifest_v1
                    ON academic_parse_manifests_v1(paper_id, version_id)
                    WHERE active=1;

                CREATE TABLE IF NOT EXISTS academic_objects_v1(
                    manifest_id TEXT NOT NULL REFERENCES
                        academic_parse_manifests_v1(manifest_id) ON DELETE CASCADE,
                    object_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL CHECK(length(source_hash)=64),
                    parser_fingerprint TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    page_number INTEGER NOT NULL CHECK(page_number >= 1),
                    reading_order INTEGER NOT NULL CHECK(reading_order >= 0),
                    provenance TEXT NOT NULL CHECK(provenance IN ('extracted','inferred')),
                    text TEXT,
                    locator_json TEXT NOT NULL,
                    object_json TEXT NOT NULL,
                    PRIMARY KEY(manifest_id, object_id)
                );
                CREATE INDEX IF NOT EXISTS ix_academic_objects_identity_v1
                    ON academic_objects_v1(paper_id, version_id, source_hash, object_id);
                CREATE INDEX IF NOT EXISTS ix_academic_objects_order_v1
                    ON academic_objects_v1(manifest_id, reading_order);

                CREATE TABLE IF NOT EXISTS academic_locators_v1(
                    manifest_id TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    paper_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL CHECK(length(source_hash)=64),
                    object_type TEXT NOT NULL,
                    page_number INTEGER NOT NULL CHECK(page_number >= 1),
                    locator_json TEXT NOT NULL,
                    PRIMARY KEY(manifest_id, object_id),
                    FOREIGN KEY(manifest_id, object_id) REFERENCES
                        academic_objects_v1(manifest_id, object_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS ix_academic_locator_identity_v1
                    ON academic_locators_v1(
                        paper_id, version_id, source_hash, object_id
                    );

                CREATE TABLE IF NOT EXISTS academic_object_assets_v1(
                    manifest_id TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    asset_hash TEXT NOT NULL CHECK(length(asset_hash)=64),
                    kind TEXT NOT NULL CHECK(kind IN ('page','region')),
                    media_type TEXT NOT NULL,
                    width_px INTEGER,
                    height_px INTEGER,
                    dpi INTEGER NOT NULL,
                    PRIMARY KEY(manifest_id, object_id, asset_hash),
                    FOREIGN KEY(manifest_id, object_id) REFERENCES
                        academic_objects_v1(manifest_id, object_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS academic_object_relations_v1(
                    manifest_id TEXT NOT NULL,
                    source_object_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    target_object_id TEXT NOT NULL,
                    PRIMARY KEY(
                        manifest_id, source_object_id, relation_type, target_object_id
                    ),
                    FOREIGN KEY(manifest_id, source_object_id) REFERENCES
                        academic_objects_v1(manifest_id, object_id) ON DELETE CASCADE,
                    FOREIGN KEY(manifest_id, target_object_id) REFERENCES
                        academic_objects_v1(manifest_id, object_id) ON DELETE CASCADE
                );

                CREATE TRIGGER IF NOT EXISTS validate_academic_object_identity_v1
                BEFORE INSERT ON academic_objects_v1
                BEGIN
                    SELECT CASE WHEN NOT EXISTS(
                        SELECT 1 FROM academic_parse_manifests_v1 m
                        WHERE m.manifest_id=NEW.manifest_id
                          AND m.paper_id=NEW.paper_id
                          AND m.version_id=NEW.version_id
                          AND m.source_hash=NEW.source_hash
                          AND m.parser_fingerprint=NEW.parser_fingerprint
                    ) THEN RAISE(ABORT, 'academic object identity mismatch') END;
                END;

                CREATE TRIGGER IF NOT EXISTS validate_academic_locator_identity_v1
                BEFORE INSERT ON academic_locators_v1
                BEGIN
                    SELECT CASE WHEN NOT EXISTS(
                        SELECT 1 FROM academic_objects_v1 o
                        WHERE o.manifest_id=NEW.manifest_id
                          AND o.object_id=NEW.object_id
                          AND o.paper_id=NEW.paper_id
                          AND o.version_id=NEW.version_id
                          AND o.source_hash=NEW.source_hash
                          AND o.object_type=NEW.object_type
                          AND o.page_number=NEW.page_number
                    ) THEN RAISE(ABORT, 'academic locator identity mismatch') END;
                END;

                INSERT OR IGNORE INTO academic_locators_v1(
                    manifest_id,object_id,paper_id,version_id,source_hash,
                    object_type,page_number,locator_json
                )
                SELECT manifest_id,object_id,paper_id,version_id,source_hash,
                       object_type,page_number,locator_json
                FROM academic_objects_v1;
                """
            )
            row = db.execute(
                "SELECT version FROM academic_schema WHERE singleton=1"
            ).fetchone()
            if row is None or int(row[0]) != _SCHEMA_VERSION:
                raise RuntimeError("unsupported academic object store schema")
            db.commit()
        self.backfill_legacy()

    def save(self, result: ParseResult, *, parse_fingerprint: str) -> None:
        """Atomically stage objects and expose only a complete terminal manifest."""

        payload = json.dumps(
            result.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """
                SELECT manifest_id, status FROM academic_parse_manifests_v1
                WHERE parse_fingerprint=?
                """,
                (parse_fingerprint,),
            ).fetchone()
            if existing is not None:
                db.rollback()
                return
            db.execute(
                """
                INSERT INTO academic_parse_manifests_v1(
                    manifest_id,paper_id,version_id,source_hash,parser_name,
                    parser_version,parser_fingerprint,parse_fingerprint,status,
                    page_count,payload,warnings_json,active
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)
                """,
                (
                    result.manifest_id,
                    result.paper_id,
                    result.version_id,
                    result.source_hash,
                    result.parser_name,
                    result.parser_version,
                    result.parser_fingerprint,
                    parse_fingerprint,
                    "staging",
                    result.page_count,
                    payload,
                    json.dumps(result.warnings, ensure_ascii=False),
                ),
            )
            self._insert_objects(db, result)
            active = 1 if result.status in _VISIBLE_STATES else 0
            if active:
                db.execute(
                    """
                    UPDATE academic_parse_manifests_v1 SET active=0
                    WHERE paper_id=? AND version_id=?
                    """,
                    (result.paper_id, result.version_id),
                )
            db.execute(
                """
                UPDATE academic_parse_manifests_v1 SET status=?, active=?
                WHERE manifest_id=?
                """,
                (result.status, active, result.manifest_id),
            )
            db.commit()

    def get_by_fingerprint(self, parse_fingerprint: str) -> ParseResult | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload FROM academic_parse_manifests_v1
                WHERE parse_fingerprint=? AND status != 'staging'
                """,
                (parse_fingerprint,),
            ).fetchone()
        return self._decode_result(row[0]) if row else None

    def get(self, paper_id: str, version_id: str) -> ParseResult:
        with self._connect() as db:
            manifest = db.execute(
                """
                SELECT manifest_id,payload FROM academic_parse_manifests_v1
                WHERE paper_id=? AND version_id=? AND active=1
                  AND status IN ('ready','partial')
                ORDER BY rowid DESC LIMIT 1
                """,
                (paper_id, version_id),
            ).fetchone()
            if manifest is None:
                raise KeyError("paper version has no active parsed manifest")
            rows = db.execute(
                """
                SELECT object_json FROM academic_objects_v1
                WHERE manifest_id=? ORDER BY reading_order, object_id
                """,
                (manifest["manifest_id"],),
            ).fetchall()
        payload = json.loads(manifest["payload"])
        payload["objects"] = [json.loads(row["object_json"]) for row in rows]
        return self._decode_result(json.dumps(payload))

    def list_active(self) -> tuple[ParseResult, ...]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT paper_id,version_id FROM academic_parse_manifests_v1
                WHERE active=1 AND status IN ('ready','partial')
                ORDER BY paper_id,version_id
                """
            ).fetchall()
        return tuple(self.get(row["paper_id"], row["version_id"]) for row in rows)

    def resolve(self, locator: EvidenceLocator) -> AcademicObject:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT o.object_json, l.locator_json
                FROM academic_objects_v1 o
                JOIN academic_parse_manifests_v1 m USING(manifest_id)
                JOIN academic_locators_v1 l
                  ON l.manifest_id=o.manifest_id AND l.object_id=o.object_id
                WHERE m.active=1 AND m.status IN ('ready','partial')
                  AND o.paper_id=? AND o.version_id=? AND o.source_hash=?
                  AND o.object_id=?
                """,
                (
                    locator.paper_id,
                    locator.version_id,
                    locator.source_hash,
                    locator.object_id,
                ),
            ).fetchone()
        if row is None:
            raise KeyError("evidence locator could not be resolved")
        item = AcademicObject.from_dict(json.loads(row["object_json"]))
        stored_locator = EvidenceLocator.from_dict(json.loads(row["locator_json"]))
        if item.locator != stored_locator:
            raise KeyError("stored object and locator identities have drifted")
        if item.locator != locator:
            raise KeyError("evidence locator coordinates do not match stored identity")
        for asset in item.assets:
            path = self.asset_path(asset.asset_hash)
            if not path.is_file() or self._sha256(path) != asset.asset_hash:
                raise KeyError(f"academic asset integrity failure: {asset.asset_hash}")
        return item

    def read_asset(self, locator: EvidenceLocator, asset_hash: str) -> bytes:
        item = self.resolve(locator)
        if asset_hash not in {asset.asset_hash for asset in item.assets}:
            raise KeyError("asset is not attached to the resolved academic object")
        path = self.asset_path(asset_hash)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != asset_hash:
            raise KeyError(f"academic asset integrity failure: {asset_hash}")
        return content

    def asset_path(self, asset_hash: str) -> Path:
        if len(asset_hash) != 64:
            raise ValueError("invalid asset hash")
        return self.assets / asset_hash[:2] / f"{asset_hash}.png"

    def backfill_legacy(self) -> None:
        """Migrate valid 0.43 manifest blobs; retain invalid rows as stale audit records."""

        with self._connect() as db:
            table = db.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='parse_manifests'
                """
            ).fetchone()
            if table is None:
                return
            rows = db.execute(
                "SELECT manifest_id,paper_id,version_id,fingerprint,payload FROM parse_manifests"
            ).fetchall()
        for row in rows:
            with self._connect() as db:
                migrated = db.execute(
                    """
                    SELECT 1 FROM academic_parse_manifests_v1
                    WHERE manifest_id IN (?,?) OR parse_fingerprint=?
                    """,
                    (
                        row["manifest_id"],
                        f"stale-{row['manifest_id']}",
                        row["fingerprint"],
                    ),
                ).fetchone()
            if migrated is not None:
                continue
            try:
                payload = json.loads(row["payload"])
                if (
                    str(payload["paper_id"]) != str(row["paper_id"])
                    or str(payload["version_id"]) != str(row["version_id"])
                ):
                    raise ValueError("legacy row and payload identity mismatch")
                objects = tuple(
                    AcademicObject.from_dict(self._upgrade_legacy_object(item))
                    for item in payload.get("objects", ())
                )
                source_hashes = {item.locator.source_hash for item in objects}
                if len(source_hashes) != 1:
                    raise ValueError("legacy manifest has no unique source hash")
                source_hash = source_hashes.pop()
                if self.version_source_hash is not None:
                    expected_hash = self.version_source_hash(
                        str(row["paper_id"]), str(row["version_id"])
                    )
                    if source_hash != expected_hash:
                        raise ValueError(
                            "legacy source hash does not match immutable paper version"
                        )
                result = ParseResult(
                    manifest_id=str(payload["manifest_id"]),
                    paper_id=str(payload["paper_id"]),
                    version_id=str(payload["version_id"]),
                    source_hash=source_hash,
                    parser_name=str(payload["parser_name"]),
                    parser_version=str(payload["parser_version"]),
                    parser_fingerprint=str(payload["parser_fingerprint"]),
                    status=payload["status"],
                    page_count=int(payload["page_count"]),
                    objects=objects,
                    warnings=tuple(payload.get("warnings", ())),
                )
                self.save(result, parse_fingerprint=str(row["fingerprint"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._record_stale_legacy(row, str(exc))

    def _record_stale_legacy(self, row: sqlite3.Row, reason: str) -> None:
        payload = json.dumps(
            {
                "legacy_manifest_id": row["manifest_id"],
                "migration_error": reason[:1000],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO academic_parse_manifests_v1(
                    manifest_id,paper_id,version_id,source_hash,parser_name,
                    parser_version,parser_fingerprint,parse_fingerprint,status,
                    page_count,payload,warnings_json,active
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)
                """,
                (
                    f"stale-{row['manifest_id']}",
                    row["paper_id"],
                    row["version_id"],
                    "0" * 64,
                    "legacy",
                    "0.43",
                    "legacy:unverified",
                    f"stale:{row['fingerprint']}",
                    "stale",
                    0,
                    payload,
                    json.dumps([reason[:1000]], ensure_ascii=False),
                ),
            )
            db.commit()

    def _insert_objects(self, db: sqlite3.Connection, result: ParseResult) -> None:
        ids = {item.object_id for item in result.objects}
        page_sizes: dict[int, tuple[float, float]] = {}
        for item in result.objects:
            if item.object_type != "page":
                continue
            width = item.structured_content.get("page_width_points")
            height = item.structured_content.get("page_height_points")
            if isinstance(width, (int, float)) and isinstance(height, (int, float)):
                page_sizes[item.locator.page_number] = (float(width), float(height))
        for item in result.objects:
            if (
                item.locator.paper_id != result.paper_id
                or item.locator.version_id != result.version_id
                or item.locator.source_hash != result.source_hash
            ):
                raise ValueError("academic object identity does not match manifest")
            bbox = item.locator.bounding_box
            page_size = page_sizes.get(item.locator.page_number)
            if bbox is not None and page_size is not None:
                width, height = page_size
                if bbox.x1 > width or bbox.y1 > height:
                    raise ValueError("academic object bounding box exceeds page bounds")
            db.execute(
                """
                INSERT INTO academic_objects_v1(
                    manifest_id,object_id,paper_id,version_id,source_hash,
                    parser_fingerprint,object_type,page_number,reading_order,
                    provenance,text,locator_json,object_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    result.manifest_id,
                    item.object_id,
                    result.paper_id,
                    result.version_id,
                    result.source_hash,
                    result.parser_fingerprint,
                    item.object_type,
                    item.locator.page_number,
                    item.reading_order,
                    item.provenance,
                    item.text,
                    json.dumps(item.locator.to_dict(), sort_keys=True),
                    json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True),
                ),
            )
            db.execute(
                """
                INSERT INTO academic_locators_v1(
                    manifest_id,object_id,paper_id,version_id,source_hash,
                    object_type,page_number,locator_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    result.manifest_id,
                    item.object_id,
                    result.paper_id,
                    result.version_id,
                    result.source_hash,
                    item.object_type,
                    item.locator.page_number,
                    json.dumps(item.locator.to_dict(), sort_keys=True),
                ),
            )
            for asset in item.assets:
                path = self.asset_path(asset.asset_hash)
                if not path.is_file() or self._sha256(path) != asset.asset_hash:
                    raise ValueError(
                        f"academic asset integrity failure: {asset.asset_hash}"
                    )
                db.execute(
                    """
                    INSERT INTO academic_object_assets_v1 VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        result.manifest_id,
                        item.object_id,
                        asset.asset_hash,
                        asset.kind,
                        asset.media_type,
                        asset.width_px,
                        asset.height_px,
                        asset.dpi,
                    ),
                )
        for item in result.objects:
            parent = item.structured_content.get("parent_object_id")
            if isinstance(parent, str) and parent in ids:
                db.execute(
                    """
                    INSERT OR IGNORE INTO academic_object_relations_v1
                    VALUES(?,?,?,?)
                    """,
                    (result.manifest_id, item.object_id, "child_of", parent),
                )

    @staticmethod
    def _decode_result(payload_json: str) -> ParseResult:
        payload = json.loads(payload_json)
        return ParseResult(
            manifest_id=payload["manifest_id"],
            paper_id=payload["paper_id"],
            version_id=payload["version_id"],
            source_hash=payload["source_hash"],
            parser_name=payload["parser_name"],
            parser_version=payload["parser_version"],
            parser_fingerprint=payload["parser_fingerprint"],
            status=payload["status"],
            page_count=payload["page_count"],
            objects=tuple(AcademicObject.from_dict(item) for item in payload["objects"]),
            warnings=tuple(payload.get("warnings", ())),
            schema_version=payload.get("schema_version", ""),
        )

    @staticmethod
    def _upgrade_legacy_object(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ValueError("legacy academic object must be an object")
        upgraded = dict(value)
        upgraded.setdefault("schema_version", "academic.v1")
        raw_locator = upgraded.get("locator")
        if not isinstance(raw_locator, dict):
            raise ValueError("legacy academic object has no locator")
        locator = dict(raw_locator)
        locator.setdefault("schema_version", "academic.v1")
        upgraded["locator"] = locator
        if "assets" not in upgraded:
            legacy_hash = upgraded.pop("asset_hash", None)
            upgraded["assets"] = (
                [
                    {
                        "asset_hash": legacy_hash,
                        "kind": (
                            "page"
                            if upgraded.get("object_type") == "page"
                            else "region"
                        ),
                    }
                ]
                if isinstance(legacy_hash, str) and legacy_hash
                else []
            )
        return upgraded

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection


__all__ = ["AcademicObjectStore"]
