"""Dependency-free local web UI for creator profiles and cost entry."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from analytics import (
    GRAINS,
    aggregate_content,
    assign_tag,
    content_items_with_roi,
    creator_annotations,
    creator_period_metrics,
    create_tag,
    delete_followup,
    list_business_periods,
    list_followups,
    parse_period_token,
    product_breakdown,
    save_commissions,
    save_followup,
    save_note,
    save_target_cost,
    unassign_tag,
)
from config_admin import config_change_log, editable_values, update_config
from calculator import PLACEHOLDER_MESSAGE
from db import UNPERIODIZED_DATE, connect, initialize_database
from metrics import (
    clear_recompute_queue,
    enqueue_recompute,
    recompute_incremental,
    recompute_metrics,
)
from rating import (
    DEFAULT_CONFIG_PATH,
    PLATFORM,
    RatingConfigError,
    ensure_ratings_current,
    load_rating_config,
    recompute_ratings,
)


CORE_METRICS = (
    "historical_gmv",
    "sold_items",
    "historical_roi",
    "post_collaboration_gmv",
    "cost_ratio_roi",
)


def _metric_map(connection: Any, creator_key: str) -> dict[str, float | None]:
    rows = connection.execute(
        "SELECT metric_name, metric_value FROM metrics WHERE platform=? AND creator_key=?",
        (PLATFORM, creator_key),
    ).fetchall()
    return {row["metric_name"]: row["metric_value"] for row in rows}


def load_creator_profile(
    db_path: str | Path,
    creator_key: str,
    selected_period: str = "total",
    grain: str = "total",
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any] | None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        creator = connection.execute(
            "SELECT * FROM creators WHERE platform=? AND creator_key=?",
            (PLATFORM, creator_key),
        ).fetchone()
        if creator is None:
            return None
        cost = connection.execute(
            "SELECT quote_vnd, collaboration_cost_vnd, updated_at FROM costs "
            "WHERE platform=? AND creator_key=? AND target_type='creator' AND target_id=''",
            (PLATFORM, creator_key),
        ).fetchone()
        rating = connection.execute(
            "SELECT grade, score, evidence_json, computed_at FROM ratings "
            "WHERE platform=? AND creator_key=?",
            (PLATFORM, creator_key),
        ).fetchone()
        quality = connection.execute(
            """
            SELECT AVG(completion_rate) AS completion_rate,
                   AVG(ctor) AS ctor,
                   SUM(interactions) AS interactions
            FROM raw_video WHERE platform=? AND creator_key=?
            """,
            (PLATFORM, creator_key),
        ).fetchone()
        metrics = _metric_map(connection, creator_key)
        annotation = connection.execute(
            "SELECT note FROM creator_annotations WHERE platform=? AND creator_key=?",
            (PLATFORM, creator_key),
        ).fetchone()
        tag_rows = connection.execute(
            """SELECT t.tag_id, t.name FROM tags t JOIN creator_tags ct ON ct.tag_id=t.tag_id
               WHERE ct.platform=? AND ct.creator_key=? ORDER BY t.name""",
            (PLATFORM, creator_key),
        ).fetchall()
        available_tags = connection.execute("SELECT tag_id, name, is_preset FROM tags ORDER BY is_preset DESC, name").fetchall()
        commissions = connection.execute(
            "SELECT * FROM commissions WHERE platform=? AND creator_key=? ORDER BY period_start DESC",
            (PLATFORM, creator_key),
        ).fetchall()
    period_metrics = creator_period_metrics(db_path, creator_key, selected_period)
    video_aggregation = aggregate_content(db_path, "video", creator_key, grain, selected_period)
    live_aggregation = aggregate_content(db_path, "live", creator_key, grain, selected_period)
    roi_formula_config = load_rating_config(config_path)["roi_formulas"]
    period_roi = None
    if collaboration_cost := (None if cost is None else cost["collaboration_cost_vnd"]):
        if period_metrics["estimated_commission"] is not None:
            period_roi = (
                period_metrics["estimated_commission"] / collaboration_cost
                * float(roi_formula_config["creator_total"]["multiplier"])
            )
    video_items = content_items_with_roi(db_path, creator_key, "video", config_path, selected_period)
    live_items = content_items_with_roi(db_path, creator_key, "live", config_path, selected_period)

    def total_item_roi(items: list[dict[str, Any]], source_type: str) -> float | None:
        if not items or any(item["slot_fee_vnd"] in (None, 0) for item in items):
            return None
        gmv_values = [item["attributed_gmv_vnd"] for item in items if item["attributed_gmv_vnd"] is not None]
        return None if not gmv_values else (
            sum(gmv_values) / sum(item["slot_fee_vnd"] for item in items)
            * float(roi_formula_config[f"{source_type}_total"]["multiplier"])
        )
    return {
        "platform": creator["platform"],
        "creator_key": creator["creator_key"],
        "creator_username": creator["creator_username"],
        "creator_id": creator["creator_id"],
        "creator_name": creator["creator_name"],
        "content_quality": None,
        "content_quality_reference": {
            "video_completion_rate": quality["completion_rate"],
            "video_ctor": quality["ctor"],
            "video_interactions": quality["interactions"],
        },
        "quote_vnd": None if cost is None else cost["quote_vnd"],
        "collaboration_cost_vnd": None if cost is None else cost["collaboration_cost_vnd"],
        "metrics": {name: metrics.get(name) for name in CORE_METRICS},
        "all_metrics": metrics,
        "period_metrics": period_metrics,
        "period_roi": period_roi,
        "selected_period": selected_period,
        "grain": grain,
        "periods": list_business_periods(db_path),
        "products": product_breakdown(db_path, creator_key, selected_period),
        "video_aggregation": video_aggregation,
        "live_aggregation": live_aggregation,
        "video_items": video_items,
        "live_items": live_items,
        "video_period_roi": total_item_roi(video_items, "video"),
        "live_period_roi": total_item_roi(live_items, "live"),
        "followups": list_followups(db_path, creator_key),
        "note": "" if annotation is None else annotation["note"],
        "tags": [dict(row) for row in tag_rows],
        "available_tags": [dict(row) for row in available_tags],
        "commissions": [dict(row) for row in commissions],
        "rating": None if rating is None else {
            "grade": rating["grade"],
            "score": rating["score"],
            "evidence": json.loads(rating["evidence_json"]),
            "computed_at": rating["computed_at"],
        },
    }


def _parse_vnd(value: str, label: str, *, allow_zero: bool) -> int | None:
    cleaned = value.strip().replace(",", "").replace(" ", "")
    if not cleaned:
        return None
    if not cleaned.isascii() or not cleaned.isdigit():
        raise ValueError(f"{label}必须是 VND 非负整数")
    parsed = int(cleaned)
    if parsed == 0 and not allow_zero:
        raise ValueError(f"{label}必须大于 0；空值表示待补录")
    return parsed


def save_cost(
    db_path: str | Path,
    creator_key: str,
    quote_text: str,
    collaboration_cost_text: str,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """Upsert quote/cost, then refresh only this affected creator."""
    quote_vnd = _parse_vnd(quote_text, "报价", allow_zero=True)
    collaboration_cost_vnd = _parse_vnd(collaboration_cost_text, "合作成本", allow_zero=False)
    now = datetime.now(timezone.utc).isoformat()
    initialize_database(db_path)
    with connect(db_path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM creators WHERE platform=? AND creator_key=?",
            (PLATFORM, creator_key),
        ).fetchone()
        if exists is None:
            raise KeyError(f"达人不存在: {creator_key}")
        connection.execute(
            """
            INSERT INTO costs(platform, creator_key, quote_vnd, collaboration_cost_vnd, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(platform, creator_key, target_type, target_id) DO UPDATE SET
                quote_vnd=excluded.quote_vnd,
                collaboration_cost_vnd=excluded.collaboration_cost_vnd,
                updated_at=excluded.updated_at
            """,
            (PLATFORM, creator_key, quote_vnd, collaboration_cost_vnd, now),
        )
    enqueue_recompute(db_path, [creator_key], "cost", PLATFORM)
    recompute_incremental(db_path, config_path, PLATFORM)
    profile = load_creator_profile(db_path, creator_key, config_path=config_path)
    if profile is None:  # Foreign key and pre-check make this defensive only.
        raise RuntimeError(f"成本已保存但达人档案不可读取: {creator_key}")
    return profile


def _missing() -> str:
    return '<span class="missing">null <small>待补录</small></span>'


def _format_number(value: float | int | None, kind: str = "number") -> str:
    if value is None:
        return _missing()
    if kind == "vnd":
        return f"{int(value):,} ₫"
    if kind == "integer":
        return f"{int(value):,}"
    if kind == "percent":
        return f"{float(value) * 100:.2f}%"
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def _layout(title: str, body: str, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>
body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:0;background:#f5f7fa;color:#172033}}
main{{max-width:1080px;margin:0 auto;padding:28px 20px}} a{{color:#1456c0}} nav{{margin-bottom:20px}}
.card{{background:#fff;border:1px solid #dce2ea;border-radius:10px;padding:18px;margin:14px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
.field{{border-bottom:1px solid #edf0f4;padding:10px 0}} .label{{color:#647084;font-size:13px;display:block}}
.value{{font-size:18px;font-weight:650}} .missing{{color:#a33}} .missing small{{border:1px solid #d99;padding:1px 5px;border-radius:10px}}
form.filters{{display:flex;flex-wrap:wrap;gap:8px;align-items:end}} label{{display:flex;flex-direction:column;gap:4px;font-size:13px}}
input,select,button{{font:inherit;padding:8px;border:1px solid #b7c0cc;border-radius:6px}} button{{cursor:pointer;background:#1456c0;color:white}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:9px;border-bottom:1px solid #e6eaf0;text-align:left}}
.notice{{padding:10px;background:#eef6ff;border-radius:6px}} .badge{{display:inline-block;padding:2px 7px;margin:2px;border-radius:10px;background:#edf2ff;font-size:12px}} code{{word-break:break-all}}
.inline{{display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap}} textarea{{min-height:64px;min-width:280px}} small.muted{{color:#647084}}
</style></head><body><main><nav><a href="/">达人列表</a> · <a href="/dashboard">数据看板</a> · <a href="/calculator">未合作达人计算器</a> · <a href="/config">配置后台</a> · <a href="/recompute">增量重算</a></nav>{body}</main>
{script}</body></html>"""


def _decorated_name(display_name: Any, grade: Any, tags: str = "", note: str = "") -> str:
    badges = [f'<span class="badge">评级 {escape(str(grade or "—"))}</span>']
    if tags:
        badges.extend(f'<span class="badge">{escape(item)}</span>' for item in tags.split(" / ") if item)
    note_html = f' <small class="muted">备注：{escape(note)}</small>' if note else ' <small class="muted">备注：—</small>'
    return f"{escape(str(display_name))} {' '.join(badges)}{note_html}"


def _period_options(periods: list[dict[str, str]], selected: str) -> str:
    options = [f'<option value="total"{" selected" if selected == "total" else ""}>总</option>']
    for period in periods:
        if "stable_unperioded" in period["source"]:
            label = "无横幅（稳定期间键）"
        else:
            label = f"{period['start']} 至 {period['end']}"
        options.append(
            f'<option value="{escape(period["token"], quote=True)}"'
            f'{" selected" if selected == period["token"] else ""}>{escape(label)}</option>'
        )
    return "".join(options)


def _aggregation_rows(rows: list[dict[str, Any]], source_type: str) -> str:
    fields = (
        (("VV", "views"), ("点赞", "likes"), ("评论", "comments"), ("分享", "shares"), ("新增粉丝", "new_followers"))
        if source_type == "video" else
        (("累计观看人数", "viewers"), ("观看人次", "view_count"), ("评论", "comments"), ("分享", "shares"), ("点赞", "likes"))
    )
    return "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td>{}</tr>".format(
            escape(str(row["period"])), row["records"],
            _format_number(row["attributed_gmv_vnd"], "vnd"),
            _format_number(row["attributed_items"], "integer"),
            "".join(f"<td>{_format_number(row[key], 'integer')}</td>" for _, key in fields),
        ) for row in rows
    ) or f'<tr><td colspan="{4 + len(fields)}">无带日期数据</td></tr>'


