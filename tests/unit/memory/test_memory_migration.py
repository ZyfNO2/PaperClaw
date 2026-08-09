from __future__ import annotations

from paperclaw.context.migrations import CURRENT_SCHEMA_VERSION, MigrationRunner, open_connection


def test_empty_database_reaches_latest_schema_and_memory_tables_are_idempotent() -> None:
    connection = open_connection(":memory:")
    try:
        first = MigrationRunner(connection).migrate(make_backup=False)
        second = MigrationRunner(connection).migrate(make_backup=False)
        assert first.applied_version == CURRENT_SCHEMA_VERSION
        assert second.already_at_version is True
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"memory_items", "memory_snapshots"}.issubset(tables)
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == CURRENT_SCHEMA_VERSION
    finally:
        connection.close()


def test_upgrade_from_v3_preserves_existing_context_data() -> None:
    connection = open_connection(":memory:")
    try:
        MigrationRunner(connection).migrate(target_version=3, make_backup=False)
        connection.execute(
            "INSERT INTO conversations(conversation_id, created_at, metadata) VALUES ('c1', 'now', '{}')"
        )
        connection.commit()
        result = MigrationRunner(connection).migrate(make_backup=False)
        assert result.ok is True
        assert connection.execute(
            "SELECT conversation_id FROM conversations"
        ).fetchone()[0] == "c1"
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='memory_items'"
        ).fetchone()[0] == "memory_items"
    finally:
        connection.close()


def test_failed_migration_does_not_advance_version() -> None:
    connection = open_connection(":memory:")
    try:
        runner = MigrationRunner(connection)
        runner.migrate(target_version=3, make_backup=False)
        from paperclaw.context import migrations

        original = migrations.MIGRATIONS.copy()
        migrations.MIGRATIONS[4] = ("broken", ("THIS IS NOT SQL",))
        try:
            result = runner.migrate(make_backup=False)
        finally:
            migrations.MIGRATIONS.clear()
            migrations.MIGRATIONS.update(original)
        assert result.ok is False
        assert runner.current_version() == 3
    finally:
        connection.close()
