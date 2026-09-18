"""Validated config editing, recalculation, and audit logging for /config."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from db import connect, initialize_database
from metrics import recompute_metrics
from rating import PLATFORM, load_rating_config, recompute_ratings


BOUNDARIES = {
    "S_A": (0, 1),
    "A_B": (1, 2),
    "B_C": (2, 3),
    "C_D": (3, 4),
}


def editable_values(config: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, definition in config["weights"].items():
        result[f"weights.{name}"] = definition["value"]
    for name, (upper_index, lower_index) in BOUNDARIES.items():
        result[f"tier_boundaries.{name}"] = config["tiers"][upper_index]["min_score"]
        assert config["tiers"][lower_index]["max_score"] == result[f"tier_boundaries.{name}"]
    for name, definition in config["roi_formulas"].items():
        result[f"roi_formulas.{name}.expression"] = definition["expression"]
        result[f"roi_formulas.{name}.numerator"] = definition["numerator"]
        result[f"roi_formulas.{name}.denominator"] = definition["denominator"]
        result[f"roi_formulas.{name}.multiplier"] = definition["multiplier"]
    return result


def _number(value: Any, key: str) -> float:
    try:
        parsed = float(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"配置 {key} 必须是数字") from exc
    return parsed


def update_config(
    db_path: str | Path,
    config_path: str | Path,
    updates: Mapping[str, Any],
) -> list[dict[str, Any]]:
    current = load_rating_config(config_path)
    before = editable_values(current)
    candidate = copy.deepcopy(current)
    recognized = set(before)
    unknown = sorted(set(updates) - recognized)
    if unknown:
        raise ValueError(f"不支持的配置键: {', '.join(unknown)}")

    for key, raw_value in updates.items():
        parts = key.split(".")
        if parts[0] == "weights":
            candidate["weights"][parts[1]]["value"] = _number(raw_value, key)
        elif parts[0] == "tier_boundaries":
            value = _number(raw_value, key)
            upper_index, lower_index = BOUNDARIES[parts[1]]
            candidate["tiers"][upper_index]["min_score"] = value
            candidate["tiers"][lower_index]["max_score"] = value
        elif parts[-1] == "multiplier":
            candidate["roi_formulas"][parts[1]]["multiplier"] = _number(raw_value, key)
        elif parts[-1] in {"numerator", "denominator"}:
            candidate["roi_formulas"][parts[1]][parts[-1]] = str(raw_value).strip()
        else:
            expression = str(raw_value).strip()
            if not expression:
                raise ValueError(f"配置 {key} 不能为空")
            candidate["roi_formulas"][parts[1]]["expression"] = expression

    config_path = Path(config_path)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        validated = load_rating_config(temporary)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    after = editable_values(validated)
    changes = [
        {"key": key, "old": before[key], "new": after[key]}
        for key in before if before[key] != after[key]
    ]
    if not changes:
        temporary.unlink(missing_ok=True)
        return []
    temporary.replace(config_path)

    initialize_database(db_path)
    from datetime import datetime, timezone
    changed_at = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO config_change_log(changed_at, config_key, old_value, new_value) VALUES (?, ?, ?, ?)",
            ((changed_at, item["key"], json.dumps(item["old"], ensure_ascii=False),
              json.dumps(item["new"], ensure_ascii=False)) for item in changes),
        )
    recompute_metrics(db_path, PLATFORM, config_path=config_path)
    recompute_ratings(db_path, config_path, PLATFORM)
    return changes


def config_change_log(db_path: str | Path, limit: int = 100) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM config_change_log ORDER BY change_id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
