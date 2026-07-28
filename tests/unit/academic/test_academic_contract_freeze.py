from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from paperclaw.academic import (
    ACADEMIC_SCHEMA_VERSION,
    AcademicObject,
    ArtifactRevision,
    EvidenceBundle,
    EvidenceLocator,
    MemorySnapshot,
    PaperRecord,
)
from paperclaw.academic.store import AcademicObjectStore


ROOT = Path(__file__).parents[3]
GOLDEN = ROOT / "contracts" / "academic.v1.golden.json"


def test_six_canonical_contracts_round_trip_golden_payload() -> None:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert PaperRecord.from_dict(payload["paper_record"]).to_dict() == payload["paper_record"]
    assert (
        EvidenceLocator.from_dict(payload["evidence_locator"]).to_dict()
        == payload["evidence_locator"]
    )
    assert (
        AcademicObject.from_dict(payload["academic_object"]).to_dict()
        == payload["academic_object"]
    )
    assert (
        EvidenceBundle.from_dict(payload["evidence_bundle"]).to_dict()
        == payload["evidence_bundle"]
    )
    assert (
        MemorySnapshot.from_dict(payload["memory_snapshot"]).to_dict()
        == payload["memory_snapshot"]
    )
    assert (
        ArtifactRevision.from_dict(payload["artifact_revision"]).to_dict()
        == payload["artifact_revision"]
    )


def test_unknown_schema_and_tampered_locator_fail_closed() -> None:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))["evidence_locator"]
    missing = dict(payload)
    missing.pop("schema_version")
    with pytest.raises(ValueError, match="unsupported academic schema"):
        EvidenceLocator.from_dict(missing)

    payload["schema_version"] = "academic.v2"
    with pytest.raises(ValueError, match="unsupported academic schema"):
        EvidenceLocator.from_dict(payload)

    object_payload = json.loads(GOLDEN.read_text(encoding="utf-8"))[
        "academic_object"
    ]
    object_payload.pop("schema_version")
    with pytest.raises(ValueError, match="unsupported academic schema"):
        AcademicObject.from_dict(object_payload)

    payload["schema_version"] = ACADEMIC_SCHEMA_VERSION
    payload["source_hash"] = "not-a-hash"
    with pytest.raises(ValueError, match="source_hash"):
        EvidenceLocator.from_dict(payload)


def test_normalized_store_rejects_coordinate_drift_and_asset_tampering(
    tmp_path: Path,
) -> None:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))["academic_object"]
    item = AcademicObject.from_dict(payload)
    database = tmp_path / "academic.sqlite3"
    assets = tmp_path / "assets"
    store = AcademicObjectStore(database, assets)

    from paperclaw.academic.contracts import ParseResult

    result = ParseResult(
        manifest_id="manifest-1",
        paper_id="paper-1",
        version_id="version-1",
        source_hash="a" * 64,
        parser_name="test",
        parser_version="1",
        parser_fingerprint="test:1",
        status="ready",
        page_count=1,
        objects=(item,),
    )
    store.save(result, parse_fingerprint="f" * 64)
    assert store.resolve(item.locator) == item

    locator = EvidenceLocator.from_dict(
        {**item.locator.to_dict(), "page_number": 2}
    )
    with pytest.raises(KeyError, match="coordinates"):
        store.resolve(locator)


def test_failed_transaction_never_exposes_staging_manifest(tmp_path: Path) -> None:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))["academic_object"]
    item = AcademicObject.from_dict(payload)
    database = tmp_path / "academic.sqlite3"
    store = AcademicObjectStore(
        database,
        tmp_path / "assets",
        version_source_hash=lambda paper_id, version_id: "a" * 64,
    )

    from paperclaw.academic.contracts import ParseResult

    mismatched = ParseResult(
        manifest_id="manifest-bad",
        paper_id="another-paper",
        version_id="version-1",
        source_hash="a" * 64,
        parser_name="test",
        parser_version="1",
        parser_fingerprint="test:1",
        status="ready",
        page_count=1,
        objects=(item,),
    )
    with pytest.raises(ValueError, match="identity"):
        store.save(mismatched, parse_fingerprint="e" * 64)

    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM academic_parse_manifests_v1"
        ).fetchone()[0] == 0


