"""Generate a synthetic demo dataset for the GitHub Pages interactive demo.

This is 100% SYNTHETIC data — no real business data is read or emitted. It is
deterministic (fixed random seed) so the published demo is reproducible.

Pipeline (mirrors real usage):
  1. write synthetic creator/video/live XLSX into demo/build/
  2. run the real importer.py x3 -> metrics.py -> rating.py against demo/build/demo.db
  3. seed collaboration costs / slot fees (so ROI metrics are non-null for a subset),
     then re-run metrics.py + rating.py so ROI is reflected
  4. seed a few tags / annotations / BD follow-ups / commissions for UI richness
  5. export demo/demo_data.json (the contract consumed by the interactive demo)

Usage:
    python demo/generate_demo.py
Outputs:
    demo/build/demo.db          (gitignored, *.db)
    demo/demo_data.json         (shipped; consumed by site/demo/)
"""
from __future__ import annotations

import json
import random
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent
BUILD_DIR = DEMO_DIR / "build"
DB_PATH = BUILD_DIR / "demo.db"
# 交互 demo 的数据契约：放在 site/demo/ 下，随 GitHub Pages 一同发布
OUT_JSON = REPO_ROOT / "site" / "demo" / "demo_data.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fixtures.generate_fixtures import write_xlsx, _row_from_mapping  # noqa: E402
from importer import HEADERS  # noqa: E402

PLATFORM = "tiktok_shop_vn"
N_CREATORS = 160
SEED = 20260917

# --- synthetic vocabulary (all fake) ---
FIRST = ["lan", "minh", "ngoc", "huynh", "pham", "tran", "le", "vu", "dang", "bui",
         "hoang", "phan", "mai", "dao", "khanh", "linh", "trang", "yen", "chi", "duong"]
SUFFIX = ["shop", "store", "official", "vn", "mart", "beauty", "fashion", "home", "daily", "xanh"]
PRODUCTS = ["Son môi 口红", "Kem chống nắng 防晒", "Phấn nền 粉底", "Sữa rửa mặt 洁面",
            "Áo thun 短袖", "Váy hè 连衣裙", "Giày sneaker 运动鞋", "Túi xách 手提包",
            "Nồi chiên 空气炸锅", "Bộ chăn ga 床品", "Dầu gội 洗发水", "Mặt nạ 面膜"]
VID_TITLES = ["Unbox 开箱", "Review 测评", "Haul 好物分享", "GRWM 化妆教程",
              "Top 5 好物", "Thử thách 挑战", "So sánh 对比", "Mẹo hay 小技巧"]
BD_NAMES = ["王 BD", "李 BD", "陈 BD", "赵 BD"]
TAG_PRESETS = ["高潜力", "待跟进", "已合作", "美妆垂类", "服饰垂类", "家居垂类"]


def _username(i: int, rng: random.Random) -> str:
    return f"{rng.choice(FIRST)}{rng.choice(SUFFIX)}{i:03d}.vn"


def _money(base: float, rng: random.Random) -> int:
    return max(0, int(base * rng.uniform(0.85, 1.15)))