def render_creator_detail(profile: dict[str, Any]) -> str:
    metrics = profile["metrics"]
    period_metrics = profile["period_metrics"]
    quality = profile["content_quality_reference"]
    rating = profile["rating"]
    display_name = profile["creator_name"] or profile["creator_username"] or profile["creator_key"]
    grade = None if rating is None else rating["grade"]
    tag_text = " / ".join(tag["name"] for tag in profile["tags"])
    decorated_name = _decorated_name(display_name, grade, tag_text, profile["note"])
    quality_reference = " / ".join((
        f"完播率 {_format_number(quality['video_completion_rate'], 'percent')}",
        f"CTOR {_format_number(quality['video_ctor'], 'percent')}",
        f"互动 {_format_number(quality['video_interactions'], 'integer')}",
    ))
    if rating is None:
        rating_value = _missing()
        evidence_html = "<p>尚无评级依据，请执行重算。</p>"
    else:
        rating_value = f"{escape(rating['grade'])}（{rating['score']:.2f} 分）"
        evidence = rating["evidence"]
        metric_items = "".join(
            "<li>{}: 原值 {}，归一分 {:.2f}，权重 {:.2f}，加权分 {:.2f}</li>".format(
                escape(item["label"]), escape(str(item["value"])), item["normalized_score"],
                item["configured_weight"], item["weighted_score"],
            ) for item in evidence["participating_metrics"]
        ) or "<li>没有可用指标，按暂定缺失策略得 0 分</li>"
        interval = evidence["matched_interval"]
        right = "]" if interval["max_inclusive"] else ")"
        evidence_html = (
            f"<p>规则状态：{escape(evidence['status'])}；公式：{escape(evidence['formula'])}</p>"
            f"<ul>{metric_items}</ul><p>命中阈值区间：{interval['grade']} "
            f"[{interval['min_score']}, {interval['max_score']}{right}</p>"
            f"<p><small>规则指纹：<code>{escape(evidence['rules_hash'])}</code></small></p>"
        )
    key_path = quote(profile["creator_key"], safe="")
    period_options = _period_options(profile["periods"], profile["selected_period"])
    grain_options = "".join(
        f'<option value="{value}"{" selected" if profile["grain"] == value else ""}>{label}</option>'
        for value, label in (("total", "总"), ("day", "日"), ("week", "周"), ("month", "月"), ("year", "年"))
    )
    product_rows = "".join(
        f"<tr><td>{escape(row['product_name'])}</td><td>{_format_number(row['vv'], 'integer')}</td>"
        f"<td>{_format_number(row['attributed_gmv_vnd'], 'vnd')}</td>"
        f"<td>{_format_number(row['attributed_items'], 'integer')}</td></tr>"
        for row in profile["products"]
    ) or '<tr><td colspan="4">视频源表当前期间无商品名称数据</td></tr>'
    video_headers = "".join(f"<th>{label}</th>" for label in ("VV", "点赞", "评论", "分享", "新增粉丝"))
    live_headers = "".join(f"<th>{label}</th>" for label in ("累计观看人数", "观看人次", "评论", "分享", "点赞"))

    def roi_rows(items: list[dict[str, Any]], source_type: str) -> str:
        return "".join(
            f"<tr><td><code>{escape(str(item['target_id']))}</code></td><td>{escape(str(item['event_at'] or '—'))}</td>"
            f"<td>{_format_number(item['attributed_gmv_vnd'], 'vnd')}</td>"
            f"<td>{_format_number(item['slot_fee_vnd'], 'vnd')}</td><td>{_format_number(item['roi'])}</td>"
            f"<td><form class='inline' method='post' action='/target-cost/{key_path}'>"
            f"<input type='hidden' name='target_type' value='{source_type}'><input type='hidden' name='target_id' value='{escape(str(item['target_id']), quote=True)}'>"
            f"<input name='slot_fee_vnd' inputmode='numeric' placeholder='坑位费' value='{'' if item['slot_fee_vnd'] is None else int(item['slot_fee_vnd'])}'><button>保存</button></form></td></tr>"
            for item in items
        ) or '<tr><td colspan="6">无记录</td></tr>'

    followup_rows = "".join(
        f"<tr><td>{escape(row['followed_at'])}</td><td>{escape(row['bd_name'])}</td>"
        f"<td>{escape(row['content'])}</td><td>{escape(row['next_step'] or '—')}</td>"
        f"<td><form method='post' action='/followup/{key_path}'><input type='hidden' name='action' value='delete'>"
        f"<input type='hidden' name='followup_id' value='{row['followup_id']}'><button>删除</button></form></td></tr>"
        for row in profile["followups"]
    ) or '<tr><td colspan="5">暂无跟进记录</td></tr>'
    commission_rows = "".join(
        f"<tr><td>{row['period_start']} 至 {row['period_end']}</td>"
        f"<td>{_format_number(row['organic_commission_vnd'], 'vnd')}</td>"
        f"<td>{_format_number(row['paid_commission_vnd'], 'vnd')}</td></tr>"
        for row in profile["commissions"]
    ) or '<tr><td colspan="3">暂无佣金补录</td></tr>'
    tag_options = "".join(
        f"<option value='{tag['tag_id']}'>{escape(tag['name'])}</option>" for tag in profile["available_tags"]
    )
    assigned_tags = "".join(
        f"<form class='inline' method='post' action='/annotation/{key_path}'><input type='hidden' name='action' value='unassign'>"
        f"<input type='hidden' name='tag_id' value='{tag['tag_id']}'><span class='badge'>{escape(tag['name'])}</span><button>移除</button></form>"
        for tag in profile["tags"]
    ) or "—"
    if profile["selected_period"] == "total":
        selected_period_label = "总"
    elif profile["selected_period"] == f"{UNPERIODIZED_DATE}|{UNPERIODIZED_DATE}":
        selected_period_label = "无横幅（稳定期间键）"
    else:
        selected_period_label = profile["selected_period"].replace("|", " 至 ")
    body = f"""
<h1>{decorated_name}</h1><p><code>{escape(profile['creator_key'])}</code></p>
<section class="card"><form class="filters" method="get">
<label>业务期间<select name="period">{period_options}</select></label>
<label>视频/直播时间粒度<select name="grain">{grain_options}</select></label><button>切换</button></form>
<p class="notice">达人表指标为期间聚合值，不支持日/周拆分；无横幅的达人表使用稳定期间键，跨日重导覆盖而不累加。视频/直播按行日期以 UTC+7 聚合。当前：{escape(selected_period_label)}。</p></section>
<section class="card"><h2>核心档案与 GMV 构成</h2><div class="grid">
<div class="field"><span class="label">内容质量</span><span class="value">{_missing()}</span><small>视频参考：{quality_reference}</small></div>
<div class="field"><span class="label">历史 GMV（达人总 GMV（联盟））</span><span class="value">{_format_number(period_metrics['historical_gmv'], 'vnd')}</span></div>
<div class="field"><span class="label">历史出单件数</span><span class="value">{_format_number(period_metrics['sold_items'], 'integer')}</span></div>
<div class="field"><span class="label">视频归因 GMV</span><span class="value">{_format_number(sum((row['attributed_gmv_vnd'] or 0) for row in profile['video_aggregation']) if profile['video_aggregation'] else None, 'vnd')}</span><small>对应件数 {_format_number(sum((row['attributed_items'] or 0) for row in profile['video_aggregation']) if profile['video_aggregation'] else None, 'integer')}</small></div>
<div class="field"><span class="label">直播归因 GMV</span><span class="value">{_format_number(sum((row['attributed_gmv_vnd'] or 0) for row in profile['live_aggregation']) if profile['live_aggregation'] else None, 'vnd')}</span><small>对应件数 {_format_number(sum((row['attributed_items'] or 0) for row in profile['live_aggregation']) if profile['live_aggregation'] else None, 'integer')}</small></div>
<div class="field"><span class="label">报价</span><span class="value">{_format_number(profile['quote_vnd'], 'vnd')}</span></div>
<div class="field"><span class="label">历史 ROI / 达人总 ROI</span><span class="value">{_format_number(profile['period_roi'])}</span></div>
<div class="field"><span class="label">合作后 GMV</span><span class="value">{_format_number(period_metrics['post_collaboration_gmv'], 'vnd')}</span></div>
<div class="field"><span class="label">费比 ROI（总）</span><span class="value">{_format_number(metrics['cost_ratio_roi'])}</span></div>
<div class="field"><span class="label">总视频 ROI</span><span class="value">{_format_number(profile['video_period_roi'])}</span></div>
<div class="field"><span class="label">总直播 ROI</span><span class="value">{_format_number(profile['live_period_roi'])}</span></div>
<div class="field"><span class="label">等级</span><span class="value">{rating_value}</span></div>
</div></section>
<section class="card"><h2>视频聚合（{escape(profile['grain'])}）</h2><p>收藏：源表未提供（数据模型已预留 favorites 字段）</p><table><thead><tr><th>时间</th><th>记录数</th><th>归因 GMV</th><th>成交件数</th>{video_headers}</tr></thead><tbody>{_aggregation_rows(profile['video_aggregation'], 'video')}</tbody></table></section>
<section class="card"><h2>直播聚合（{escape(profile['grain'])}）</h2><p>收藏：源表未提供（数据模型已预留 favorites 字段）</p><table><thead><tr><th>时间</th><th>记录数</th><th>归因 GMV</th><th>成交件数</th>{live_headers}</tr></thead><tbody>{_aggregation_rows(profile['live_aggregation'], 'live')}</tbody></table></section>
<section class="card"><h2>商品维度（来源：视频表“商品”）</h2><table><thead><tr><th>商品</th><th>VV</th><th>归因 GMV</th><th>成交件数</th></tr></thead><tbody>{product_rows}</tbody></table><p class="notice">直播源表没有商品名称列，因此无法提供直播商品维度拆分。</p></section>
<section class="card"><h2>单视频 ROI 与坑位费</h2><table><thead><tr><th>视频 ID</th><th>发布时间 UTC+7</th><th>归因 GMV</th><th>坑位费</th><th>ROI</th><th>补录</th></tr></thead><tbody>{roi_rows(profile['video_items'], 'video')}</tbody></table></section>
<section class="card"><h2>单直播 ROI 与坑位费</h2><table><thead><tr><th>直播复合键</th><th>开播时间 UTC+7</th><th>归因 GMV</th><th>坑位费</th><th>ROI</th><th>补录</th></tr></thead><tbody>{roi_rows(profile['live_items'], 'live')}</tbody></table></section>
<section class="card"><h2>规则依据</h2>{evidence_html}</section>
<section class="card"><h2>成本与报价补录</h2><form method="post" action="/cost/{key_path}">
<label>报价（VND 整数）<input name="quote_vnd" inputmode="numeric" value="{'' if profile['quote_vnd'] is None else int(profile['quote_vnd'])}"></label><br>
<label>合作成本（VND 正整数）<input name="collaboration_cost_vnd" inputmode="numeric" value="{'' if profile['collaboration_cost_vnd'] is None else int(profile['collaboration_cost_vnd'])}"></label><br><button>保存并重算</button></form></section>
<section class="card"><h2>BD 跟进</h2><table><thead><tr><th>时间</th><th>BD</th><th>内容</th><th>下一步</th><th>操作</th></tr></thead><tbody>{followup_rows}</tbody></table>
<form method="post" action="/followup/{key_path}"><input type="hidden" name="action" value="save"><label>时间<input name="followed_at" required></label><label>BD<input name="bd_name" required></label><label>内容<textarea name="content" required></textarea></label><label>下一步<textarea name="next_step"></textarea></label><button>新增跟进</button></form></section>
<section class="card"><h2>达人×期间佣金</h2><table><thead><tr><th>期间</th><th>自然流佣金</th><th>付费流佣金</th></tr></thead><tbody>{commission_rows}</tbody></table>
<form class="inline" method="post" action="/commission/{key_path}"><label>开始日期<input type="date" name="period_start" required></label><label>结束日期<input type="date" name="period_end" required></label><label>自然流佣金<input name="organic_vnd"></label><label>付费流佣金<input name="paid_vnd"></label><button>保存</button></form></section>
<section class="card"><h2>标签与自由备注</h2><p>已分配：{assigned_tags}</p>
<form class="inline" method="post" action="/annotation/{key_path}"><input type="hidden" name="action" value="assign"><select name="tag_id">{tag_options}</select><button>分配标签</button></form>
<form class="inline" method="post" action="/annotation/{key_path}"><input type="hidden" name="action" value="create_assign"><input name="tag_name" placeholder="自定义标签"><button>新建并分配</button></form>
<form method="post" action="/annotation/{key_path}"><input type="hidden" name="action" value="note"><label>自由备注<textarea name="note">{escape(profile['note'])}</textarea></label><button>保存备注</button></form></section>"""
    title_tags = tag_text or "—"
    title_note = profile["note"] or "—"
    return _layout(f"达人详情 - {display_name} | 评级 {grade or '—'} | 标签 {title_tags} | 备注 {title_note}", body)


