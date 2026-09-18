"""INC-3 period analytics and creator-specific editable records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from db import connect, initialize_database
from importer import PLATFORM
from rating import DEFAULT_CONFIG_PATH, load_rating_config


GRAINS = {"total", "day", "week", "month", "year"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_creator(connection: Any, creator_key: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM creators WHERE platform=? AND creator_key=?", (PLATFORM, creator_key)
    ).fetchone()
    if row is None:
        raise KeyError(f"达人不存在: {creator_key}")


def period_token(start: str, end: str) -> str:
    return f"{start}|{end}"


def parse_period_token(value: str | None) -> tuple[str, str] | None:
    if not value or value == "total":
        return None
    parts = value.split("|", 1)
    if len(parts) != 2:
        raise ValueError("业务期间参数非法")
    try:
        start = datetime.fromisoformat(parts[0]).date().isoformat()
        end = datetime.fromisoformat(parts[1]).date().isoformat()
    except ValueError as exc:
        raise ValueError("业务期间参数必须为 YYYY-MM-DD|YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("业务期间开始日期不能晚于结束日期")
    return start, end


def list_business_periods(db_path: str | Path, source_type: str | None = None) -> list[dict[str, str]]:
    initialize_database(db_path)
    clauses = ["platform=?", "period_start IS NOT NULL", "period_end IS NOT NULL"]
    params: list[Any] = [PLATFORM]
    if source_type:
        clauses.append("source_type=?")
        params.append(source_type)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""SELECT period_start, period_end,
                       GROUP_CONCAT(DISTINCT period_source) AS sources
                FROM import_batches WHERE {' AND '.join(clauses)}
                GROUP BY period_start, period_end
                ORDER BY period_start DESC, period_end DESC""",
            params,
        ).fetchall()
    return [
        {
            "start": row["period_start"], "end": row["period_end"],
            "token": period_token(row["period_start"], row["period_end"]),
            "source": row["sources"] or "import_time",
        }
        for row in rows
    ]


def creator_period_metrics(
    db_path: str | Path, creator_key: str, selected_period: str = "total"
) -> dict[str, int | None]:
    initialize_database(db_path)
    period = parse_period_token(selected_period)
    clauses = ["platform=?", "creator_key=?"]
    params: list[Any] = [PLATFORM, creator_key]
    if period:
        clauses.extend(("period_start=?", "period_end=?"))
        params.extend(period)
    with connect(db_path) as connection:
        row = connection.execute(
            f"""SELECT SUM(alliance_gmv_vnd) AS historical_gmv,
                       SUM(alliance_items) AS sold_items,
                       SUM(estimated_commission_vnd) AS estimated_commission,
                       SUM(targeted_gmv_vnd) AS post_collaboration_gmv
                FROM raw_creator_periods WHERE {' AND '.join(clauses)}""",
            params,
        ).fetchone()
    return {name: row[name] for name in row.keys()}


