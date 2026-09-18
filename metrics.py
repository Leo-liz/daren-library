"""Metric calculations and source lineage for creator records."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from db import connect, initialize_database
from importer import PLATFORM
from rating import DEFAULT_CONFIG_PATH, load_rating_config


METRIC_BATCH_SIZE = 1_000
METRIC_UPSERT_SQL = """
    INSERT INTO metrics(
        platform, creator_key, metric_name, metric_value,
        source_table, source_field, source_batches, computed_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(platform, creator_key, metric_name) DO UPDATE SET
        metric_value=excluded.metric_value,
        source_table=excluded.source_table,
        source_field=excluded.source_field,
        source_batches=excluded.source_batches,
        computed_at=excluded.computed_at
"""


def _trace(batch_ids: Iterable[str]) -> str:
    return json.dumps(sorted(set(batch_ids)), ensure_ascii=False, separators=(",", ":"))


def _upsert_metric(
    connection: Any,
    platform: str,
    creator_key: str,
    name: str,
    value: int | float | None,
    source_table: str,
    source_field: str,
    batches: list[str],
    computed_at: str,
) -> None:
    connection.execute(
        METRIC_UPSERT_SQL,
        (platform, creator_key, name, value, source_table, source_field, _trace(batches), computed_at),
    )


def _metric_parameters(
    platform: str,
    creator_key: str,
    name: str,
    value: int | float | None,
    source_table: str,
    source_field: str,
    batches: Iterable[str],
    computed_at: str,
) -> tuple[Any, ...]:
    return (
        platform, creator_key, name, value, source_table, source_field,
        _trace(batches), computed_at,
    )


def _rows_by_creator(rows: Iterable[Any]) -> dict[str, Any]:
    return {row["creator_key"]: row for row in rows}


def _source_batches(
    connection: Any,
    table: str,
    platform: str,
    scope_join: str,
) -> dict[str, set[str]]:
    batches: dict[str, set[str]] = {}
    rows = connection.execute(
        f"SELECT source.creator_key, source.import_batch_id FROM {table} AS source "
        f"{scope_join} WHERE source.platform=?",
        (platform,),
    )
    for row in rows:
        batches.setdefault(row["creator_key"], set()).add(row["import_batch_id"])
    return batches


def recompute_metrics(
    db_path: str | Path,
    platform: str = PLATFORM,
    creator_key: str | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    creator_keys: list[str] | tuple[str, ...] | set[str] | None = None,
) -> int:
    """Recompute all, one, or an explicit set of creators."""
    initialize_database(db_path)
    config = load_rating_config(config_path)
    roi_formulas = config["roi_formulas"]
    computed_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    with connect(db_path) as connection:
        if creator_key is not None and creator_keys is not None:
            raise ValueError("creator_key 与 creator_keys 不能同时提供")
        if creator_keys is not None:
            wanted = sorted(set(creator_keys))
            creators = []
            for offset in range(0, len(wanted), 500):
                chunk = wanted[offset:offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                creators.extend(connection.execute(
                    f"SELECT creator_key FROM creators WHERE platform=? AND creator_key IN ({placeholders}) ORDER BY creator_key",
                    (platform, *chunk),
                ).fetchall())
        elif creator_key is None:
            creators = connection.execute(
                "SELECT creator_key FROM creators WHERE platform=? ORDER BY creator_key", (platform,)
            ).fetchall()
        else:
            creators = connection.execute(
                "SELECT creator_key FROM creators WHERE platform=? AND creator_key=?",
                (platform, creator_key),
            ).fetchall()
        target_keys = [row["creator_key"] for row in creators]
        if not target_keys:
            return 0
        restricted = creator_key is not None or creator_keys is not None
        scope_join = ""
        if restricted and target_keys:
            connection.execute(
                "CREATE TEMP TABLE recompute_targets(creator_key TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            connection.executemany(
                "INSERT INTO recompute_targets(creator_key) VALUES (?)",
                ((key,) for key in target_keys),
            )
            scope_join = (
                "JOIN recompute_targets AS target ON target.creator_key=source.creator_key"
            )

        period_data = _rows_by_creator(connection.execute(
            """SELECT source.creator_key,
                      SUM(source.alliance_gmv_vnd) AS alliance_gmv_vnd,
                      SUM(source.alliance_items) AS alliance_items,
                      SUM(source.estimated_commission_vnd) AS estimated_commission_vnd,
                      SUM(source.targeted_gmv_vnd) AS targeted_gmv_vnd
               FROM raw_creator_periods AS source """ + scope_join + " "
            "WHERE source.platform=? GROUP BY source.creator_key",
            (platform,),
        ))
        raw_creator_data = _rows_by_creator(connection.execute(
            """SELECT source.creator_key,
                      SUM(source.alliance_gmv_vnd) AS alliance_gmv_vnd,
                      SUM(source.alliance_items) AS alliance_items,
                      SUM(source.estimated_commission_vnd) AS estimated_commission_vnd,
                      SUM(source.targeted_gmv_vnd) AS targeted_gmv_vnd
               FROM raw_creator AS source """ + scope_join + " "
            "WHERE source.platform=? GROUP BY source.creator_key",
            (platform,),
        ))
        creator_costs = {
            row["creator_key"]: row["collaboration_cost_vnd"]
            for row in connection.execute(
                "SELECT source.creator_key, source.collaboration_cost_vnd FROM costs AS source "
                + scope_join
                + " WHERE source.platform=? AND source.target_type='creator' AND source.target_id=''",
                (platform,),
            )
        }
        period_batches = _source_batches(
            connection, "raw_creator_periods", platform, scope_join
        )
        raw_creator_batches = _source_batches(connection, "raw_creator", platform, scope_join)

        content_definitions = (
            ("raw_video", "video", "video_id", (
                ("video_attributed_gmv", "attributed_gmv_vnd"),
                ("video_attributed_items", "attributed_items"),
                ("video_views", "views"), ("video_likes", "likes"),
                ("video_comments", "comments"), ("video_shares", "shares"),
                ("video_new_followers", "new_followers"),
            )),
            ("raw_live", "live", "source_record_key", (
                ("live_attributed_gmv", "attributed_gmv_vnd"),
                ("live_attributed_items", "attributed_items"),
                ("live_viewers", "viewers"), ("live_view_count", "view_count"),
                ("live_comments", "comments"), ("live_shares", "shares"),
                ("live_likes", "likes"),
            )),
        )
        content_data: dict[str, dict[str, Any]] = {}
        content_batches: dict[str, dict[str, set[str]]] = {}
        for table, prefix, identifier, definitions in content_definitions:
            summed_fields = ", ".join(
                f"SUM(source.{field}) AS {field}" for _, field in definitions
            )
            content_data[prefix] = _rows_by_creator(connection.execute(
                f"""SELECT source.creator_key, {summed_fields},
                            COUNT(*) AS row_count,
                            SUM(CASE WHEN source.attributed_gmv_vnd IS NOT NULL THEN 1 ELSE 0 END)
                                AS numerator_count,
                            SUM(CASE WHEN cost.slot_fee_vnd IS NOT NULL AND cost.slot_fee_vnd<>0
                                     THEN 1 ELSE 0 END) AS priced_rows,
                            SUM(CASE WHEN cost.slot_fee_vnd IS NOT NULL AND cost.slot_fee_vnd<>0
                                     THEN cost.slot_fee_vnd ELSE 0 END) AS total_cost_vnd
                     FROM {table} AS source
                     {scope_join}
                     LEFT JOIN costs AS cost
                       ON cost.platform=source.platform
                      AND cost.creator_key=source.creator_key
                      AND cost.target_type=?
                      AND cost.target_id=source.{identifier}
                     WHERE source.platform=?
                     GROUP BY source.creator_key""",
                (prefix, platform),
            ))
            content_batches[prefix] = _source_batches(connection, table, platform, scope_join)

        direct_metrics = (
            ("historical_gmv", "alliance_gmv_vnd"),
            ("sold_items", "alliance_items"),
            ("post_collaboration_gmv", "targeted_gmv_vnd"),
        )
        for offset in range(0, len(target_keys), METRIC_BATCH_SIZE):
            chunk = target_keys[offset:offset + METRIC_BATCH_SIZE]
            metric_rows: list[tuple[Any, ...]] = []
            for current_creator_key in chunk:
                creator_values = period_data.get(current_creator_key)
                creator_batches = period_batches.get(current_creator_key, set())
                if creator_values is None:
                    # Old INC-1 databases are readable before their first INC-3 import.
                    creator_values = raw_creator_data.get(current_creator_key)
                    creator_batches = raw_creator_batches.get(current_creator_key, set())

                def creator_sum(field: str) -> int | None:
                    return None if creator_values is None else creator_values[field]

                for metric_name, source_field in direct_metrics:
                    metric_rows.append(_metric_parameters(
                        platform, current_creator_key, metric_name, creator_sum(source_field),
                        "raw_creator", source_field, creator_batches, computed_at,
                    ))

                collaboration_cost = creator_costs.get(current_creator_key)
                creator_roi_config = roi_formulas["creator_total"]
                creator_numerator = creator_sum(creator_roi_config["numerator"])
                historical_roi = None
                if collaboration_cost not in (None, 0) and creator_numerator is not None:
                    historical_roi = (
                        creator_numerator / collaboration_cost
                        * float(creator_roi_config["multiplier"])
                    )
                metric_rows.append(_metric_parameters(
                    platform, current_creator_key, "historical_roi", historical_roi,
                    "raw_creator_periods+costs",
                    f"{creator_roi_config['numerator']}/{creator_roi_config['denominator']}",
                    creator_batches, computed_at,
                ))

                targeted_gmv = creator_sum("targeted_gmv_vnd")
                cost_ratio_roi = None
                if collaboration_cost not in (None, 0) and targeted_gmv is not None:
                    cost_ratio_roi = targeted_gmv / collaboration_cost
                metric_rows.append(_metric_parameters(
                    platform, current_creator_key, "cost_ratio_roi", cost_ratio_roi,
                    "raw_creator+costs", "targeted_gmv_vnd/collaboration_cost_vnd",
                    creator_batches, computed_at,
                ))

                for table, prefix, _, definitions in content_definitions:
                    values = content_data[prefix].get(current_creator_key)
                    batches = content_batches[prefix].get(current_creator_key, set())
                    for metric_name, field in definitions:
                        value = None if values is None else values[field]
                        metric_rows.append(_metric_parameters(
                            platform, current_creator_key, metric_name, value,
                            table, field, batches, computed_at,
                        ))
                    roi_value = None
                    formula = roi_formulas[f"{prefix}_total"]
                    if (
                        values is not None
                        and values["row_count"] == values["priced_rows"]
                        and values["numerator_count"] > 0
                        and values["total_cost_vnd"] not in (None, 0)
                    ):
                        roi_value = (
                            values["attributed_gmv_vnd"] / values["total_cost_vnd"]
                            * float(formula["multiplier"])
                        )
                    metric_rows.append(_metric_parameters(
                        platform, current_creator_key, f"{prefix}_total_roi", roi_value,
                        f"{table}+costs", f"{formula['numerator']}/{formula['denominator']}",
                        batches, computed_at,
                    ))

            connection.executemany(METRIC_UPSERT_SQL, metric_rows)
            connection.commit()
            completed = offset + len(chunk)
            elapsed = time.perf_counter() - started
            eta = 0 if completed == 0 else max(0, round(elapsed / completed * (len(target_keys) - completed)))
            print(
                f"progress: {completed}/{len(target_keys)} elapsed={round(elapsed)}s eta={eta}s",
                file=sys.stderr,
                flush=True,
            )
    return len(creators)


def enqueue_recompute(
    db_path: str | Path,
    creator_keys: list[str] | tuple[str, ...] | set[str],
    reason: str,
    platform: str = PLATFORM,
) -> int:
    """Queue creator derivations after an import or cost edit."""
    if reason not in {"import", "cost"}:
        raise ValueError("增量重算原因必须是 import 或 cost")
    keys = sorted(set(creator_keys))
    if not keys:
        return 0
    initialize_database(db_path)
    queued_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as connection:
        connection.executemany(
            """INSERT INTO recompute_queue(platform, creator_key, reason, queued_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(platform, creator_key, reason) DO UPDATE SET queued_at=excluded.queued_at""",
            ((platform, key, reason, queued_at) for key in keys),
        )
    return len(keys)


def queued_recompute_creators(db_path: str | Path, platform: str = PLATFORM) -> list[str]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT DISTINCT creator_key FROM recompute_queue WHERE platform=? ORDER BY creator_key",
            (platform,),
        ).fetchall()
    return [row["creator_key"] for row in rows]


def clear_recompute_queue(
    db_path: str | Path,
    creator_keys: list[str] | tuple[str, ...] | set[str] | None = None,
    platform: str = PLATFORM,
) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        if creator_keys is None:
            connection.execute("DELETE FROM recompute_queue WHERE platform=?", (platform,))
            return
        for offset in range(0, len(creator_keys), 500):
            chunk = list(creator_keys)[offset:offset + 500]
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            connection.execute(
                f"DELETE FROM recompute_queue WHERE platform=? AND creator_key IN ({placeholders})",
                (platform, *chunk),
            )


def recompute_incremental(
    db_path: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    platform: str = PLATFORM,
) -> int:
    """Refresh only creators queued by recent imports or cost supplementation."""
    keys = queued_recompute_creators(db_path, platform)
    if not keys:
        return 0
    count = recompute_metrics(db_path, platform, config_path=config_path, creator_keys=keys)
    from rating import recompute_ratings

    recompute_ratings(db_path, config_path, platform, creator_keys=keys)
    clear_recompute_queue(db_path, keys, platform)
    return count


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="重算达人指标")
    parser.add_argument("--db", default="daren_library.db")
    arguments = parser.parse_args()
    count = recompute_metrics(arguments.db)
    print(json.dumps({"creators_recomputed": count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