def _list_rows(
    db_path: str | Path,
    query: dict[str, list[str]],
    limit: int | None = 500,
) -> list[dict[str, Any]]:
    clauses = ["c.platform=?"]
    selected_period = query.get("period", ["total"])[0]
    period = parse_period_token(selected_period)
    period_clauses = ["platform=?"]
    period_parameters: list[Any] = [PLATFORM]
    if period:
        period_clauses.extend(("period_start=?", "period_end=?"))
        period_parameters.extend(period)
        clauses.append("p.creator_key IS NOT NULL")
    parameters: list[Any] = [PLATFORM]
    text = query.get("q", [""])[0].strip()
    if text:
        literal = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append(
            "(COALESCE(c.creator_name,'') LIKE ? ESCAPE '\\' OR "
            "COALESCE(c.creator_username,'') LIKE ? ESCAPE '\\' OR "
            "COALESCE(c.creator_id,'') LIKE ? ESCAPE '\\' OR c.creator_key LIKE ? ESCAPE '\\')"
        )
        parameters.extend([f"%{literal}%"] * 4)
    grade = query.get("grade", [""])[0]
    if grade in {"S", "A", "B", "C", "D"}:
        clauses.append("r.grade=?")
        parameters.append(grade)
    for query_key, operator in (("gmv_min", ">="), ("gmv_max", "<=")):
        raw = query.get(query_key, [""])[0].strip()
        if raw:
            value = _parse_vnd(raw, "GMV 筛选", allow_zero=True)
            clauses.append(f"COALESCE(p.historical_gmv, -1) {operator} ?")
            parameters.append(value)
    order = {
        "gmv_desc": "COALESCE(p.historical_gmv,-1) DESC",
        "gmv_asc": "COALESCE(p.historical_gmv,-1) ASC",
        "items_desc": "COALESCE(p.sold_items,-1) DESC",
        "items_asc": "COALESCE(p.sold_items,-1) ASC",
        "grade_desc": "CASE r.grade WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END",
        "grade_asc": "CASE r.grade WHEN 'D' THEN 1 WHEN 'C' THEN 2 WHEN 'B' THEN 3 WHEN 'A' THEN 4 ELSE 5 END",
        "grade": "CASE r.grade WHEN 'S' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END",
    }.get(query.get("sort", ["gmv_desc"])[0], "COALESCE(p.historical_gmv,-1) DESC")
    limit_sql = "" if limit is None else " LIMIT ?"
    if limit is not None:
        parameters.append(limit)
    sql = f"""
        WITH p AS (
            SELECT creator_key, SUM(alliance_gmv_vnd) AS historical_gmv,
                   SUM(alliance_items) AS sold_items,
                   SUM(targeted_gmv_vnd) AS post_collaboration_gmv
            FROM raw_creator_periods WHERE {' AND '.join(period_clauses)} GROUP BY creator_key
        )
        SELECT c.creator_key, c.creator_name, c.creator_username, c.creator_id,
               r.grade, r.score, p.historical_gmv, p.sold_items,
               p.post_collaboration_gmv
        FROM creators c
        LEFT JOIN ratings r ON r.platform=c.platform AND r.creator_key=c.creator_key
        LEFT JOIN p ON p.creator_key=c.creator_key
        WHERE {' AND '.join(clauses)} ORDER BY {order}, c.creator_key{limit_sql}
    """
    with connect(db_path) as connection:
        rows = [dict(row) for row in connection.execute(sql, (*period_parameters, *parameters)).fetchall()]
    annotations = creator_annotations(db_path, [row["creator_key"] for row in rows])
    for row in rows:
        row.update(annotations.get(row["creator_key"], {"tags": "", "note": ""}))
    return rows