def gen_creator_rows(rng: random.Random):
    headers = HEADERS["creator"]
    rows = [list(headers)]
    creators = []
    # quality percentiles, shuffled so rank != index
    percs = [i / (N_CREATORS - 1) for i in range(N_CREATORS)]
    rng.shuffle(percs)
    for i in range(N_CREATORS):
        p = percs[i]
        uname = _username(i, rng)
        # demo 统一用 username 键（避免 id/username 双建档造成的重复展示）
        has_id = False
        daren_id = str(7_000_000_000_000_000_000 + i * 137) if has_id else "--"
        alliance_gmv = _money(300_000 * (1 + p * 130), rng)
        alliance_items = max(1, int((3 + p * 300) * rng.uniform(0.8, 1.2)))
        targeted_gmv = _money(alliance_gmv * rng.uniform(0.2, 0.6), rng)
        commission = _money(alliance_gmv * rng.uniform(0.08, 0.15), rng)
        live_gmv = _money(alliance_gmv * rng.uniform(0.05, 0.3), rng)
        video_gmv = _money(alliance_gmv * rng.uniform(0.1, 0.4), rng)
        card_gmv = _money(alliance_gmv * rng.uniform(0.0, 0.2), rng)
        fans = _money(2_000 + p * 400_000, rng)
        creators.append({
            "index": i, "username": uname, "daren_id": daren_id, "perc": p,
            "alliance_gmv": alliance_gmv, "alliance_items": alliance_items,
            "targeted_gmv": targeted_gmv, "commission": commission,
            "live_gmv": live_gmv, "video_gmv": video_gmv,
        })
        rows.append(_row_from_mapping(headers, {
            "达人ID": daren_id,
            "达人用户名": uname,
            "联盟 GMV": alliance_gmv,
            "联盟直播 GMV": live_gmv,
            "联盟带货视频 GMV": video_gmv,
            "联盟商品卡 GMV": card_gmv,
            "联盟商品成交件数": alliance_items,
            "成交件数": alliance_items + rng.randint(0, 20),
            "预计佣金": commission,
            "预计固定费用": _money(commission * 0.1, rng),
            "平均订单金额": _money(alliance_gmv / max(1, alliance_items), rng),
            "联盟橱窗商品数": rng.randint(1, 60),
            "联盟订单量": max(1, alliance_items - rng.randint(0, 2)),
            "点击率": f"{rng.uniform(2, 18):.1f}%",
            "商品曝光次数": _money(10_000 + p * 900_000, rng),
            "平均联盟客户数": rng.randint(1, 500),
            "联盟直播数": rng.randint(0, 30),
            "联盟带货视频数": rng.randint(0, 60),
            "定向合作 GMV": targeted_gmv,
            "定向合作预计佣金": _money(commission * rng.uniform(0.2, 0.6), rng),
            "公开合作 GMV": _money(alliance_gmv * rng.uniform(0.0, 0.2), rng),
            "公开合作预计佣金": _money(commission * rng.uniform(0.0, 0.3), rng),
            "联盟已退款的 GMV": _money(alliance_gmv * rng.uniform(0.0, 0.03), rng),
            "已退款的联盟商品数": rng.randint(0, 5),
            "联盟粉丝数": fans,
        }))
    return rows, creators


def gen_video_rows(creators, rng: random.Random):
    headers = HEADERS["video"]
    rows = [["日期范围：2026-08-01 至 2026-08-31"], list(headers)]
    vid_counter = 0
    for c in creators:
        if rng.random() < 0.35:      # 35% creators have no video rows
            continue
        n_vid = rng.randint(1, 5)
        for _ in range(n_vid):
            vid_counter += 1
            day = rng.randint(1, 28)
            hh, mm, ss = rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)
            attr_gmv = _money(c["alliance_gmv"] * rng.uniform(0.02, 0.12) / max(1, n_vid), rng)
            # exercise BOTH real datetime formats
            if rng.random() < 0.5:
                pub = f"2026/08/{day:02d} {hh:02d}:{mm:02d}:{ss:02d}"
            else:
                pub = f"2026-08-{day:02d} {hh:02d}:{mm:02d}"
            rows.append(_row_from_mapping(headers, {
                "达人昵称": c["username"], "达人ID": c["daren_id"],
                "视频信息": f"{rng.choice(VID_TITLES)} · {rng.choice(PRODUCTS)}",
                "视频ID": f"demo-v-{vid_counter:05d}",
                "发布时间": pub,
                "达人所在国家/地区": "越南",
                "商品": rng.choice(PRODUCTS),
                "VV": _money(2_000 + c["perc"] * 300_000, rng),
                "点赞数": rng.randint(10, 5_000),
                "评论数": rng.randint(0, 400),
                "分享数": rng.randint(0, 200),
                "新增粉丝数": rng.randint(0, 300),
                "引流次数": rng.randint(0, 900),
                "商品曝光次数": _money(1_000 + c["perc"] * 200_000, rng),
                "商品点击次数": rng.randint(0, 3_000),
                "去重客户数": rng.randint(0, 500),
                "归因 SKU 订单数": rng.randint(0, 120),
                "视频 SKU 订单数": rng.randint(0, 100),
                "视频间接 SKU 订单数": rng.randint(0, 40),
                "视频归因成交件数": rng.randint(0, 60),
                "视频商品成交件数": rng.randint(0, 50),
                "视频间接成交件数": rng.randint(0, 20),
                "视频归因 GMV (₫)": attr_gmv,
                "视频 GMV (₫)": _money(attr_gmv * 1.2, rng),
                "视频间接 GMV (₫)": _money(attr_gmv * 0.2, rng),
                "GPM (₫)": rng.randint(100, 9_000),
                "点击率（视频）": f"{rng.uniform(1, 12):.1f}%",
                "引流率": f"{rng.uniform(1, 20):.1f}%",
                "视频完播率": f"{rng.uniform(20, 80):.0f}%",
                "CTOR（SKU 订单）": f"{rng.uniform(1, 9):.1f}%",
                "诊断": rng.choice(["表现优异", "表现良好", "有待提升", "--"]),
            }))
    return rows, vid_counter


