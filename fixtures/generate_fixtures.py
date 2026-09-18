"""Generate small synthetic XLSX fixtures using only the Python standard library."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from importer import HEADERS  # noqa: E402


def _column_name(index: int) -> str:
    name = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def _row_from_mapping(headers: tuple[str, ...], values: dict[str, object]) -> list[object]:
    return [values.get(header, "--") for header in headers]


def write_xlsx(path: Path, rows: list[list[object]]) -> None:
    shared: list[str] = []
    shared_index: dict[str, int] = {}
    sheet_rows: list[str] = []

    for row_number, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column, value in enumerate(row):
            if value is None:
                continue
            reference = f"{_column_name(column)}{row_number}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            elif (row_number + column) % 2 == 0:
                text = escape(str(value))
                cells.append(f'<c r="{reference}" t="inlineStr"><is><t>{text}</t></is></c>')
            else:
                text = str(value)
                if text not in shared_index:
                    shared_index[text] = len(shared)
                    shared.append(text)
                cells.append(f'<c r="{reference}" t="s"><v>{shared_index[text]}</v></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    shared_xml = "".join(f"<si><t>{escape(value)}</t></si>" for value in shared)
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            '</Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="合成数据" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
            '</Relationships>'
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
        ),
        "xl/sharedStrings.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'count="{len(shared)}" uniqueCount="{len(shared)}">{shared_xml}</sst>'
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content.encode("utf-8"))


def generate(output_dir: Path) -> None:
    creator_headers = HEADERS["creator"]
    creator_rows = [
        list(creator_headers),
        _row_from_mapping(creator_headers, {
            "达人用户名": "lananh.vn", "联盟 GMV": 1_000_000, "联盟直播 GMV": 400_000,
            "联盟带货视频 GMV": 500_000, "联盟商品卡 GMV": 100_000,
            "联盟商品成交件数": 25, "预计佣金": "200,000 VND", "定向合作 GMV": 750_000,
            "公开合作 GMV": "--", "联盟已退款的 GMV": 0, "联盟粉丝数": 12_000,
            "点击率": "12.5%",
        }),
        _row_from_mapping(creator_headers, {
            "达人用户名": "minhanh.vn", "联盟 GMV": "2,500,000 VND", "联盟直播 GMV": 600_000,
            "联盟带货视频 GMV": 800_000, "联盟商品卡 GMV": 1_100_000,
            "联盟商品成交件数": 40, "预计佣金": 300_000, "定向合作 GMV": 1_000_000,
            "公开合作 GMV": 1_500_000, "联盟已退款的 GMV": "--", "联盟粉丝数": 20_000,
            "点击率": "8%",
        }),
    ]
    write_xlsx(output_dir / "creator_good.xlsx", creator_rows)

    video_headers = HEADERS["video"]
    video_rows = [
        ["日期范围：2026-08-01 至 2026-08-31"],
        list(video_headers),
        _row_from_mapping(video_headers, {
            "达人昵称": "lananh.vn", "达人ID": "--", "视频信息": "Son môi mùa thu 秋季口红",
            "视频ID": "v-001", "发布时间": "2026/08/01 10:00:30", "商品": "合成口红A",
            "VV": 10_000, "点赞数": 100, "评论数": 10, "分享数": 5, "新增粉丝数": 2,
            "视频归因成交件数": 3, "视频归因 GMV (₫)": 300_000,
            "视频间接 GMV (₫)": 50_000, "视频完播率": "50%", "CTOR（SKU 订单）": "6.5%",
        }),
        _row_from_mapping(video_headers, {
            "达人昵称": "lananh.vn", "达人ID": "--", "视频信息": "Kem chống nắng 防晒",
            "视频ID": "v-002", "发布时间": "2026-08-08 11:30", "商品": "合成口红A",
            "VV": 8_000, "点赞数": 80, "评论数": 8, "分享数": 4, "新增粉丝数": 1,
            "视频归因成交件数": 2, "视频归因 GMV (₫)": "200,000 VND",
            "视频间接 GMV (₫)": "--", "视频完播率": 0.45, "CTOR（SKU 订单）": "5%",
        }),
        _row_from_mapping(video_headers, {
            "达人昵称": "minhanh.vn", "达人ID": "--", "视频信息": "Phấn nền 粉底",
            "视频ID": "v-003", "发布时间": "2026-08-10 09:15", "商品": "合成粉底B",
            "VV": 20_000, "点赞数": 200, "评论数": 20, "分享数": 10, "新增粉丝数": 4,
            "视频归因成交件数": 8, "视频归因 GMV (₫)": 800_000,
            "视频间接 GMV (₫)": 100_000, "视频完播率": "62%", "CTOR（SKU 订单）": "7%",
        }),
    ]
    write_xlsx(output_dir / "video_good.xlsx", video_rows)

    live_headers = HEADERS["live"]
    live_rows = [
        ["日期范围：2026-08-01 至 2026-08-31"],
        list(live_headers),
        _row_from_mapping(live_headers, {
            "达人ID": "--", "达人信息": "Lan Anh 蓝安", "昵称": "lananh.vn",
            "开播时间": "2026/08/15/ 20:00", "直播时长": "01:30:00",
            "直播归因 GMV (₫)": 400_000, "直播间接 GMV (₫)": 20_000,
            "已创建的订单数": 12, "直播归因成交件数": 4, "累计观看人数": 2_000,
            "观看人次": 3_000, "评论次数": 30, "分享次数": 12, "直播点赞数": 500,
            "点击成交转化率": "2.5%",
        }),
        _row_from_mapping(live_headers, {
            "达人ID": "--", "达人信息": "Lan Anh 蓝安", "昵称": "lananh.vn",
            "开播时间": "2026-08-16 19:30", "直播时长": "02:00:00",
            "直播归因 GMV (₫)": "600,000 VND", "直播间接 GMV (₫)": "--",
            "已创建的订单数": 18, "直播归因成交件数": 6, "累计观看人数": 3_500,
            "观看人次": 5_000, "评论次数": 45, "分享次数": 18, "直播点赞数": 800,
            "点击成交转化率": "3%",
        }),
    ]
    write_xlsx(output_dir / "live_good.xlsx", live_rows)

    bad_rows = [
        list(creator_headers),
        _row_from_mapping(creator_headers, {
            "达人用户名": "valid.vn", "联盟 GMV": 100_000, "联盟商品成交件数": 2,
            "预计佣金": 10_000, "定向合作 GMV": 50_000,
        }),
        _row_from_mapping(creator_headers, {
            "达人用户名": "--", "联盟 GMV": 200_000, "联盟商品成交件数": 3,
        }),
        _row_from_mapping(creator_headers, {
            "达人用户名": "bad-number.vn", "联盟 GMV": "không hợp lệ", "联盟商品成交件数": 4,
        }),
    ]
    write_xlsx(output_dir / "creator_bad_rows.xlsx", bad_rows)


def generate_benchmark(output_dir: Path, row_count: int = 5_000) -> tuple[Path, Path]:
    """Generate deterministic creator/video workbooks for local performance checks."""
    if row_count < 1:
        raise ValueError("row_count 必须大于 0")
    creator_headers = HEADERS["creator"]
    creator_rows = [list(creator_headers)]
    video_headers = HEADERS["video"]
    video_rows = [["日期范围：2026-08-01 至 2026-08-31"], list(video_headers)]
    for index in range(row_count):
        username = f"benchmark-{index:05d}.vn"
        creator_rows.append(_row_from_mapping(creator_headers, {
            "达人用户名": username,
            "联盟 GMV": 1_000_000 + index,
            "联盟商品成交件数": 10 + index % 50,
            "预计佣金": 100_000 + index,
            "定向合作 GMV": 500_000 + index,
            "公开合作 GMV": 100_000 + index,
            "联盟已退款的 GMV": index % 100,
            "联盟粉丝数": 1_000 + index,
            "点击率": f"{index % 100 / 10:.1f}%",
        }))
        day = index % 28 + 1
        hour = index % 24
        minute = index % 60
        second = index * 7 % 60
        video_rows.append(_row_from_mapping(video_headers, {
            "达人昵称": username,
            "达人ID": "--",
            "视频信息": f"synthetic-video-{index}",
            "视频ID": f"benchmark-video-{index:05d}",
            "发布时间": f"2026/08/{day:02d} {hour:02d}:{minute:02d}:{second:02d}",
            "商品": f"synthetic-product-{index % 20}",
            "VV": 1_000 + index,
            "点赞数": 100 + index % 50,
            "评论数": 10 + index % 20,
            "分享数": 5 + index % 10,
            "新增粉丝数": index % 8,
            "视频归因成交件数": 1 + index % 5,
            "视频归因 GMV (₫)": 100_000 + index,
            "视频间接 GMV (₫)": 10_000 + index,
            "视频完播率": "50%",
            "CTOR（SKU 订单）": "5%",
        }))
    creator_path = output_dir / "creator_5000.xlsx"
    video_path = output_dir / "video_5000.xlsx"
    write_xlsx(creator_path, creator_rows)
    write_xlsx(video_path, video_rows)
    return creator_path, video_path


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent)
