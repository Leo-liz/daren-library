"""Config-driven, explainable S/A/B/C/D creator ratings."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import connect, initialize_database


PLATFORM = "tiktok_shop_vn"
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config") / "rating_rules.json"
SUPPORTED_METRICS = {
    "historical_gmv",
    "sold_items",
    "post_collaboration_gmv",
    "historical_roi",
    "cost_ratio_roi",
}
EXPECTED_GRADES = ("S", "A", "B", "C", "D")
DEFAULT_ROI_FORMULAS = {
    "creator_total": {"expression": "预计佣金 / 合作成本", "numerator": "estimated_commission_vnd", "denominator": "collaboration_cost_vnd", "multiplier": 1, "status": "暂定"},
    "video_total": {"expression": "Σ视频归因 GMV / Σ视频坑位费", "numerator": "attributed_gmv_vnd", "denominator": "slot_fee_vnd", "multiplier": 1, "status": "暂定"},
    "video_single": {"expression": "该视频归因 GMV / 该视频坑位费", "numerator": "attributed_gmv_vnd", "denominator": "slot_fee_vnd", "multiplier": 1, "status": "暂定"},
    "live_total": {"expression": "Σ直播归因 GMV / Σ直播坑位费", "numerator": "attributed_gmv_vnd", "denominator": "slot_fee_vnd", "multiplier": 1, "status": "暂定"},
    "live_single": {"expression": "该直播归因 GMV / 该直播坑位费", "numerator": "attributed_gmv_vnd", "denominator": "slot_fee_vnd", "multiplier": 1, "status": "暂定"},
}


class RatingConfigError(ValueError):
    """Raised when rating rules are missing, malformed, or unsafe to apply."""


def _require_status(value: Any, location: str) -> None:
    if not isinstance(value, dict) or value.get("status") != "暂定":
        raise RatingConfigError(f"评级配置 {location} 必须标注 status=暂定")


def load_rating_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    try:
        raw = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RatingConfigError(f"评级配置文件不存在: {config_path}") from exc
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RatingConfigError(
            f"评级配置不是合法 JSON: {config_path}（第 {exc.lineno} 行第 {exc.colno} 列）"
        ) from exc
    if not isinstance(config, dict):
        raise RatingConfigError("评级配置根节点必须是对象")
    # INC-2 custom configs remain readable; /config persists this injected
    # section on the first successful edit.
    config.setdefault("roi_formulas", copy.deepcopy(DEFAULT_ROI_FORMULAS))

    missing = [
        key for key in (
            "version", "status", "score_range", "missing_metric_policy",
            "available_metrics", "weights", "tiers", "formulas", "roi_formulas",
        ) if key not in config
    ]
    if missing:
        raise RatingConfigError(f"评级配置缺少字段: {', '.join(missing)}")
    if config["status"] != "暂定":
        raise RatingConfigError("评级配置根节点必须标注 status=暂定")
    if not isinstance(config["version"], int) or isinstance(config["version"], bool):
        raise RatingConfigError("评级配置 version 必须是整数")

    score_range = config["score_range"]
    _require_status(score_range, "score_range")
    if score_range.get("min") != 0 or score_range.get("max") != 100:
        raise RatingConfigError("评级配置 score_range 必须为 0..100")

    missing_policy = config["missing_metric_policy"]
    _require_status(missing_policy, "missing_metric_policy")
    if missing_policy.get("value") != "exclude_and_renormalize":
        raise RatingConfigError("评级配置仅支持 missing_metric_policy=exclude_and_renormalize")

    available = config["available_metrics"]
    if not isinstance(available, dict) or not available:
        raise RatingConfigError("评级配置 available_metrics 必须是非空对象")
    unknown = sorted(set(available) - SUPPORTED_METRICS)
    if unknown:
        raise RatingConfigError(f"评级配置包含不支持的指标: {', '.join(unknown)}")
    for metric_name, definition in available.items():
        _require_status(definition, f"available_metrics.{metric_name}")
        if not isinstance(definition.get("label"), str) or not definition["label"].strip():
            raise RatingConfigError(f"评级配置指标 {metric_name} 缺少可读 label")
        if definition.get("normalization") != "min_max":
            raise RatingConfigError(f"评级配置指标 {metric_name} 仅支持 min_max 归一化")

    weights = config["weights"]
    if not isinstance(weights, dict) or not weights:
        raise RatingConfigError("评级配置 weights 必须是非空对象")
    if not set(weights).issubset(available):
        invalid = sorted(set(weights) - set(available))
        raise RatingConfigError(f"评级配置权重引用了未声明指标: {', '.join(invalid)}")
    positive_weight = False
    for metric_name, definition in weights.items():
        _require_status(definition, f"weights.{metric_name}")
        value = definition.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise RatingConfigError(f"评级配置权重 {metric_name} 必须是有限数字")
        if value < 0:
            raise RatingConfigError(f"评级配置权重 {metric_name} 不得为负数")
        positive_weight = positive_weight or value > 0
    if not positive_weight:
        raise RatingConfigError("评级配置至少需要一个大于 0 的权重")

    tiers = config["tiers"]
    if not isinstance(tiers, list) or len(tiers) != len(EXPECTED_GRADES):
        raise RatingConfigError("评级配置 tiers 必须恰好包含 S/A/B/C/D 五档")
    if tuple(tier.get("grade") for tier in tiers) != EXPECTED_GRADES:
        raise RatingConfigError("评级配置 tiers 必须按 S/A/B/C/D 顺序排列")
    expected_upper = 100.0
    for index, tier in enumerate(tiers):
        _require_status(tier, f"tiers[{index}]")
        low, high = tier.get("min_score"), tier.get("max_score")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (low, high)):
            raise RatingConfigError(f"评级配置档位 {tier.get('grade')} 阈值必须是数字")
        if low < 0 or high > 100 or low >= high:
            raise RatingConfigError(f"评级配置档位 {tier['grade']} 阈值区间非法")
        if float(high) != expected_upper:
            raise RatingConfigError(f"评级配置档位 {tier['grade']} 与上一档存在空隙或重叠")
        should_include_max = index == 0
        if tier.get("max_inclusive") is not should_include_max:
            raise RatingConfigError(f"评级配置档位 {tier['grade']} 的 max_inclusive 非法")
        expected_upper = float(low)
    if expected_upper != 0:
        raise RatingConfigError("评级配置档位必须完整覆盖 0..100")

    formulas = config["formulas"]
    required_formulas = {"normalization", "rating_score", "historical_roi", "cost_ratio_roi"}
    if not isinstance(formulas, dict) or not required_formulas.issubset(formulas):
        missing_formulas = sorted(required_formulas - set(formulas or {}))
        raise RatingConfigError(f"评级配置缺少口径公式: {', '.join(missing_formulas)}")
    for formula_name, definition in formulas.items():
        _require_status(definition, f"formulas.{formula_name}")
        if not isinstance(definition.get("expression"), str) or not definition["expression"].strip():
            raise RatingConfigError(f"评级配置公式 {formula_name} 不能为空")

    roi_formulas = config["roi_formulas"]
    required_roi_formulas = {
        "creator_total", "video_total", "video_single", "live_total", "live_single",
    }
    if not isinstance(roi_formulas, dict) or set(roi_formulas) != required_roi_formulas:
        raise RatingConfigError("评级配置 roi_formulas 必须完整包含达人/视频/直播五种 ROI")
    allowed_fields = {
        "creator_total": ({"estimated_commission_vnd", "targeted_gmv_vnd"}, {"collaboration_cost_vnd"}),
        "video_total": ({"attributed_gmv_vnd"}, {"slot_fee_vnd"}),
        "video_single": ({"attributed_gmv_vnd"}, {"slot_fee_vnd"}),
        "live_total": ({"attributed_gmv_vnd"}, {"slot_fee_vnd"}),
        "live_single": ({"attributed_gmv_vnd"}, {"slot_fee_vnd"}),
    }
    for name, definition in roi_formulas.items():
        _require_status(definition, f"roi_formulas.{name}")
        if not isinstance(definition.get("expression"), str) or not definition["expression"].strip():
            raise RatingConfigError(f"评级配置 ROI 公式 {name} 的 expression 不能为空")
        numerators, denominators = allowed_fields[name]
        if definition.get("numerator") not in numerators:
            raise RatingConfigError(f"评级配置 ROI 公式 {name} 的 numerator 不受支持")
        if definition.get("denominator") not in denominators:
            raise RatingConfigError(f"评级配置 ROI 公式 {name} 的 denominator 不受支持")
        multiplier = definition.get("multiplier")
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or not math.isfinite(multiplier):
            raise RatingConfigError(f"评级配置 ROI 公式 {name} 的 multiplier 必须是有限数字")
        if multiplier <= 0:
            raise RatingConfigError(f"评级配置 ROI 公式 {name} 的 multiplier 必须大于 0")
    return config


def config_hash(config: dict[str, Any]) -> str:
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _grade_for_score(score: float, tiers: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    for tier in tiers:
        if score >= float(tier["min_score"]):
            return str(tier["grade"]), tier
    raise RuntimeError(f"得分 {score} 未命中任何评级档位")


def recompute_ratings(
    db_path: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    platform: str = PLATFORM,
    creator_keys: list[str] | tuple[str, ...] | set[str] | None = None,
) -> int:
    """Recompute all ratings, or only explicitly affected creators."""
    config = load_rating_config(config_path)
    rules_hash = config_hash(config)
    metric_names = [name for name, item in config["weights"].items() if item["value"] > 0]
    initialize_database(db_path)
    computed_at = datetime.now(timezone.utc).isoformat()

    with connect(db_path) as connection:
        if creator_keys is None:
            creators = connection.execute(
                "SELECT creator_key FROM creators WHERE platform=? ORDER BY creator_key", (platform,)
            ).fetchall()
        else:
            creators = []
            wanted = sorted(set(creator_keys))
            for offset in range(0, len(wanted), 500):
                chunk = wanted[offset:offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                creators.extend(connection.execute(
                    f"SELECT creator_key FROM creators WHERE platform=? AND creator_key IN ({placeholders}) ORDER BY creator_key",
                    (platform, *chunk),
                ).fetchall())
        target_keys = [row["creator_key"] for row in creators]
        values_by_creator: dict[str, dict[str, float | None]] = {key: {} for key in target_keys}
        if target_keys:
            metric_placeholders = ",".join("?" for _ in metric_names)
            for offset in range(0, len(target_keys), 500):
                chunk = target_keys[offset:offset + 500]
                creator_placeholders = ",".join("?" for _ in chunk)
                metric_rows = connection.execute(
                    f"""SELECT creator_key, metric_name, metric_value FROM metrics
                        WHERE platform=? AND metric_name IN ({metric_placeholders})
                          AND creator_key IN ({creator_placeholders})""",
                    (platform, *metric_names, *chunk),
                ).fetchall()
                for row in metric_rows:
                    values_by_creator[row["creator_key"]][row["metric_name"]] = row["metric_value"]

        ranges: dict[str, tuple[float | None, float | None]] = {}
        if metric_names:
            placeholders = ",".join("?" for _ in metric_names)
            range_rows = connection.execute(
                f"""SELECT metric_name, MIN(metric_value) AS minimum, MAX(metric_value) AS maximum
                    FROM metrics WHERE platform=? AND metric_name IN ({placeholders})
                    AND metric_value IS NOT NULL GROUP BY metric_name""",
                (platform, *metric_names),
            ).fetchall()
            found_ranges = {row["metric_name"]: (row["minimum"], row["maximum"]) for row in range_rows}
            ranges = {name: found_ranges.get(name, (None, None)) for name in metric_names}

        for creator in creators:
            creator_key = creator["creator_key"]
            evidence_metrics: list[dict[str, Any]] = []
            weighted_total = 0.0
            effective_weight = 0.0
            for metric_name in metric_names:
                raw_value = values_by_creator.get(creator_key, {}).get(metric_name)
                if raw_value is None:
                    continue
                minimum, maximum = ranges[metric_name]
                if minimum is None or maximum is None:
                    continue
                normalized = 50.0 if maximum == minimum else (float(raw_value) - minimum) / (maximum - minimum) * 100
                weight = float(config["weights"][metric_name]["value"])
                weighted = normalized * weight
                weighted_total += weighted
                effective_weight += weight
                evidence_metrics.append({
                    "metric": metric_name,
                    "label": config["available_metrics"][metric_name]["label"],
                    "value": raw_value,
                    "population_min": minimum,
                    "population_max": maximum,
                    "normalized_score": round(normalized, 6),
                    "configured_weight": weight,
                    "weighted_score": round(weighted, 6),
                    "status": "暂定",
                })
            score = weighted_total / effective_weight if effective_weight else 0.0
            score = min(100.0, max(0.0, score))
            grade, matched_tier = _grade_for_score(score, config["tiers"])
            evidence = {
                "status": "暂定",
                "config_version": config["version"],
                "rules_hash": rules_hash,
                "formula": config["formulas"]["rating_score"]["expression"],
                "missing_metric_policy": config["missing_metric_policy"]["description"],
                "participating_metrics": evidence_metrics,
                "score": round(score, 6),
                "matched_interval": {
                    "grade": grade,
                    "min_score": matched_tier["min_score"],
                    "max_score": matched_tier["max_score"],
                    "min_inclusive": True,
                    "max_inclusive": matched_tier["max_inclusive"],
                    "status": "暂定",
                },
            }
            connection.execute(
                """
                INSERT INTO ratings(platform, creator_key, grade, score, evidence_json, rules_hash, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, creator_key) DO UPDATE SET
                    grade=excluded.grade, score=excluded.score,
                    evidence_json=excluded.evidence_json, rules_hash=excluded.rules_hash,
                    computed_at=excluded.computed_at
                """,
                (
                    platform, creator_key, grade, score,
                    json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                    rules_hash, computed_at,
                ),
            )
        if creator_keys is None:
            connection.execute(
                "DELETE FROM ratings WHERE platform=? AND creator_key NOT IN "
                "(SELECT creator_key FROM creators WHERE platform=?)",
                (platform, platform),
            )
    return len(creators)


def ensure_ratings_current(
    db_path: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    platform: str = PLATFORM,
) -> bool:
    """Recompute lazily when a config edit or creator-set change is detected."""
    config = load_rating_config(config_path)
    expected_hash = config_hash(config)
    initialize_database(db_path)
    with connect(db_path) as connection:
        creator_count = connection.execute(
            "SELECT COUNT(*) FROM creators WHERE platform=?", (platform,)
        ).fetchone()[0]
        current_count, stale_count = connection.execute(
            """
            SELECT COUNT(*), SUM(CASE WHEN rules_hash<>? THEN 1 ELSE 0 END)
            FROM ratings WHERE platform=?
            """,
            (expected_hash, platform),
        ).fetchone()
    if current_count != creator_count or (stale_count or 0) > 0:
        recompute_ratings(db_path, config_path, platform)
        return True
    return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="按外置规则重算达人等级")
    parser.add_argument("--db", default="daren_library.db")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    arguments = parser.parse_args()
    count = recompute_ratings(arguments.db, arguments.config)
    print(json.dumps({"creators_recomputed": count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