def gen_live_rows(creators, rng: random.Random):
    headers = HEADERS["live"]
    rows = [["日期范围：2026-08-01 至 2026-08-31"], list(headers)]
    live_counter = 0
    for c in creators:
        if rng.random() < 0.6:       # only ~40% creators have live rows
            continue
        n_live = rng.randint(1, 3)
        for _ in range(n_live):
            live_counter += 1
            day = rng.randint(1, 28)
            hh, mm = rng.randint(0, 23), rng.randint(0, 59)
            attr_gmv = _money(c["alliance_gmv"] * rng.uniform(0.03, 0.15) / max(1, n_live), rng)
            dur_h, dur_m = rng.randint(0, 3), rng.randint(0, 59)
            # exercise the trailing-slash live format AND a plain one
            if rng.random() < 0.6:
                start = f"2026/08/{day:02d}/ {hh:02d}:{mm:02d}"
            else:
                start = f"2026-08-{day:02d} {hh:02d}:{mm:02d}:00"
            rows.append(_row_from_mapping(headers, {
                "达人ID": c["daren_id"],
                "达人信息": c["username"],
                "昵称": c["username"],
                "开播时间": start,
                "直播时长": f"{dur_h:02d}:{dur_m:02d}:00",
                "直播归因 GMV (₫)": attr_gmv,
                "直播 GMV (₫)": _money(attr_gmv * 1.15, rng),
                "直播间接 GMV (₫)": _money(attr_gmv * 0.18, rng),
                "添加商品数": rng.randint(1, 40),
                "动销商品数": rng.randint(0, 30),
                "已创建的订单数": rng.randint(0, 200),
                "支付订单数": rng.randint(0, 180),
                "直播归因成交件数": rng.randint(0, 90),
                "直播商品成交件数": rng.randint(0, 80),
                "直播间接成交件数": rng.randint(0, 30),
                "去重客户数": rng.randint(0, 400),
                "件单价 (₫)": rng.randint(20_000, 900_000),
                "点击成交转化率": f"{rng.uniform(0.5, 8):.1f}%",
                "累计观看人数": _money(500 + c["perc"] * 60_000, rng),
                "观看人次": _money(800 + c["perc"] * 90_000, rng),
                "人均观看时长（直播）": f"{rng.randint(1, 12)}:{rng.randint(0,59):02d}",
                "评论次数": rng.randint(0, 900),
                "分享次数": rng.randint(0, 300),
                "直播点赞数": rng.randint(0, 20_000),
                "新粉丝数（达人视频）": rng.randint(0, 600),
                "商品曝光次数": _money(1_000 + c["perc"] * 150_000, rng),
                "商品点击次数": rng.randint(0, 4_000),
                "曝光点击率": f"{rng.uniform(1, 15):.1f}%",
            }))
    return rows, live_counter