def all_creator_period_metrics(db_path: str | Path, selected_period: str = "total") -> dict[str, dict[str, int | None]]:
    initialize_database(db_path)
    period = parse_period_token(selected_period)
    clauses = ["platform=?"]
    params: list[Any] = [PLATFORM]
    if period:
        clauses.extend(("period_start=?", "period_end=?"))
        params.extend(period)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""SELECT creator_key, SUM(alliance_gmv_vnd) AS historical_gmv,
                       SUM(alliance_items) AS sold_items,
                       SUM(targeted_gmv_vnd) AS post_collaboration_gmv
                FROM raw_creator_periods WHERE {' AND '.join(clauses)}
                GROUP BY creator_key""",
            params,
        ).fetchall()
    return {row["creator_key"]: {name: row[name] for name in row.keys() if name != "creator_key"} for row in rows}


def _bucket(iso_value: str | None, grain: str) -> str:
    if grain == "total":
        return "总"
    if iso_value is None:
        raise ValueError("非总计聚合需要有效的行日期")
    parsed = datetime.fromisoformat(iso_value)
    if grain == "day":
        return parsed.date().isoformat()
    if grain == "week":
        year, week, _ = parsed.isocalendar()
        return f"{year}-W{week:02d}"
    if grain == "month":
        return f"{parsed.year:04d}-{parsed.month:02d}"
    if grain == "year":
        return str(parsed.year)
    raise ValueError(f"未知聚合粒度: {grain}")


def aggregate_content(
    db_path: str | Path,
    source_type: str,
    creator_key: str | None = None,
    grain: str = "total",
    selected_period: str = "total",
) -> list[dict[str, Any]]:
    if source_type not in {"video", "live"}:
        raise ValueError("内容类型必须是 video 或 live")
    if grain not in GRAINS:
        raise ValueError("聚合粒度必须是 day/week/month/year/total")
    initialize_database(db_path)
    table = f"raw_{source_type}"
    date_field = "published_at" if source_type == "video" else "event_at_utc7"
    fields = (
        ("attributed_gmv_vnd", "attributed_gmv_vnd"),
        ("attributed_items", "attributed_items"),
        (("views", "likes", "comments", "shares", "new_followers") if source_type == "video"
         else ("viewers", "view_count", "comments", "shares", "likes")),
    )
    numeric_fields = [fields[0][0], fields[1][0], *fields[2]]
    clauses = ["platform=?"]
    params: list[Any] = [PLATFORM]
    if creator_key:
        clauses.append("creator_key=?")
        params.append(creator_key)
    period = parse_period_token(selected_period)
    if grain != "total" or period:
        clauses.append(f"{date_field} IS NOT NULL")
    if period:
        clauses.extend((f"substr({date_field},1,10)>=?", f"substr({date_field},1,10)<=?"))
        params.extend(period)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT {date_field}, {', '.join(numeric_fields)} FROM {table} "
            f"WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _bucket(row[date_field], grain)
        target = buckets.setdefault(key, {"period": key, "records": 0, **{field: 0 for field in numeric_fields}})
        target["records"] += 1
        for field in numeric_fields:
            if row[field] is not None:
                target[field] += row[field]
    return [buckets[key] for key in sorted(buckets)]


def product_breakdown(
    db_path: str | Path, creator_key: str, selected_period: str = "total"
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    clauses = ["v.platform=?", "v.creator_key=?", "v.product_name IS NOT NULL", "v.product_name<>''"]
    params: list[Any] = [PLATFORM, creator_key]
    period = parse_period_token(selected_period)
    if period:
        clauses.extend(("substr(v.published_at,1,10)>=?", "substr(v.published_at,1,10)<=?"))
        params.extend(period)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""SELECT v.product_name, SUM(v.views) AS vv,
                       SUM(v.attributed_gmv_vnd) AS attributed_gmv_vnd,
                       SUM(v.attributed_items) AS attributed_items
                FROM raw_video v WHERE {' AND '.join(clauses)}
                GROUP BY v.product_name ORDER BY attributed_gmv_vnd DESC, v.product_name""",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def content_items_with_roi(
    db_path: str | Path,
    creator_key: str,
    source_type: str,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    selected_period: str = "total",
) -> list[dict[str, Any]]:
    if source_type not in {"video", "live"}:
        raise ValueError("内容类型必须是 video 或 live")
    initialize_database(db_path)
    config = load_rating_config(config_path)["roi_formulas"][f"{source_type}_single"]
    table = f"raw_{source_type}"
    identifier = "video_id" if source_type == "video" else "source_record_key"
    date_field = "published_at" if source_type == "video" else "event_at_utc7"
    period = parse_period_token(selected_period)
    date_filter = ""
    params: list[Any] = [source_type, PLATFORM, creator_key]
    if period:
        date_filter = f" AND substr(r.{date_field},1,10)>=? AND substr(r.{date_field},1,10)<=?"
        params.extend(period)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""SELECT r.{identifier} AS target_id, r.{date_field} AS event_at,
                       r.attributed_gmv_vnd, c.slot_fee_vnd
                FROM {table} r LEFT JOIN costs c
                  ON c.platform=r.platform AND c.creator_key=r.creator_key
                 AND c.target_type=? AND c.target_id=r.{identifier}
                WHERE r.platform=? AND r.creator_key=?{date_filter} ORDER BY r.{date_field}""",
            params,
        ).fetchall()
    result = []
    for row in rows:
        roi = None
        if row["slot_fee_vnd"] not in (None, 0) and row["attributed_gmv_vnd"] is not None:
            roi = row["attributed_gmv_vnd"] / row["slot_fee_vnd"] * float(config["multiplier"])
        result.append({**dict(row), "roi": roi})
    return result


def save_target_cost(
    db_path: str | Path, creator_key: str, target_type: str, target_id: str, slot_fee_vnd: int | None
) -> None:
    if target_type not in {"video", "live"}:
        raise ValueError("坑位费粒度必须是 video 或 live")
    if not target_id:
        raise ValueError("视频ID/直播复合键不能为空")
    if slot_fee_vnd is not None and slot_fee_vnd <= 0:
        raise ValueError("坑位费必须是 VND 正整数；空值表示待补录")
    initialize_database(db_path)
    with connect(db_path) as connection:
        _ensure_creator(connection, creator_key)
        connection.execute(
            """INSERT INTO costs(
                   platform, creator_key, target_type, target_id, slot_fee_vnd, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform, creator_key, target_type, target_id) DO UPDATE SET
                   slot_fee_vnd=excluded.slot_fee_vnd, updated_at=excluded.updated_at""",
            (PLATFORM, creator_key, target_type, target_id, slot_fee_vnd, _now()),
        )
    from metrics import enqueue_recompute

    enqueue_recompute(db_path, [creator_key], "cost", PLATFORM)


def list_followups(db_path: str | Path, creator_key: str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM bd_followups WHERE platform=? AND creator_key=? ORDER BY followed_at DESC, followup_id DESC",
            (PLATFORM, creator_key),
        ).fetchall()
    return [dict(row) for row in rows]


def save_followup(
    db_path: str | Path, creator_key: str, followed_at: str, bd_name: str,
    content: str, next_step: str = "", followup_id: int | None = None,
) -> int:
    if not followed_at.strip() or not bd_name.strip() or not content.strip():
        raise ValueError("跟进时间、BD、内容均不能为空")
    now = _now()
    initialize_database(db_path)
    with connect(db_path) as connection:
        _ensure_creator(connection, creator_key)
        if followup_id is None:
            cursor = connection.execute(
                """INSERT INTO bd_followups(
                       platform, creator_key, followed_at, bd_name, content, next_step, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (PLATFORM, creator_key, followed_at.strip(), bd_name.strip(), content.strip(), next_step.strip(), now, now),
            )
            return int(cursor.lastrowid)
        cursor = connection.execute(
            """UPDATE bd_followups SET followed_at=?, bd_name=?, content=?, next_step=?, updated_at=?
               WHERE followup_id=? AND platform=? AND creator_key=?""",
            (followed_at.strip(), bd_name.strip(), content.strip(), next_step.strip(), now,
             followup_id, PLATFORM, creator_key),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"跟进记录不存在: {followup_id}")
        return followup_id