def render_creator_list(db_path: str | Path, query: dict[str, list[str]]) -> str:
    rows = _list_rows(db_path, query)
    table_rows = "".join(
        f"<tr><td><input form='compareForm' type='checkbox' name='ids' value='{escape(row['creator_key'], quote=True)}'></td>"
        f"<td><a href=\"/creator/{quote(row['creator_key'], safe='')}?period={quote(query.get('period', ['total'])[0], safe='')}\">"
        f"{_decorated_name(row['creator_name'] or row['creator_username'] or row['creator_key'], row['grade'], row['tags'], row['note'])}</a></td>"
        f"<td>{escape(str(row['creator_id'] or '—'))}</td><td>{escape(str(row['grade'] or '—'))}</td>"
        f"<td>{_format_number(row['historical_gmv'], 'vnd')}</td>"
        f"<td>{_format_number(row['sold_items'], 'integer')}</td></tr>"
        for row in rows
    ) or '<tr><td colspan="6">没有匹配记录</td></tr>'
    selected_grade = query.get("grade", [""])[0]
    selected_sort = query.get("sort", ["gmv_desc"])[0]
    options = '<option value="">全部</option>' + "".join(
        f'<option value="{grade}"{" selected" if grade == selected_grade else ""}>{grade}</option>'
        for grade in ("S", "A", "B", "C", "D")
    )
    sort_options = "".join(
        f'<option value="{value}"{" selected" if value == selected_sort else ""}>{label}</option>'
        for value, label in (
            ("gmv_desc", "历史 GMV 从高到低"), ("gmv_asc", "历史 GMV 从低到高"),
            ("items_desc", "历史出单件数从高到低"), ("items_asc", "历史出单件数从低到高"),
            ("grade_desc", "等级从高到低"), ("grade_asc", "等级从低到高"),
        )
    )
    q = escape(query.get("q", [""])[0], quote=True)
    message = escape(query.get("message", [""])[0])
    notice = f'<p class="notice">{message}</p>' if message else ""
    selected_period = query.get("period", ["total"])[0]
    period_options = _period_options(list_business_periods(db_path, "creator"), selected_period)
    export_query = urlencode(query, doseq=True)
    body = f"""<h1>达人列表</h1>{notice}
<section class="card"><form class="filters" method="get">
<label>名称或 ID<input name="q" value="{q}" placeholder="搜索达人"></label>
<label>等级<select name="grade">{options}</select></label>
<label>业务期间<select name="period">{period_options}</select></label>
<label>GMV 最低<input name="gmv_min" value="{escape(query.get('gmv_min', [''])[0], quote=True)}"></label>
<label>GMV 最高<input name="gmv_max" value="{escape(query.get('gmv_max', [''])[0], quote=True)}"></label>
<label>排序<select name="sort">{sort_options}</select></label>
<button type="submit">查询</button><button type="button" id="resetFilters">重置</button>
</form><p class="notice">达人表指标为期间聚合值，不支持日/周拆分；无横幅时使用稳定期间键，跨日重导覆盖而不累加。列表与 CSV 使用同一查询和排序，单次最多展示/导出 500 条；请用筛选缩小范围。</p></section>
<section class="card"><form id="compareForm" method="get" action="/compare"><input type="hidden" name="period" value="{escape(selected_period, quote=True)}"><button>对比勾选达人（至少 2 位）</button></form> <a href="/export.csv?{export_query}">导出当前展示 CSV</a>
<table><thead><tr><th>选</th><th>达人（评级+标签/备注）</th><th>ID</th><th>等级</th><th>历史 GMV</th><th>历史出单件数</th></tr></thead>
<tbody>{table_rows}</tbody></table></section>"""
    script = '<script>document.getElementById("resetFilters").addEventListener("click",()=>location.href="/");</script>'
    return _layout("达人列表", body, script)