def test_database_trigger_rejects_object_manifest_identity_drift(tmp_path: Path) -> None:
    database = tmp_path / "academic.sqlite3"
    AcademicObjectStore(database, tmp_path / "assets")
    with sqlite3.connect(database) as db:
        db.execute(
            """
            INSERT INTO academic_parse_manifests_v1(
                manifest_id,paper_id,version_id,source_hash,parser_name,
                parser_version,parser_fingerprint,parse_fingerprint,status,
                page_count,payload,warnings_json,active
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)
            """,
            (
                "manifest-trigger",
                "paper-1",
                "version-1",
                "a" * 64,
                "test",
                "1",
                "test:1",
                "trigger-fingerprint",
                "staging",
                1,
                "{}",
                "[]",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="identity mismatch"):
            db.execute(
                """
                INSERT INTO academic_objects_v1(
                    manifest_id,object_id,paper_id,version_id,source_hash,
                    parser_fingerprint,object_type,page_number,reading_order,
                    provenance,text,locator_json,object_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "manifest-trigger",
                    "object-1",
                    "wrong-paper",
                    "version-1",
                    "a" * 64,
                    "test:1",
                    "page",
                    1,
                    0,
                    "extracted",
                    None,
                    "{}",
                    "{}",
                ),
            )


def test_store_rejects_bbox_outside_declared_page_dimensions(tmp_path: Path) -> None:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))["academic_object"]
    payload["structured_content"] = {
        "page_width_points": 100.0,
        "page_height_points": 100.0,
    }
    item = AcademicObject.from_dict(payload)
    from paperclaw.academic.contracts import ParseResult

    store = AcademicObjectStore(tmp_path / "academic.sqlite3", tmp_path / "assets")
    result = ParseResult(
        manifest_id="manifest-bounds",
        paper_id="paper-1",
        version_id="version-1",
        source_hash="a" * 64,
        parser_name="test",
        parser_version="1",
        parser_fingerprint="test:bounds",
        status="ready",
        page_count=1,
        objects=(item,),
    )
    with pytest.raises(ValueError, match="page bounds"):
        store.save(result, parse_fingerprint="bounds-fingerprint")


@pytest.mark.parametrize(
    ("version_hash", "expected_status"),
    [("a" * 64, "ready"), ("b" * 64, "stale")],
)
def test_legacy_manifest_backfills_only_when_identity_is_verifiable(
    tmp_path: Path, version_hash: str, expected_status: str
) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["academic_object"]
    legacy_object = dict(golden)
    legacy_object.pop("schema_version")
    legacy_object["locator"] = dict(legacy_object["locator"])
    legacy_object["locator"].pop("schema_version")
    legacy_object["asset_hash"] = None
    legacy_object.pop("assets")
    database = tmp_path / "academic.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE parse_manifests("
            "manifest_id TEXT PRIMARY KEY,paper_id TEXT,version_id TEXT,"
            "fingerprint TEXT UNIQUE,payload TEXT)"
        )
        db.execute(
            "INSERT INTO parse_manifests VALUES(?,?,?,?,?)",
            (
                "legacy-1",
                "paper-1",
                "version-1",
                "legacy-fingerprint",
                json.dumps(
                    {
                        "manifest_id": "legacy-1",
                        "paper_id": "paper-1",
                        "version_id": "version-1",
                        "parser_name": "legacy",
                        "parser_version": "0.43",
                        "parser_fingerprint": "legacy:0.43",
                        "status": "ready",
                        "page_count": 1,
                        "objects": [legacy_object],
                        "warnings": [],
                    }
                ),
            ),
        )
        db.commit()

    store = AcademicObjectStore(
        database,
        tmp_path / "assets",
        version_source_hash=lambda paper_id, version_id: version_hash,
    )
    if expected_status == "ready":
        restored = store.get("paper-1", "version-1")
        assert restored.source_hash == "a" * 64
        assert restored.objects[0].locator.object_id == "version-1:page:1"
    else:
        with sqlite3.connect(database) as db:
            assert db.execute(
                "SELECT status FROM academic_parse_manifests_v1"
            ).fetchone() == ("stale",)
        with pytest.raises(KeyError):
            store.get("paper-1", "version-1")


def test_invalid_legacy_manifest_stays_stale_and_does_not_block_reparse(
    tmp_path: Path,
) -> None:
    database = tmp_path / "academic.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE parse_manifests("
            "manifest_id TEXT PRIMARY KEY,paper_id TEXT,version_id TEXT,"
            "fingerprint TEXT UNIQUE,payload TEXT)"
        )
        db.execute(
            "INSERT INTO parse_manifests VALUES(?,?,?,?,?)",
            ("legacy-bad", "paper-1", "version-1", "parse-fingerprint", "{}"),
        )
        db.commit()

    store = AcademicObjectStore(database, tmp_path / "assets")
    AcademicObjectStore(database, tmp_path / "assets")
    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT status,active FROM academic_parse_manifests_v1"
        ).fetchone()
        assert row == ("stale", 0)

    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))["academic_object"]
    item = AcademicObject.from_dict(payload)
    from paperclaw.academic.contracts import ParseResult

    store.save(
        ParseResult(
            manifest_id="manifest-reparse",
            paper_id="paper-1",
            version_id="version-1",
            source_hash="a" * 64,
            parser_name="test",
            parser_version="1",
            parser_fingerprint="test:1",
            status="ready",
            page_count=1,
            objects=(item,),
        ),
        parse_fingerprint="parse-fingerprint",
    )
    assert store.get("paper-1", "version-1").manifest_id == "manifest-reparse"


def test_contract_files_have_stable_sha256() -> None:
    schema = ROOT / "contracts" / "academic.v1.schema.json"
    assert hashlib.sha256(schema.read_bytes()).hexdigest() == (
        "62c3c6bbde000023a95025fdcae53c777fac479ddc9da02a63ea293b0855d2e0"
    )
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == (
        "5f8b3b999de2139c6e328966086043663a3012a068636061971926b979ea647d"
    )
    packaged = ROOT / "src" / "paperclaw" / "academic" / "schemas"
    assert hashlib.sha256((packaged / schema.name).read_bytes()).hexdigest() == (
        "62c3c6bbde000023a95025fdcae53c777fac479ddc9da02a63ea293b0855d2e0"
    )
    assert hashlib.sha256((packaged / GOLDEN.name).read_bytes()).hexdigest() == (
        "5f8b3b999de2139c6e328966086043663a3012a068636061971926b979ea647d"
    )


def test_wire_schema_accepts_all_six_golden_models_and_rejects_shells() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "academic.v1.schema.json").read_text(encoding="utf-8")
    )
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for key in (
        "paper_record",
        "academic_object",
        "evidence_locator",
        "evidence_bundle",
        "memory_snapshot",
        "artifact_revision",
    ):
        validator.validate(golden[key])
    with pytest.raises(JsonSchemaValidationError):
        validator.validate({"schema_version": "academic.v1"})