def run_cli(args, expect=(0, 2)):
    proc = subprocess.run([sys.executable, *args], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode not in expect:
        raise RuntimeError(f"CLI failed {args}: exit={proc.returncode}\n{proc.stderr[-800:]}")
    return proc


def seed_costs_and_extras(db_path: Path, creators, rng: random.Random):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    # resolve creator_key for each synthetic creator (id-prefixed key wins when 达人ID present)
    def key_for(c):
        cur.execute("SELECT creator_key FROM creators WHERE platform=? AND creator_key IN (?,?)",
                    (PLATFORM, f"id:{c['daren_id']}", f"username:{c['username']}"))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT creator_key FROM creators WHERE platform=? AND creator_key LIKE ?",
                    (PLATFORM, f"%{c['username']}%"))
        row = cur.fetchone()
        return row[0] if row else None

    keyed = []
    for c in creators:
        k = key_for(c)
        if k:
            keyed.append((k, c))

    # collaboration cost for ~55% of creators -> historical_roi / cost_ratio_roi non-null
    for k, c in keyed:
        if rng.random() < 0.55:
            target_roi = rng.uniform(0.8, 4.0)
            cost = max(1, int(c["commission"] / target_roi))
            cur.execute(
                "INSERT INTO costs(platform,creator_key,target_type,target_id,quote_vnd,"
                "collaboration_cost_vnd,slot_fee_vnd,updated_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(platform,creator_key,target_type,target_id) DO UPDATE SET "
                "collaboration_cost_vnd=excluded.collaboration_cost_vnd,updated_at=excluded.updated_at",
                (PLATFORM, k, "creator", "", _money(cost * 1.2, rng), cost, None, now),
            )
    # slot fees for some videos/lives -> video_total_roi / live_total_roi non-null
    cur.execute("SELECT creator_key, video_id FROM raw_video")
    for ck, vid in cur.fetchall():
        if rng.random() < 0.4 and vid:
            fee = rng.randint(200_000, 5_000_000)
            cur.execute(
                "INSERT INTO costs(platform,creator_key,target_type,target_id,quote_vnd,"
                "collaboration_cost_vnd,slot_fee_vnd,updated_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(platform,creator_key,target_type,target_id) DO UPDATE SET "
                "slot_fee_vnd=excluded.slot_fee_vnd,updated_at=excluded.updated_at",
                (PLATFORM, ck, "video", str(vid), None, None, fee, now),
            )
    cur.execute("SELECT creator_key, source_record_key FROM raw_live")
    for ck, lk in cur.fetchall():
        if rng.random() < 0.4 and lk:
            fee = rng.randint(300_000, 6_000_000)
            cur.execute(
                "INSERT INTO costs(platform,creator_key,target_type,target_id,quote_vnd,"
                "collaboration_cost_vnd,slot_fee_vnd,updated_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(platform,creator_key,target_type,target_id) DO UPDATE SET "
                "slot_fee_vnd=excluded.slot_fee_vnd,updated_at=excluded.updated_at",
                (PLATFORM, ck, "live", str(lk), None, None, fee, now),
            )
    # preset tags
    tag_ids = {}
    for name in TAG_PRESETS:
        cur.execute("INSERT INTO tags(name,is_preset,created_at) VALUES (?,1,?) "
                    "ON CONFLICT(name) DO NOTHING", (name, now))
        cur.execute("SELECT tag_id FROM tags WHERE name=?", (name,))
        tag_ids[name] = cur.fetchone()[0]
    # assign tags / annotations / followups / commissions to a subset
    for idx, (k, c) in enumerate(keyed):
        if rng.random() < 0.4:
            cur.execute("INSERT INTO creator_tags(platform,creator_key,tag_id,created_at) "
                        "VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                        (PLATFORM, k, tag_ids[rng.choice(TAG_PRESETS)], now))
        if rng.random() < 0.3:
            note = rng.choice(["复投优先级高，美妆垂类头部", "报价偏高，需谈坑位费",
                               "已合作 3 次，ROI 稳定", "新达人，待小样测试", "直播转化好，可排大促"])
            cur.execute("INSERT INTO creator_annotations(platform,creator_key,note,updated_at) "
                        "VALUES (?,?,?,?) ON CONFLICT(platform,creator_key) DO UPDATE SET "
                        "note=excluded.note,updated_at=excluded.updated_at", (PLATFORM, k, note, now))
        if rng.random() < 0.3:
            cur.execute("INSERT INTO bd_followups(platform,creator_key,followed_at,bd_name,"
                        "content,next_step,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                        (PLATFORM, k, f"2026-08-{rng.randint(1,28):02d}", rng.choice(BD_NAMES),
                         rng.choice(["已寄样，等待反馈", "已确认大促排期", "报价谈判中", "首播数据复盘"]),
                         rng.choice(["一周后跟进", "安排下次直播", "等待达人回复", None]), now, now))
        if rng.random() < 0.5:
            organic = _money(c["commission"] * rng.uniform(0.3, 0.7), rng)
            paid = _money(c["commission"] * rng.uniform(0.1, 0.5), rng)
            cur.execute("INSERT INTO commissions(platform,creator_key,period_start,period_end,"
                        "organic_commission_vnd,paid_commission_vnd,updated_at) VALUES (?,?,?,?,?,?,?) "
                        "ON CONFLICT(platform,creator_key,period_start,period_end) DO UPDATE SET "
                        "organic_commission_vnd=excluded.organic_commission_vnd,"
                        "paid_commission_vnd=excluded.paid_commission_vnd,updated_at=excluded.updated_at",
                        (PLATFORM, k, "2026-08-01", "2026-08-31", organic, paid, now))
    conn.commit()
    conn.close()
    return [k for k, _ in keyed]