def delete_followup(db_path: str | Path, creator_key: str, followup_id: int) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        cursor = connection.execute(
            "DELETE FROM bd_followups WHERE followup_id=? AND platform=? AND creator_key=?",
            (followup_id, PLATFORM, creator_key),
        )
        if cursor.rowcount != 1:
            raise KeyError(f"跟进记录不存在: {followup_id}")


def save_commissions(
    db_path: str | Path, creator_key: str, start: str, end: str,
    organic_vnd: int | None, paid_vnd: int | None,
) -> None:
    initialize_database(db_path)
    parse_period_token(period_token(start, end))
    for label, value in (("自然流佣金", organic_vnd), ("付费流佣金", paid_vnd)):
        if value is not None and value < 0:
            raise ValueError(f"{label}必须是 VND 非负整数")
    with connect(db_path) as connection:
        _ensure_creator(connection, creator_key)
        connection.execute(
            """INSERT INTO commissions(
                   platform, creator_key, period_start, period_end,
                   organic_commission_vnd, paid_commission_vnd, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform, creator_key, period_start, period_end) DO UPDATE SET
                   organic_commission_vnd=excluded.organic_commission_vnd,
                   paid_commission_vnd=excluded.paid_commission_vnd,
                   updated_at=excluded.updated_at""",
            (PLATFORM, creator_key, start, end, organic_vnd, paid_vnd, _now()),
        )