def render_dashboard(db_path: str | Path, query: dict[str, list[str]]) -> str:
    period = query.get("period", ["total"])[0]
    grain = query.get("grain", ["month"])[0]
    if grain not in GRAINS:
        raise ValueError("时间粒度非法")
    parsed_period = parse_period_token(period)
    period_clauses = ["platform=?"]
    period_parameters: list[Any] = [PLATFORM]
    if parsed_period:
        period_clauses.extend(("period_start=?", "period_end=?"))
        period_parameters.extend(parsed_period)
    join = "JOIN" if parsed_period else "LEFT JOIN"
    with connect(db_path) as connection:
        summary = connection.execute(
            f"""WITH p AS (
                    SELECT creator_key, SUM(alliance_gmv_vnd) AS historical_gmv
                    FROM raw_creator_periods WHERE {' AND '.join(period_clauses)} GROUP BY creator_key
                )
                SELECT COUNT(c.creator_key) AS creator_count,
                       COALESCE(SUM(p.historical_gmv), 0) AS historical_gmv,
                       SUM(CASE WHEN r.grade='S' THEN 1 ELSE 0 END) AS grade_s,
                       SUM(CASE WHEN r.grade='A' THEN 1 ELSE 0 END) AS grade_a,
                       SUM(CASE WHEN r.grade='B' THEN 1 ELSE 0 END) AS grade_b,
                       SUM(CASE WHEN r.grade='C' THEN 1 ELSE 0 END) AS grade_c,
                       SUM(CASE WHEN r.grade='D' THEN 1 ELSE 0 END) AS grade_d
                FROM creators c {join} p ON p.creator_key=c.creator_key
                LEFT JOIN ratings r ON r.platform=c.platform AND r.creator_key=c.creator_key
                WHERE c.platform=?""",
            (*period_parameters, PLATFORM),
        ).fetchone()
    grades = {grade: int(summary[f"grade_{grade.lower()}"] or 0) for grade in "SABCD"}
    top_gmv = _list_rows(db_path, {"period": [period], "sort": ["gmv_desc"]}, limit=10)
    top_items = _list_rows(db_path, {"period": [period], "sort": ["items_desc"]}, limit=10)
    top_gmv_rows = "".join(
        f"<li>{_decorated_name(row['creator_name'] or row['creator_username'] or row['creator_key'], row['grade'], row['tags'], row['note'])} — {_format_number(row['historical_gmv'], 'vnd')}</li>"
        for row in top_gmv
    ) or "<li>暂无数据</li>"
    top_item_rows = "".join(
        f"<li>{_decorated_name(row['creator_name'] or row['creator_username'] or row['creator_key'], row['grade'], row['tags'], row['note'])} — {_format_number(row['sold_items'], 'integer')} 件</li>"
        for row in top_items
    ) or "<li>暂无数据</li>"
    video = aggregate_content(db_path, "video", grain=grain, selected_period=period)
    live = aggregate_content(db_path, "live", grain=grain, selected_period=period)
    video_total = aggregate_content(db_path, "video", grain="total", selected_period=period)
    live_total = aggregate_content(db_path, "live", grain="total", selected_period=period)
    video_gmv = 0 if not video_total else video_total[0]["attributed_gmv_vnd"]
    live_gmv = 0 if not live_total else live_total[0]["attributed_gmv_vnd"]
    body = f"""<h1>数据看板</h1><section class="card"><form class="filters" method="get">
<label>业务期间<select name="period">{_period_options(list_business_periods(db_path), period)}</select></label>
<label>视频/直播粒度<select name="grain">{''.join(f'<option value="{value}"{" selected" if grain == value else ""}>{label}</option>' for value,label in (("total","总"),("day","日"),("week","周"),("month","月"),("year","年")))}</select></label><button>切换</button></form>
<p class="notice">达人表指标为期间聚合值，不支持日/周拆分；视频/直播按行日期（UTC+7）聚合。</p></section>
<section class="card"><div class="grid"><div class="field"><span class="label">达人数</span><span class="value">{int(summary['creator_count'])}</span></div><div class="field"><span class="label">总 GMV（联盟口径）</span><span class="value">{_format_number(summary['historical_gmv'], 'vnd')}</span></div><div class="field"><span class="label">视频归因 GMV</span><span class="value">{_format_number(video_gmv, 'vnd')}</span></div><div class="field"><span class="label">直播归因 GMV</span><span class="value">{_format_number(live_gmv, 'vnd')}</span></div><div class="field"><span class="label">等级分布</span><span class="value">{' / '.join(f'{key}:{value}' for key,value in grades.items())}</span></div></div><div class="grid"><div><h2>TOP 10（GMV）</h2><ol>{top_gmv_rows}</ol></div><div><h2>TOP 10（出单件数）</h2><ol>{top_item_rows}</ol></div></div></section>
<section class="card"><h2>视频趋势</h2><table><thead><tr><th>时间</th><th>记录数</th><th>归因 GMV</th><th>件数</th><th>VV</th><th>点赞</th><th>评论</th><th>分享</th><th>新增粉丝</th></tr></thead><tbody>{_aggregation_rows(video, 'video')}</tbody></table></section>
<section class="card"><h2>直播趋势</h2><table><thead><tr><th>时间</th><th>记录数</th><th>归因 GMV</th><th>件数</th><th>累计观看人数</th><th>观看人次</th><th>评论</th><th>分享</th><th>点赞</th></tr></thead><tbody>{_aggregation_rows(live, 'live')}</tbody></table></section>"""
    return _layout("数据看板", body)


