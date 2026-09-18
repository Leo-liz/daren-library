"""Dependency-free XLSX importer for TikTok Shop VN creator data."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from db import (
    UNPERIODIZED_DATE,
    UNPERIODIZED_SOURCE,
    connect,
    initialize_database,
)


PLATFORM = "tiktok_shop_vn"
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
UTC7 = timezone(timedelta(hours=7))
IMPORT_BATCH_SIZE = 1_000


@dataclass(frozen=True)
class RowError:
    row_number: int
    reason: str


@dataclass(frozen=True)
class ImportResult:
    batch_id: str
    source_type: str
    total_rows: int
    accepted_rows: int
    overwritten_rows: int
    rejected_rows: int
    errors: tuple[RowError, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["errors"] = [asdict(error) for error in self.errors]
        return result


HEADERS: dict[str, tuple[str, ...]] = {
    "creator": (
        "达人用户名", "联盟 GMV", "联盟直播 GMV", "联盟带货视频 GMV", "联盟商品卡 GMV",
        "联盟商品成交件数", "成交件数", "预计佣金", "预计固定费用", "平均订单金额",
        "联盟橱窗商品数", "联盟订单量", "点击率", "商品曝光次数", "平均联盟客户数",
        "联盟直播数", "联盟带货视频数", "定向合作 GMV", "定向合作预计佣金",
        "公开合作 GMV", "公开合作预计佣金", "联盟已退款的 GMV", "已退款的联盟商品数",
        "联盟粉丝数",
    ),
    "video": (
        "达人昵称", "达人ID", "视频信息", "视频ID", "发布时间", "达人所在国家/地区", "商品",
        "VV", "点赞数", "评论数", "分享数", "新增粉丝数", "引流次数", "商品曝光次数",
        "商品点击次数", "去重客户数", "归因 SKU 订单数", "视频 SKU 订单数",
        "视频间接 SKU 订单数", "视频归因成交件数", "视频商品成交件数", "视频间接成交件数",
        "视频归因 GMV (₫)", "视频 GMV (₫)", "视频间接 GMV (₫)", "GPM (₫)",
        "点击率（视频）", "引流率", "视频完播率", "CTOR（SKU 订单）", "诊断",
    ),
    "live": (
        "达人ID", "达人信息", "昵称", "开播时间", "直播时长", "直播归因 GMV (₫)",
        "直播 GMV (₫)", "直播间接 GMV (₫)", "添加商品数", "动销商品数", "已创建的订单数",
        "支付订单数", "直播归因成交件数", "直播商品成交件数", "直播间接成交件数",
        "去重客户数", "件单价 (₫)", "点击成交转化率", "累计观看人数", "观看人次",
        "人均观看时长（直播）", "评论次数", "分享次数", "直播点赞数", "新粉丝数（达人视频）",
        "商品曝光次数", "商品点击次数", "曝光点击率",
    ),
}


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "creator_username": (
        "达人用户名", "达人账号", "达人昵称", "昵称", "Creator username", "Tên người sáng tạo",
    ),
    "creator_id": ("达人ID", "达人 ID", "Creator ID", "ID nhà sáng tạo"),
    "creator_name": ("达人名称", "达人昵称", "达人信息", "昵称", "Creator name", "Tên hiển thị"),
    "video_id": ("视频ID", "视频 ID", "Video ID"),
    "published_at": ("发布时间", "视频发布时间", "Publish time"),
    "product_name": ("商品", "商品名称", "Product"),
    "started_at": ("开播时间", "直播开始时间", "Start time"),
    "alliance_gmv_vnd": ("联盟GMV", "联盟 GMV", "Affiliate GMV"),
    "alliance_items": ("联盟商品成交件数", "联盟成交件数", "Affiliate items sold"),
    "estimated_commission_vnd": ("预计佣金", "预估佣金", "Estimated commission"),
    "targeted_gmv_vnd": ("定向合作GMV", "定向合作 GMV", "Targeted collaboration GMV"),
    "public_gmv_vnd": ("公开合作GMV", "公开合作 GMV", "Open collaboration GMV"),
    "refunded_gmv_vnd": ("联盟已退款的 GMV", "已退款GMV", "已退款 GMV", "Refunded GMV"),
    "affiliate_followers": ("联盟粉丝数", "Affiliate followers"),
    "click_rate": ("点击率", "Click rate"),
    "attributed_gmv_vnd": (
        "视频归因 GMV (₫)", "视频归因 GMV（₫）", "直播归因 GMV (₫)",
        "直播归因 GMV（₫）", "归因GMV", "归因 GMV", "Attributed GMV",
    ),
    "indirect_gmv_vnd": (
        "视频间接 GMV (₫)", "视频间接 GMV（₫）", "直播间接 GMV (₫)",
        "直播间接 GMV（₫）", "间接GMV", "间接 GMV", "Indirect GMV",
    ),
    "views": ("VV", "视频观看次数(VV)", "视频观看次数（VV）", "视频观看次数", "Video views"),
    "interactions": ("互动数", "Interactions"),
    "likes": ("点赞数", "直播点赞数", "Likes"),
    "comments": ("评论数", "评论次数", "Comments"),
    "shares": ("分享数", "分享次数", "Shares"),
    "new_followers": ("新增粉丝数", "新粉丝数（达人视频）", "New followers"),
    "attributed_items": ("视频归因成交件数", "直播归因成交件数", "Attributed items"),
    "view_count": ("观看人次", "Views"),
    "completion_rate": ("视频完播率", "完播率", "Completion rate"),
    "ctor": ("CTOR（SKU 订单）", "CTOR(SKU 订单)", "CTOR",),
    "attributed_orders": ("已创建的订单数", "归因订单数", "Attributed orders"),
    "viewers": ("累计观看人数", "观看人数", "Unique viewers"),
    "conversion_rate": ("点击成交转化率", "转化率", "Conversion rate"),
}

AMOUNT_FIELDS = {
    "alliance_gmv_vnd", "estimated_commission_vnd", "targeted_gmv_vnd", "public_gmv_vnd",
    "refunded_gmv_vnd", "attributed_gmv_vnd", "indirect_gmv_vnd",
}
INTEGER_FIELDS = {
    "alliance_items", "affiliate_followers", "views", "interactions", "attributed_orders", "viewers",
    "likes", "comments", "shares", "new_followers", "attributed_items", "view_count",
}
PERCENT_FIELDS = {"click_rate", "completion_rate", "ctor", "conversion_rate"}


def _normalize_header(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[\s\u3000]+", "", str(value)).casefold()


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == "--":
            return None
        return stripped
    return value


def _column_index(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha())
    index = 0
    for character in letters.upper():
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(node.text or "" for node in item.findall(f".//{{{SHEET_NS}}}t")) for item in root]


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook.find(f".//{{{SHEET_NS}}}sheet")
        if first_sheet is None:
            raise ValueError("工作簿中没有工作表")
        relationship_id = first_sheet.attrib[f"{{{DOC_REL_NS}}}id"]
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        for relationship in relationships.findall(f"{{{PKG_REL_NS}}}Relationship"):
            if relationship.attrib.get("Id") == relationship_id:
                target = relationship.attrib["Target"].lstrip("/")
                return target if target.startswith("xl/") else str(PurePosixPath("xl") / target)
    except KeyError:
        pass
    if "xl/worksheets/sheet1.xml" in archive.namelist():
        return "xl/worksheets/sheet1.xml"
    raise ValueError("无法定位首个工作表")


def read_xlsx_rows(path: str | Path) -> list[tuple[int, list[Any]]]:
    """Return `(Excel row number, cell values)` from the first XLSX worksheet."""
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        root = ET.fromstring(archive.read(_first_sheet_path(archive)))

    rows: list[tuple[int, list[Any]]] = []
    for row in root.findall(f".//{{{SHEET_NS}}}sheetData/{{{SHEET_NS}}}row"):
        row_number = int(row.attrib.get("r", len(rows) + 1))
        values: list[Any] = []
        for cell in row.findall(f"{{{SHEET_NS}}}c"):
            index = _column_index(cell.attrib.get("r", "A1"))
            while len(values) <= index:
                values.append(None)
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.findall(f".//{{{SHEET_NS}}}t"))
            else:
                node = cell.find(f"{{{SHEET_NS}}}v")
                raw = None if node is None else node.text
                if cell_type == "s" and raw is not None:
                    value = shared[int(raw)]
                elif cell_type == "b" and raw is not None:
                    value = raw == "1"
                else:
                    value = raw
            values[index] = value
        rows.append((row_number, values))
    return rows


def _header_lookup(headers: Iterable[Any]) -> dict[str, int]:
    return {_normalize_header(header): index for index, header in enumerate(headers) if _normalize_header(header)}


def _get(row: list[Any], lookup: dict[str, int], canonical: str) -> Any:
    for alias in FIELD_ALIASES[canonical]:
        index = lookup.get(_normalize_header(alias))
        if index is not None and index < len(row):
            return _normalize_value(row[index])
    return None


def _get_original_string(row: list[Any], lookup: dict[str, int], canonical: str) -> str | None:
    """Read a required textual key component without parsing or case normalization."""
    for alias in FIELD_ALIASES[canonical]:
        index = lookup.get(_normalize_header(alias))
        if index is not None and index < len(row):
            value = row[index]
            if _normalize_value(value) is not None:
                return str(value)
    return None


def _parse_number(value: Any, field: str) -> int | float | None:
    value = _normalize_value(value)
    if value is None:
        return None
    text = str(value).strip()
    is_percent = field in PERCENT_FIELDS
    if is_percent and text.endswith("%"):
        text = text[:-1].strip()
        divisor = 100.0
    else:
        divisor = 1.0
    cleaned = re.sub(r"(?i)VND|₫", "", text).replace(",", "").replace(" ", "")
    try:
        numeric = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"字段 {field} 数值非法: {value}") from exc
    if field in AMOUNT_FIELDS or field in INTEGER_FIELDS:
        if not numeric.is_integer():
            raise ValueError(f"字段 {field} 应为整数: {value}")
        return int(numeric)
    return numeric / divisor


def _parse_period_banner(values: list[Any]) -> tuple[str, str]:
    text = " ".join(str(value) for value in values if _normalize_value(value) is not None)
    matches = re.findall(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", text)
    if len(matches) < 2:
        raise ValueError("日期范围横幅无法解析：需要两个 YYYY-MM-DD 日期")
    parsed = [datetime(int(year), int(month), int(day), tzinfo=UTC7).date() for year, month, day in matches[:2]]
    if parsed[0] > parsed[1]:
        raise ValueError("日期范围横幅非法：开始日期晚于结束日期")
    return parsed[0].isoformat(), parsed[1].isoformat()


def _parse_business_datetime(value: Any, label: str, *, required: bool) -> str | None:
    value = _normalize_value(value)
    if value is None:
        if required:
            raise ValueError(f"主键缺失: {label}")
        return None
    text = str(value).strip()
    parsed: datetime | None = None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        serial = float(text)
        if 1 <= serial <= 2958465:
            parsed = datetime(1899, 12, 30) + timedelta(days=serial)
    if parsed is None:
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for pattern in (
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d/ %H:%M:%S",
                "%Y/%m/%d/ %H:%M",
                "%Y/%m/%d %H:%M",
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d",
                "%Y-%m-%d",
            ):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
    if parsed is None:
        raise ValueError(f"字段 {label} 日期时间非法: {value}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC7)
    else:
        parsed = parsed.astimezone(UTC7)
    return parsed.isoformat(timespec="seconds")


def _creator_identity(row: list[Any], lookup: dict[str, int]) -> tuple[str, str | None, str | None, str | None]:
    username = _get(row, lookup, "creator_username")
    creator_id = _get(row, lookup, "creator_id")
    name = _get(row, lookup, "creator_name")
    if creator_id is not None:
        key = f"id:{creator_id}"
    elif username is not None:
        key = f"username:{str(username).casefold()}"
    else:
        raise ValueError("主键缺失: 达人ID/达人用户名至少填写一个")
    return key, None if username is None else str(username), None if creator_id is None else str(creator_id), None if name is None else str(name)


def _canonical_raw(headers: list[Any], row: list[Any]) -> str:
    payload = {
        str(header): _normalize_value(row[index]) if index < len(row) else None
        for index, header in enumerate(headers)
        if _normalize_header(header)
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _upsert_creator(connection: Any, platform: str, identity: tuple[str, str | None, str | None, str | None], now: str) -> None:
    key, username, creator_id, name = identity
    connection.execute(
        """
        INSERT INTO creators(platform, creator_key, creator_username, creator_id, creator_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, creator_key) DO UPDATE SET
            creator_username=COALESCE(excluded.creator_username, creators.creator_username),
            creator_id=COALESCE(excluded.creator_id, creators.creator_id),
            creator_name=COALESCE(excluded.creator_name, creators.creator_name),
            updated_at=excluded.updated_at
        """,
        (platform, key, username, creator_id, name, now, now),
    )


def _row_values(source_type: str, row: list[Any], lookup: dict[str, int]) -> dict[str, Any]:
    common = {field: _get(row, lookup, field) for field in ("creator_username", "creator_id", "creator_name")}
    if source_type == "creator":
        fields = (
            "alliance_gmv_vnd", "alliance_items", "estimated_commission_vnd", "targeted_gmv_vnd",
            "public_gmv_vnd", "refunded_gmv_vnd", "affiliate_followers", "click_rate",
        )
    elif source_type == "video":
        fields = (
            "attributed_gmv_vnd", "indirect_gmv_vnd", "views", "interactions",
            "likes", "comments", "shares", "new_followers", "attributed_items",
            "completion_rate", "ctor",
        )
        common["video_id"] = _get(row, lookup, "video_id")
        if common["video_id"] is None:
            raise ValueError("主键缺失: 视频ID")
        common["published_at"] = _parse_business_datetime(
            _get(row, lookup, "published_at"), "发布时间", required=False
        )
        product = _get(row, lookup, "product_name")
        common["product_name"] = None if product is None else str(product)
    else:
        fields = (
            "attributed_gmv_vnd", "indirect_gmv_vnd", "attributed_orders", "attributed_items",
            "viewers", "view_count", "comments", "shares", "likes", "conversion_rate",
        )
        common["started_at"] = _get_original_string(row, lookup, "started_at")
        if common["started_at"] is None:
            raise ValueError("主键缺失: 开播时间")
        common["event_at_utc7"] = _parse_business_datetime(
            common["started_at"], "开播时间", required=True
        )
    for field in fields:
        common[field] = _parse_number(_get(row, lookup, field), field)
    return common


def import_xlsx(
    db_path: str | Path,
    xlsx_path: str | Path,
    source_type: str,
    platform: str = PLATFORM,
) -> ImportResult:
    if source_type not in HEADERS:
        raise ValueError(f"不支持的数据表类型: {source_type}")
    initialize_database(db_path)
    rows = read_xlsx_rows(xlsx_path)
    header_position = 1 if source_type in {"video", "live"} else 0
    if len(rows) <= header_position:
        raise ValueError("工作表缺少表头")
    headers = rows[header_position][1]
    lookup = _header_lookup(headers)
    data_rows = [(number, row) for number, row in rows[header_position + 1:] if any(_normalize_value(value) is not None for value in row)]
    batch_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    if source_type in {"video", "live"}:
        period_start, period_end = _parse_period_banner(rows[0][1])
        period_source = "banner"
    else:
        period_start = period_end = UNPERIODIZED_DATE
        period_source = UNPERIODIZED_SOURCE
    errors: list[RowError] = []
    accepted = 0
    overwritten = 0

    creator_upsert_sql = """
        INSERT INTO creators(platform, creator_key, creator_username, creator_id, creator_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, creator_key) DO UPDATE SET
            creator_username=COALESCE(excluded.creator_username, creators.creator_username),
            creator_id=COALESCE(excluded.creator_id, creators.creator_id),
            creator_name=COALESCE(excluded.creator_name, creators.creator_name),
            updated_at=excluded.updated_at
    """
    raw_sql = {
        "creator": """
            INSERT INTO raw_creator(
                platform, source_record_key, creator_key, creator_username, creator_id, creator_name,
                alliance_gmv_vnd, alliance_items, estimated_commission_vnd, targeted_gmv_vnd,
                public_gmv_vnd, refunded_gmv_vnd, affiliate_followers, click_rate,
                source_row_number, import_batch_id, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, source_record_key) DO UPDATE SET
                creator_key=excluded.creator_key, creator_username=excluded.creator_username,
                creator_id=excluded.creator_id, creator_name=excluded.creator_name,
                alliance_gmv_vnd=excluded.alliance_gmv_vnd, alliance_items=excluded.alliance_items,
                estimated_commission_vnd=excluded.estimated_commission_vnd,
                targeted_gmv_vnd=excluded.targeted_gmv_vnd, public_gmv_vnd=excluded.public_gmv_vnd,
                refunded_gmv_vnd=excluded.refunded_gmv_vnd,
                affiliate_followers=excluded.affiliate_followers, click_rate=excluded.click_rate,
                source_row_number=excluded.source_row_number,
                import_batch_id=excluded.import_batch_id, raw_json=excluded.raw_json
        """,
        "video": """
            INSERT INTO raw_video(
                platform, source_record_key, creator_key, creator_username, creator_id, creator_name,
                video_id, published_at, product_name, attributed_gmv_vnd, attributed_items,
                indirect_gmv_vnd, views, interactions, likes, comments, shares,
                new_followers, completion_rate, ctor, source_row_number, import_batch_id, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, source_record_key) DO UPDATE SET
                creator_key=excluded.creator_key, creator_username=excluded.creator_username,
                creator_id=excluded.creator_id, creator_name=excluded.creator_name,
                video_id=excluded.video_id, published_at=excluded.published_at,
                product_name=excluded.product_name, attributed_gmv_vnd=excluded.attributed_gmv_vnd,
                attributed_items=excluded.attributed_items,
                indirect_gmv_vnd=excluded.indirect_gmv_vnd, views=excluded.views,
                interactions=excluded.interactions, likes=excluded.likes,
                comments=excluded.comments, shares=excluded.shares,
                new_followers=excluded.new_followers, completion_rate=excluded.completion_rate,
                ctor=excluded.ctor, source_row_number=excluded.source_row_number,
                import_batch_id=excluded.import_batch_id, raw_json=excluded.raw_json
        """,
        "live": """
            INSERT INTO raw_live(
                platform, source_record_key, creator_key, creator_username, creator_id, creator_name,
                live_id, started_at, event_at_utc7, attributed_gmv_vnd, indirect_gmv_vnd,
                attributed_orders, attributed_items, viewers, view_count, comments, shares,
                likes, conversion_rate, source_row_number, import_batch_id, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, source_record_key) DO UPDATE SET
                creator_key=excluded.creator_key, creator_username=excluded.creator_username,
                creator_id=excluded.creator_id, creator_name=excluded.creator_name,
                live_id=excluded.live_id, started_at=excluded.started_at,
                event_at_utc7=excluded.event_at_utc7,
                attributed_gmv_vnd=excluded.attributed_gmv_vnd,
                indirect_gmv_vnd=excluded.indirect_gmv_vnd,
                attributed_orders=excluded.attributed_orders,
                attributed_items=excluded.attributed_items, viewers=excluded.viewers,
                view_count=excluded.view_count, comments=excluded.comments,
                shares=excluded.shares, likes=excluded.likes,
                conversion_rate=excluded.conversion_rate,
                source_row_number=excluded.source_row_number,
                import_batch_id=excluded.import_batch_id, raw_json=excluded.raw_json
        """,
    }
    creator_period_sql = """
        INSERT INTO raw_creator_periods(
            platform, creator_key, period_start, period_end, period_source,
            alliance_gmv_vnd, alliance_items, estimated_commission_vnd,
            targeted_gmv_vnd, import_batch_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, creator_key, period_start, period_end) DO UPDATE SET
            period_source=excluded.period_source,
            alliance_gmv_vnd=excluded.alliance_gmv_vnd,
            alliance_items=excluded.alliance_items,
            estimated_commission_vnd=excluded.estimated_commission_vnd,
            targeted_gmv_vnd=excluded.targeted_gmv_vnd,
            import_batch_id=excluded.import_batch_id,
            updated_at=excluded.updated_at
    """
    target_table = {"creator": "raw_creator", "video": "raw_video", "live": "raw_live"}[source_type]

    with connect(db_path) as connection:
        connection.execute(
            """INSERT INTO import_batches(
                   batch_id, source_type, source_name, platform, imported_at,
                   period_start, period_end, period_source, total_rows
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (batch_id, source_type, Path(xlsx_path).name, platform, now,
             period_start, period_end, period_source, len(data_rows)),
        )
        connection.commit()

        for offset in range(0, len(data_rows), IMPORT_BATCH_SIZE):
            prepared: list[dict[str, Any]] = []
            for row_number, row in data_rows[offset:offset + IMPORT_BATCH_SIZE]:
                try:
                    identity = _creator_identity(row, lookup)
                    values = _row_values(source_type, row, lookup)
                    creator_key, username, creator_id, creator_name = identity
                    raw_json = _canonical_raw(headers, row)
                    if source_type == "creator":
                        source_record_key = creator_key
                        raw_parameters = (
                            platform, source_record_key, creator_key, username, creator_id, creator_name,
                            values["alliance_gmv_vnd"], values["alliance_items"],
                            values["estimated_commission_vnd"], values["targeted_gmv_vnd"],
                            values["public_gmv_vnd"], values["refunded_gmv_vnd"],
                            values["affiliate_followers"], values["click_rate"], row_number, batch_id, raw_json,
                        )
                        period_parameters = (
                            platform, creator_key, period_start, period_end, period_source,
                            values["alliance_gmv_vnd"], values["alliance_items"],
                            values["estimated_commission_vnd"], values["targeted_gmv_vnd"], batch_id, now,
                        )
                    elif source_type == "video":
                        source_record_key = str(values["video_id"])
                        raw_parameters = (
                            platform, source_record_key, creator_key, username, creator_id, creator_name,
                            source_record_key, values["published_at"], values["product_name"],
                            values["attributed_gmv_vnd"], values["attributed_items"],
                            values["indirect_gmv_vnd"], values["views"], values["interactions"],
                            values["likes"], values["comments"], values["shares"], values["new_followers"],
                            values["completion_rate"], values["ctor"], row_number, batch_id, raw_json,
                        )
                        period_parameters = None
                    else:
                        source_record_key = json.dumps(
                            [creator_key, values["started_at"]], ensure_ascii=False, separators=(",", ":")
                        )
                        raw_parameters = (
                            platform, source_record_key, creator_key, username, creator_id, creator_name,
                            source_record_key, values["started_at"], values["event_at_utc7"],
                            values["attributed_gmv_vnd"], values["indirect_gmv_vnd"],
                            values["attributed_orders"], values["attributed_items"], values["viewers"],
                            values["view_count"], values["comments"], values["shares"], values["likes"],
                            values["conversion_rate"], row_number, batch_id, raw_json,
                        )
                        period_parameters = None
                    prepared.append({
                        "source_record_key": source_record_key,
                        "creator_key": creator_key,
                        "creator": (platform, creator_key, username, creator_id, creator_name, now, now),
                        "raw": raw_parameters,
                        "period": period_parameters,
                    })
                except (ValueError, TypeError) as exc:
                    errors.append(RowError(row_number=row_number, reason=str(exc)))

            source_keys = list(dict.fromkeys(item["source_record_key"] for item in prepared))
            existing_keys: set[str] = set()
            for key_offset in range(0, len(source_keys), 500):
                key_chunk = source_keys[key_offset:key_offset + 500]
                placeholders = ",".join("?" for _ in key_chunk)
                existing_keys.update(
                    row["source_record_key"] for row in connection.execute(
                        f"SELECT source_record_key FROM {target_table} "
                        f"WHERE platform=? AND source_record_key IN ({placeholders})",
                        (platform, *key_chunk),
                    ).fetchall()
                )
            seen_keys = set(existing_keys)
            for item in prepared:
                if item["source_record_key"] in seen_keys:
                    overwritten += 1
                else:
                    accepted += 1
                    seen_keys.add(item["source_record_key"])

            connection.executemany(creator_upsert_sql, (item["creator"] for item in prepared))
            connection.executemany(raw_sql[source_type], (item["raw"] for item in prepared))
            if source_type == "creator":
                connection.executemany(
                    creator_period_sql,
                    (item["period"] for item in prepared if item["period"] is not None),
                )
            batch_creator_keys = sorted({item["creator_key"] for item in prepared})
            connection.executemany(
                """INSERT INTO recompute_queue(platform, creator_key, reason, queued_at)
                   VALUES (?, ?, 'import', ?)
                   ON CONFLICT(platform, creator_key, reason) DO UPDATE SET queued_at=excluded.queued_at""",
                ((platform, key, now) for key in batch_creator_keys),
            )
            connection.execute(
                """UPDATE import_batches SET accepted_rows=?, rejected_rows=? WHERE batch_id=?""",
                (accepted, len(errors), batch_id),
            )
            connection.commit()

    # Import is a complete derivation boundary. Only creators touched by this
    # batch are queued, refreshed, and removed from the queue after success.
    from metrics import recompute_incremental

    recompute_incremental(db_path, platform=platform)

    return ImportResult(
        batch_id=batch_id,
        source_type=source_type,
        total_rows=len(data_rows),
        accepted_rows=accepted,
        overwritten_rows=overwritten,
        rejected_rows=len(errors),
        errors=tuple(errors),
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="导入 TikTok Shop 越南站 XLSX 数据")
    parser.add_argument("source_type", choices=tuple(HEADERS))
    parser.add_argument("xlsx_path")
    parser.add_argument("--db", default="daren_library.db")
    arguments = parser.parse_args()
    result = import_xlsx(arguments.db, arguments.xlsx_path, arguments.source_type)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.rejected_rows == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