def delete_commissions(db_path: str | Path, creator_key: str, start: str, end: str) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "DELETE FROM commissions WHERE platform=? AND creator_key=? AND period_start=? AND period_end=?",
            (PLATFORM, creator_key, start, end),
        )


def create_tag(db_path: str | Path, name: str) -> int:
    initialize_database(db_path)
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("标签名称不能为空")
    with connect(db_path) as connection:
        cursor = connection.execute(
            "INSERT INTO tags(name, is_preset, created_at) VALUES (?, 0, ?)", (cleaned, _now())
        )
        return int(cursor.lastrowid)


def rename_tag(db_path: str | Path, tag_id: int, name: str) -> None:
    initialize_database(db_path)
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("标签名称不能为空")
    with connect(db_path) as connection:
        cursor = connection.execute(
            "UPDATE tags SET name=? WHERE tag_id=? AND is_preset=0", (cleaned, tag_id)
        )
        if cursor.rowcount != 1:
            raise KeyError("标签不存在或预置标签不可改名")


def delete_tag(db_path: str | Path, tag_id: int) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        cursor = connection.execute("DELETE FROM tags WHERE tag_id=? AND is_preset=0", (tag_id,))
        if cursor.rowcount != 1:
            raise KeyError("标签不存在或预置标签不可删除")


def assign_tag(db_path: str | Path, creator_key: str, tag_id: int) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        _ensure_creator(connection, creator_key)
        if connection.execute("SELECT 1 FROM tags WHERE tag_id=?", (tag_id,)).fetchone() is None:
            raise KeyError(f"标签不存在: {tag_id}")
        connection.execute(
            "INSERT OR IGNORE INTO creator_tags(platform, creator_key, tag_id, created_at) VALUES (?, ?, ?, ?)",
            (PLATFORM, creator_key, tag_id, _now()),
        )


def unassign_tag(db_path: str | Path, creator_key: str, tag_id: int) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "DELETE FROM creator_tags WHERE platform=? AND creator_key=? AND tag_id=?",
            (PLATFORM, creator_key, tag_id),
        )


def save_note(db_path: str | Path, creator_key: str, note: str) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        _ensure_creator(connection, creator_key)
        if not note.strip():
            connection.execute(
                "DELETE FROM creator_annotations WHERE platform=? AND creator_key=?", (PLATFORM, creator_key)
            )
            return
        connection.execute(
            """INSERT INTO creator_annotations(platform, creator_key, note, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(platform, creator_key) DO UPDATE SET
                   note=excluded.note, updated_at=excluded.updated_at""",
            (PLATFORM, creator_key, note.strip(), _now()),
        )


def creator_annotations(db_path: str | Path, creator_keys: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT c.creator_key, COALESCE(a.note, '') AS note,
                      COALESCE(GROUP_CONCAT(t.name, ' / '), '') AS tags
               FROM creators c
               LEFT JOIN creator_annotations a
                 ON a.platform=c.platform AND a.creator_key=c.creator_key
               LEFT JOIN creator_tags ct
                 ON ct.platform=c.platform AND ct.creator_key=c.creator_key
               LEFT JOIN tags t ON t.tag_id=ct.tag_id
               WHERE c.platform=? GROUP BY c.creator_key""",
            (PLATFORM,),
        ).fetchall()
    wanted = None if creator_keys is None else set(creator_keys)
    return {
        row["creator_key"]: {"note": row["note"], "tags": row["tags"]}
        for row in rows if wanted is None or row["creator_key"] in wanted
    }