def render_compare(db_path: str | Path, query: dict[str, list[str]], config_path: str | Path) -> str:
    creator_keys = query.get("ids", [])
    if len(set(creator_keys)) < 2:
        raise ValueError("请至少选择 2 位达人进行对比")
    selected_period = query.get("period", ["total"])[0]
    parse_period_token(selected_period)
    profiles = [
        load_creator_profile(db_path, key, selected_period=selected_period, config_path=config_path)
        for key in dict.fromkeys(creator_keys)
    ]
    profiles = [profile for profile in profiles if profile is not None]
    if len(profiles) < 2:
        raise ValueError("可读取的对比达人不足 2 位")
    rows = "".join(
        f"<tr><td>{_decorated_name(profile['creator_name'] or profile['creator_username'] or profile['creator_key'], None if profile['rating'] is None else profile['rating']['grade'], ' / '.join(tag['name'] for tag in profile['tags']), profile['note'])}</td>"
        f"<td>{_format_number(profile['period_metrics']['historical_gmv'], 'vnd')}</td>"
        f"<td>{_format_number(profile['period_metrics']['sold_items'], 'integer')}</td>"
        f"<td>{_format_number(profile['video_period_roi'])}</td><td>{_format_number(profile['live_period_roi'])}</td></tr>"
        for profile in profiles
    )
    period_label = "总" if selected_period == "total" else selected_period.replace("|", " 至 ")
    return _layout("达人对比", f"<h1>达人对比</h1><p class='notice'>业务期间：{escape(period_label)}</p><section class='card'><table><thead><tr><th>达人（评级+标签/备注）</th><th>联盟 GMV</th><th>件数</th><th>总视频 ROI</th><th>总直播 ROI</th></tr></thead><tbody>{rows}</tbody></table></section>")