def export_json(db_path: Path, out_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    config = json.loads((REPO_ROOT / "config" / "rating_rules.json").read_text(encoding="utf-8"))

    def q(sql, params=()):
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    creators = q("SELECT creator_key, platform, creator_name, creator_username, creator_id "
                 "FROM creators WHERE platform=? ORDER BY creator_key", (PLATFORM,))
    # metrics per creator
    metrics_rows = q("SELECT creator_key, metric_name, metric_value, source_table, source_field, "
                     "source_batches FROM metrics WHERE platform=?", (PLATFORM,))
    metrics_by_creator = {}
    for m in metrics_rows:
        metrics_by_creator.setdefault(m["creator_key"], {})[m["metric_name"]] = {
            "value": m["metric_value"], "source_table": m["source_table"],
            "source_field": m["source_field"], "source_batches": m["source_batches"],
        }
    ratings = {r["creator_key"]: r for r in q(
        "SELECT creator_key, grade, score, evidence_json, computed_at FROM ratings WHERE platform=?",
        (PLATFORM,))}
    costs = {}
    for c in q("SELECT creator_key, target_type, target_id, quote_vnd, collaboration_cost_vnd, "
               "slot_fee_vnd FROM costs WHERE platform=?", (PLATFORM,)):
        costs.setdefault(c["creator_key"], []).append(c)
    tags_map = {}
    for t in q("SELECT ct.creator_key, t.name FROM creator_tags ct JOIN tags t ON t.tag_id=ct.tag_id "
               "WHERE ct.platform=?", (PLATFORM,)):
        tags_map.setdefault(t["creator_key"], []).append(t["name"])
    annotations = {a["creator_key"]: a["note"] for a in q(
        "SELECT creator_key, note FROM creator_annotations WHERE platform=?", (PLATFORM,))}
    followups_map = {}
    for f in q("SELECT creator_key, followed_at, bd_name, content, next_step FROM bd_followups "
               "WHERE platform=? ORDER BY followed_at DESC", (PLATFORM,)):
        followups_map.setdefault(f["creator_key"], []).append(f)
    commissions_map = {}
    for cm in q("SELECT creator_key, period_start, period_end, organic_commission_vnd, "
                "paid_commission_vnd FROM commissions WHERE platform=?", (PLATFORM,)):
        commissions_map.setdefault(cm["creator_key"], []).append(cm)
    videos_map = {}
    for v in q("SELECT creator_key, video_id, product_name, published_at, attributed_gmv_vnd, "
               "views, likes, comments, shares, attributed_items, "
               "json_extract(raw_json,'$.\"视频信息\"') AS title FROM raw_video WHERE platform=? "
               "ORDER BY attributed_gmv_vnd DESC", (PLATFORM,)):
        videos_map.setdefault(v["creator_key"], []).append(v)
    lives_map = {}
    for l in q("SELECT creator_key, source_record_key, started_at, attributed_gmv_vnd, "
               "viewers, view_count, likes, attributed_items, "
               "json_extract(raw_json,'$.\"直播时长\"') AS duration FROM raw_live WHERE platform=? "
               "ORDER BY attributed_gmv_vnd DESC", (PLATFORM,)):
        lives_map.setdefault(l["creator_key"], []).append(l)

    out_creators = []
    for c in creators:
        k = c["creator_key"]
        r = ratings.get(k, {})
        evidence = None
        if r.get("evidence_json"):
            try:
                evidence = json.loads(r["evidence_json"])
            except json.JSONDecodeError:
                evidence = None
        out_creators.append({
            "creator_key": k,
            "platform": c["platform"],
            "display_name": c.get("creator_name") or c.get("creator_username") or k,
            "username": c.get("creator_username"),
            "creator_id": c.get("creator_id"),
            "grade": r.get("grade"),
            "score": r.get("score"),
            "rating_computed_at": r.get("computed_at"),
            "rating_evidence": evidence,
            "metrics": metrics_by_creator.get(k, {}),
            "costs": costs.get(k, []),
            "tags": tags_map.get(k, []),
            "annotation": annotations.get(k),
            "followups": followups_map.get(k, []),
            "commissions": commissions_map.get(k, []),
            "videos": videos_map.get(k, [])[:12],
            "lives": lives_map.get(k, [])[:8],
            "video_count": len(videos_map.get(k, [])),
            "live_count": len(lives_map.get(k, [])),
        })

    def metric_total(name):
        cur.execute("SELECT SUM(metric_value) FROM metrics WHERE platform=? AND metric_name=?",
                    (PLATFORM, name))
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else 0

    grade_dist = {}
    cur.execute("SELECT grade, COUNT(*) c FROM ratings WHERE platform=? GROUP BY grade", (PLATFORM,))
    for row in cur.fetchall():
        grade_dist[row[0]] = row[1]

    top_gmv = q("SELECT creator_key, metric_value FROM metrics WHERE platform=? AND "
                "metric_name='historical_gmv' AND metric_value IS NOT NULL "
                "ORDER BY metric_value DESC LIMIT 10", (PLATFORM,))
    top_roi = q("SELECT creator_key, metric_value FROM metrics WHERE platform=? AND "
                "metric_name='cost_ratio_roi' AND metric_value IS NOT NULL "
                "ORDER BY metric_value DESC LIMIT 10", (PLATFORM,))
    name_by_key = {c["creator_key"]: (c.get("creator_name") or c.get("creator_username") or c["creator_key"]) for c in creators}
    grade_by_key = {c["creator_key"]: c.get("grade") for c in out_creators}

    def enrich(rows, field):
        return [{"creator_key": r["creator_key"], "name": name_by_key.get(r["creator_key"], r["creator_key"]),
                 "grade": grade_by_key.get(r["creator_key"]), field: r["metric_value"]} for r in rows]

    dashboard = {
        "creator_count": len(creators),
        "sum_historical_gmv": metric_total("historical_gmv"),
        "sum_video_attributed_gmv": metric_total("video_attributed_gmv"),
        "sum_live_attributed_gmv": metric_total("live_attributed_gmv"),
        "sum_post_collaboration_gmv": metric_total("post_collaboration_gmv"),
        "sum_sold_items": metric_total("sold_items"),
        "grade_distribution": grade_dist,
        "top_by_gmv": enrich(top_gmv, "historical_gmv"),
        "top_by_cost_ratio_roi": enrich(top_roi, "cost_ratio_roi"),
    }

    payload = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "synthetic": True,
        "note": f"100% 合成演示数据，非真实业务数据。由 demo/generate_demo.py 确定性生成（seed={SEED}）。",
        "platform": PLATFORM,
        "config": config,
        "dashboard": dashboard,
        "creators": out_creators,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    conn.close()
    return payload


def main() -> int:
    rng = random.Random(SEED)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    creator_rows, creators = gen_creator_rows(rng)
    video_rows, n_vid = gen_video_rows(creators, rng)
    live_rows, n_live = gen_live_rows(creators, rng)
    write_xlsx(BUILD_DIR / "demo_creator.xlsx", creator_rows)
    write_xlsx(BUILD_DIR / "demo_video.xlsx", video_rows)
    write_xlsx(BUILD_DIR / "demo_live.xlsx", live_rows)
    print(f"synthetic rows: creators={len(creators)} videos={n_vid} lives={n_live}")

    db = str(DB_PATH)
    run_cli(["importer.py", "creator", str(BUILD_DIR / "demo_creator.xlsx"), "--db", db])
    run_cli(["importer.py", "video", str(BUILD_DIR / "demo_video.xlsx"), "--db", db])
    run_cli(["importer.py", "live", str(BUILD_DIR / "demo_live.xlsx"), "--db", db])
    seed_costs_and_extras(DB_PATH, creators, rng)
    run_cli(["metrics.py", "--db", db])
    run_cli(["rating.py", "--db", db])

    payload = export_json(DB_PATH, OUT_JSON)
    gd = payload["dashboard"]["grade_distribution"]
    print(f"exported {OUT_JSON} ({OUT_JSON.stat().st_size/1024:.0f} KB)")
    print(f"creators={payload['dashboard']['creator_count']} grade_dist={gd}")
    print(f"sum_historical_gmv={payload['dashboard']['sum_historical_gmv']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
