"""SQLite initialization helpers for the INC-1 data foundation."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_PATH = Path(__file__).with_name("schema.sql")
UNPERIODIZED_DATE = "0001-01-01"
UNPERIODIZED_SOURCE = "stable_unperioded"


class ClosingConnection(sqlite3.Connection):
    """A connection whose context manager also releases the file handle."""

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path), factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(db_path: str | Path) -> None:
    with connect(db_path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate_schema(connection)


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _add_columns(connection: sqlite3.Connection, table: str, definitions: tuple[str, ...]) -> None:
    existing = _columns(connection, table)
    for definition in definitions:
        name = definition.split()[0]
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _migrate_schema(connection: sqlite3.Connection) -> None:
    """Apply additive INC-3 migrations to databases created by INC-1/2."""
    _add_columns(connection, "import_batches", (
        "period_start TEXT", "period_end TEXT",
        "period_source TEXT NOT NULL DEFAULT 'import_time'",
    ))
    _add_columns(connection, "raw_video", (
        "published_at TEXT", "product_name TEXT", "attributed_items INTEGER",
        "likes INTEGER", "comments INTEGER", "shares INTEGER",
        "new_followers INTEGER", "favorites INTEGER",
    ))
    _add_columns(connection, "raw_live", (
        "event_at_utc7 TEXT", "attributed_items INTEGER", "view_count INTEGER",
        "comments INTEGER", "shares INTEGER", "likes INTEGER", "favorites INTEGER",
    ))

    cost_columns = _columns(connection, "costs")
    if "target_type" not in cost_columns:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            ALTER TABLE costs RENAME TO costs_inc2;
            CREATE TABLE costs (
                platform TEXT NOT NULL,
                creator_key TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT 'creator'
                    CHECK (target_type IN ('creator', 'video', 'live')),
                target_id TEXT NOT NULL DEFAULT '',
                quote_vnd INTEGER,
                collaboration_cost_vnd INTEGER,
                slot_fee_vnd INTEGER,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (platform, creator_key, target_type, target_id),
                FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key)
            );
            INSERT INTO costs(
                platform, creator_key, target_type, target_id,
                quote_vnd, collaboration_cost_vnd, slot_fee_vnd, updated_at
            )
            SELECT platform, creator_key, 'creator', '',
                   quote_vnd, collaboration_cost_vnd, NULL, updated_at
            FROM costs_inc2;
            DROP TABLE costs_inc2;
            """
        )
        connection.execute("PRAGMA foreign_keys = ON")
    else:
        _add_columns(connection, "costs", ("slot_fee_vnd INTEGER",))

    now = datetime.now(timezone.utc).isoformat()
    connection.executemany(
        "INSERT OR IGNORE INTO tags(name, is_preset, created_at) VALUES (?, 1, ?)",
        ((name, now) for name in ("xx计划", "长期合作视频", "长期合作直播")),
    )
    # Creator exports have no period banner.  Old databases used each import
    # date as the period key, so a cross-day re-import produced another row and
    # inflated total metrics.  Backfill one stable row from raw_creator (the
    # canonical latest record), then remove only legacy import-time rows.  Rows
    # sourced from an explicit banner remain untouched.
    connection.execute(
        """INSERT OR IGNORE INTO raw_creator_periods(
               platform, creator_key, period_start, period_end, period_source,
               alliance_gmv_vnd, alliance_items, estimated_commission_vnd,
               targeted_gmv_vnd, import_batch_id, updated_at
           )
           SELECT r.platform, r.creator_key, ?, ?, ?,
                  r.alliance_gmv_vnd, r.alliance_items, r.estimated_commission_vnd,
                  r.targeted_gmv_vnd, r.import_batch_id, b.imported_at
           FROM raw_creator r JOIN import_batches b ON b.batch_id=r.import_batch_id""",
        (UNPERIODIZED_DATE, UNPERIODIZED_DATE, UNPERIODIZED_SOURCE),
    )
    connection.execute(
        """DELETE FROM raw_creator_periods AS p
           WHERE p.period_source='import_time'
             AND EXISTS (
                 SELECT 1 FROM raw_creator AS r
                 WHERE r.platform=p.platform AND r.creator_key=p.creator_key
             )"""
    )
    connection.execute(
        """UPDATE import_batches
           SET period_start=?, period_end=?, period_source=?
           WHERE source_type='creator' AND period_source='import_time'""",
        (UNPERIODIZED_DATE, UNPERIODIZED_DATE, UNPERIODIZED_SOURCE),
    )