def export_creator_csv(db_path: str | Path, query: dict[str, list[str]]) -> bytes:
    rows = _list_rows(db_path, query)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("达人", "达人ID", "评级", "标签", "备注", "历史 GMV（VND）", "历史出单件数"))
    for row in rows:
        writer.writerow((
            f"{row['creator_name'] or row['creator_username'] or row['creator_key']} "
            f"[评级:{row['grade'] or '—'}] [标签:{row['tags'] or '—'}] [备注:{row['note'] or '—'}]",
            row["creator_id"] or "", row["grade"] or "", row["tags"], row["note"],
            "" if row["historical_gmv"] is None else int(row["historical_gmv"]),
            "" if row["sold_items"] is None else int(row["sold_items"]),
        ))
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def render_calculator_page(config_path: str | Path) -> str:
    formula = load_rating_config(config_path).get("calculator_formula")
    formula_text = "null（待业务确认）" if formula is None else escape(json.dumps(formula, ensure_ascii=False))
    body = f"""<h1>未合作达人计算器</h1>
<section class="card"><p class="notice">{PLACEHOLDER_MESSAGE}</p>
<p>输入契约已定义为：销量、播放量、假设坑位费、假设佣金率。当前配置 <code>calculator_formula</code> = {formula_text}，因此不产生预测值。</p>
<div class="grid"><label>销量<input disabled placeholder="非负整数"></label><label>播放量<input disabled placeholder="非负整数"></label><label>假设坑位费（VND）<input disabled placeholder="非负整数"></label><label>假设佣金率<input disabled placeholder="0..1"></label></div>
<p><small class="muted">本页不连接 TikTok、FastMoss 或任何抓取服务。需业务确认公式和授权数据源后另行实现。</small></p></section>"""
    return _layout("未合作达人计算器", body)


def render_config_page(db_path: str | Path, config_path: str | Path, message: str = "") -> str:
    config = load_rating_config(config_path)
    values = editable_values(config)
    inputs = "".join(
        f"<label>{escape(key)}<input name='{escape(key, quote=True)}' value='{escape(str(value), quote=True)}'></label>"
        for key, value in values.items()
    )
    history = "".join(
        f"<tr><td>{escape(row['changed_at'])}</td><td>{escape(row['config_key'])}</td>"
        f"<td>{escape(row['old_value'])}</td><td>{escape(row['new_value'])}</td></tr>"
        for row in config_change_log(db_path)
    ) or '<tr><td colspan="4">暂无变更</td></tr>'
    notice = f'<p class="notice">{escape(message)}</p>' if message else ""
    body = f"""<h1>配置后台</h1>{notice}<p class="notice">评级权重、五档边界与 ROI 公式为暂定业务规则。保存后写回配置文件、重算指标与评级，并逐键留痕。</p>
<section class="card"><form method="post" action="/config"><div class="grid">{inputs}</div><button>保存配置并重算</button></form></section>
<section class="card"><h2>变更留痕</h2><table><thead><tr><th>时间</th><th>键</th><th>旧值</th><th>新值</th></tr></thead><tbody>{history}</tbody></table></section>"""
    return _layout("配置后台", body)


class CreatorHandler(BaseHTTPRequestHandler):
    server_version = "DarenLibrary/0.4"

    def _send_html(self, status: int, content: str) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_bytes(self, status: int, content: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def _read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 65536:
            raise ValueError("表单内容过大")
        return parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)

    @property
    def db_path(self) -> Path:
        return self.server.db_path  # type: ignore[attr-defined]

    @property
    def config_path(self) -> Path:
        return self.server.config_path  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        try:
            if parsed.path == "/":
                ensure_ratings_current(self.db_path, self.config_path)
                self._send_html(200, render_creator_list(self.db_path, parse_qs(parsed.query)))
                return
            if parsed.path == "/dashboard":
                ensure_ratings_current(self.db_path, self.config_path)
                self._send_html(200, render_dashboard(self.db_path, parse_qs(parsed.query)))
                return
            if parsed.path == "/compare":
                ensure_ratings_current(self.db_path, self.config_path)
                self._send_html(200, render_compare(self.db_path, parse_qs(parsed.query), self.config_path))
                return
            if parsed.path == "/export.csv":
                ensure_ratings_current(self.db_path, self.config_path)
                self._send_bytes(200, export_creator_csv(self.db_path, parse_qs(parsed.query)),
                                 "text/csv; charset=utf-8", "creators.csv")
                return
            if parsed.path == "/config":
                self._send_html(200, render_config_page(
                    self.db_path, self.config_path, parse_qs(parsed.query).get("message", [""])[0]
                ))
                return
            if parsed.path == "/calculator":
                self._send_html(200, render_calculator_page(self.config_path))
                return
            if parsed.path == "/recompute":
                full = parse_qs(parsed.query).get("full", ["0"])[0] == "1"
                if full:
                    count = recompute_metrics(self.db_path, config_path=self.config_path)
                    recompute_ratings(self.db_path, self.config_path)
                    clear_recompute_queue(self.db_path)
                    message = f"已全量重算 {count} 位达人"
                else:
                    count = recompute_incremental(self.db_path, self.config_path)
                    message = f"已重算 {count} 位受影响达人（增量）"
                self._redirect("/?message=" + quote(message))
                return
            if parsed.path.startswith("/creator/"):
                ensure_ratings_current(self.db_path, self.config_path)
                creator_key = unquote(parsed.path[len("/creator/"):])
                query = parse_qs(parsed.query)
                selected_period = query.get("period", ["total"])[0]
                grain = query.get("grain", ["total"])[0]
                profile = load_creator_profile(
                    self.db_path, creator_key, selected_period, grain, self.config_path
                )
                if profile is None:
                    self._send_html(404, _layout("未找到", "<h1>达人不存在</h1>"))
                else:
                    self._send_html(200, render_creator_detail(profile))
                return
            if parsed.path.startswith("/cost/"):
                ensure_ratings_current(self.db_path, self.config_path)
                creator_key = unquote(parsed.path[len("/cost/"):])
                profile = load_creator_profile(self.db_path, creator_key, config_path=self.config_path)
                if profile is None:
                    self._send_html(404, _layout("未找到", "<h1>达人不存在</h1>"))
                else:
                    self._send_html(200, render_creator_detail(profile))
                return
            self._send_html(404, _layout("未找到", "<h1>页面不存在</h1>"))
        except (RatingConfigError, ValueError) as exc:
            self._send_html(400, _layout("配置或输入错误", f"<h1>无法处理</h1><p>{escape(str(exc))}</p>"))

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        try:
            form = self._read_form()
            if parsed.path == "/config":
                known = editable_values(load_rating_config(self.config_path))
                updates = {key: form.get(key, [str(value)])[0] for key, value in known.items()}
                changes = update_config(self.db_path, self.config_path, updates)
                self._redirect("/config?message=" + quote(f"已保存 {len(changes)} 项配置变更并重算"))
                return

            route_prefixes = ("/cost/", "/target-cost/", "/followup/", "/commission/", "/annotation/")
            prefix = next((item for item in route_prefixes if parsed.path.startswith(item)), None)
            if prefix is None:
                self._send_html(404, _layout("未找到", "<h1>页面不存在</h1>"))
                return
            creator_key = unquote(parsed.path[len(prefix):])
            if prefix == "/cost/":
                save_cost(
                    self.db_path, creator_key, form.get("quote_vnd", [""])[0],
                    form.get("collaboration_cost_vnd", [""])[0], self.config_path,
                )
                message = "成本与报价已保存并重算"
            elif prefix == "/target-cost/":
                slot_fee = _parse_vnd(form.get("slot_fee_vnd", [""])[0], "坑位费", allow_zero=False)
                save_target_cost(
                    self.db_path, creator_key, form.get("target_type", [""])[0],
                    form.get("target_id", [""])[0], slot_fee,
                )
                recompute_incremental(self.db_path, self.config_path, PLATFORM)
                message = "坑位费已保存并重算"
            elif prefix == "/followup/":
                if form.get("action", ["save"])[0] == "delete":
                    delete_followup(self.db_path, creator_key, int(form.get("followup_id", ["0"])[0]))
                    message = "跟进记录已删除"
                else:
                    raw_id = form.get("followup_id", [""])[0]
                    save_followup(
                        self.db_path, creator_key, form.get("followed_at", [""])[0],
                        form.get("bd_name", [""])[0], form.get("content", [""])[0],
                        form.get("next_step", [""])[0], int(raw_id) if raw_id else None,
                    )
                    message = "跟进记录已保存"
            elif prefix == "/commission/":
                organic = _parse_vnd(form.get("organic_vnd", [""])[0], "自然流佣金", allow_zero=True)
                paid = _parse_vnd(form.get("paid_vnd", [""])[0], "付费流佣金", allow_zero=True)
                save_commissions(
                    self.db_path, creator_key, form.get("period_start", [""])[0],
                    form.get("period_end", [""])[0], organic, paid,
                )
                message = "期间佣金已保存"
            else:
                action = form.get("action", [""])[0]
                if action == "note":
                    save_note(self.db_path, creator_key, form.get("note", [""])[0])
                elif action == "assign":
                    assign_tag(self.db_path, creator_key, int(form.get("tag_id", ["0"])[0]))
                elif action == "unassign":
                    unassign_tag(self.db_path, creator_key, int(form.get("tag_id", ["0"])[0]))
                elif action == "create_assign":
                    assign_tag(self.db_path, creator_key, create_tag(self.db_path, form.get("tag_name", [""])[0]))
                else:
                    raise ValueError("未知的标签/备注操作")
                message = "标签/备注已更新"
            self._redirect("/creator/" + quote(creator_key, safe="") + "?message=" + quote(message))
        except KeyError as exc:
            self._send_html(404, _layout("未找到", f"<h1>达人不存在</h1><p>{escape(str(exc))}</p>"))
        except (RatingConfigError, UnicodeDecodeError, ValueError) as exc:
            self._send_html(400, _layout("输入错误", f"<h1>无法保存</h1><p>{escape(str(exc))}</p>"))

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")


def create_server(
    db_path: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> HTTPServer:
    initialize_database(db_path)
    ensure_ratings_current(db_path, config_path)
    server = HTTPServer((host, port), CreatorHandler)
    server.db_path = Path(db_path)  # type: ignore[attr-defined]
    server.config_path = Path(config_path)  # type: ignore[attr-defined]
    return server


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="启动达人库本地 Web 原型")
    parser.add_argument("--db", default="daren_library.db")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    arguments = parser.parse_args()
    server = create_server(arguments.db, arguments.config, arguments.host, arguments.port)
    print(f"达人库已启动: http://{arguments.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
