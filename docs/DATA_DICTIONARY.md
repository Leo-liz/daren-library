# 数据字段字典

本字典对应 TikTok Shop 越南站三张人工导入表。金额字段以 VND 整数保存；百分比保存为 0..1 小数；所有非空原始列同时写入各明细表的 `raw_json`，未结构化字段不参与当前指标。

## 公共与审计字段

| 原表语义 | DB 字段 | 用途 |
|---|---|---|
| 达人 ID（有则优先）/规范化用户名 | `creators.creator_key`、三张 `raw_*`.`creator_key` | 唯一达人键；`id:<ID>` 或 `username:<小写用户名>` |
| 原文件名、表类型、导入时间 | `import_batches.source_name/source_type/imported_at` | 批次审计 |
| Excel 行号、批次号、整行内容 | `raw_*.source_row_number/import_batch_id/raw_json` | 指标追溯与坏行定位 |
| 横幅日期范围 | `import_batches.period_start/period_end` | 视频/直播期间筛选；达人表无横幅时用稳定期间键（0001-01-01），重导覆盖同一期间、不跨日累加 |

## 达人表（24 列）

| 原表字段 | DB 字段 | 指标映射 |
|---|---|---|
| 达人用户名 | `creators.creator_username`、`raw_creator.creator_username` | 搜索、唯一键回退 |
| 联盟 GMV | `raw_creator.alliance_gmv_vnd`、`raw_creator_periods.alliance_gmv_vnd` | `historical_gmv`、看板总 GMV |
| 联盟直播 GMV | `raw_creator.raw_json` | 当前不单独派生；直播分段取直播表归因 GMV |
| 联盟带货视频 GMV | `raw_creator.raw_json` | 当前不单独派生；视频分段取视频表归因 GMV |
| 联盟商品卡 GMV | `raw_creator.raw_json` | 当前不派生 |
| 联盟商品成交件数 | `raw_creator.alliance_items`、`raw_creator_periods.alliance_items` | `sold_items`、件数 TOP |
| 成交件数 | `raw_creator.raw_json` | 当前不派生，避免与联盟口径混用 |
| 预计佣金 | `raw_creator.estimated_commission_vnd`、`raw_creator_periods.estimated_commission_vnd` | `historical_roi` 分子 |
| 预计固定费用 | `raw_creator.raw_json` | 当前不派生；报价/成本由人工补录 |
| 平均订单金额 | `raw_creator.raw_json` | 当前不派生 |
| 联盟橱窗商品数 | `raw_creator.raw_json` | 当前不派生 |
| 联盟订单量 | `raw_creator.raw_json` | 当前不派生 |
| 点击率 | `raw_creator.click_rate` | 档案参考 |
| 商品曝光次数 | `raw_creator.raw_json` | 当前不派生 |
| 平均联盟客户数 | `raw_creator.raw_json` | 当前不派生 |
| 联盟直播数 | `raw_creator.raw_json` | 当前不派生 |
| 联盟带货视频数 | `raw_creator.raw_json` | 当前不派生 |
| 定向合作 GMV | `raw_creator.targeted_gmv_vnd`、`raw_creator_periods.targeted_gmv_vnd` | `post_collaboration_gmv`、`cost_ratio_roi` 分子 |
| 定向合作预计佣金 | `raw_creator.raw_json` | 当前不派生 |
| 公开合作 GMV | `raw_creator.public_gmv_vnd` | 档案追溯，当前不派生 |
| 公开合作预计佣金 | `raw_creator.raw_json` | 当前不派生 |
| 联盟已退款的 GMV | `raw_creator.refunded_gmv_vnd` | 档案追溯，当前不派生 |
| 已退款的联盟商品数 | `raw_creator.raw_json` | 当前不派生 |
| 联盟粉丝数 | `raw_creator.affiliate_followers` | 档案参考 |

## 视频表（31 列）

| 原表字段 | DB 字段 | 指标映射 |
|---|---|---|
| 达人昵称、达人ID | `creators` 及 `raw_video.creator_name/creator_id` | 搜索、达人归属 |
| 视频信息 | `raw_video.raw_json` | 当前不派生 |
| 视频ID | `raw_video.video_id/source_record_key` | 视频唯一键、单视频 ROI |
| 发布时间 | `raw_video.published_at`（UTC+7） | 日/周/月/年/期间筛选 |
| 达人所在国家/地区 | `raw_video.raw_json` | 当前不派生 |
| 商品 | `raw_video.product_name` | 商品 VV/GMV/件数聚合 |
| VV | `raw_video.views` | `video_views`、趋势与商品 VV |
| 点赞数、评论数、分享数 | `raw_video.likes/comments/shares` | `video_likes/comments/shares` |
| 新增粉丝数 | `raw_video.new_followers` | `video_new_followers` |
| 引流次数、商品曝光次数、商品点击次数、去重客户数 | `raw_video.raw_json` | 当前不派生 |
| 归因 SKU 订单数、视频 SKU 订单数、视频间接 SKU 订单数 | `raw_video.raw_json` | 当前不派生 |
| 视频归因成交件数 | `raw_video.attributed_items` | `video_attributed_items`、商品件数 |
| 视频商品成交件数、视频间接成交件数 | `raw_video.raw_json` | 当前不派生 |
| 视频归因 GMV (₫) | `raw_video.attributed_gmv_vnd` | `video_attributed_gmv`、单/总视频 ROI |
| 视频 GMV (₫) | `raw_video.raw_json` | 当前不派生，避免与归因口径混用 |
| 视频间接 GMV (₫) | `raw_video.indirect_gmv_vnd` | 追溯字段，当前不派生 |
| GPM (₫)、点击率（视频）、引流率 | `raw_video.raw_json` | 当前不派生 |
| 视频完播率 | `raw_video.completion_rate` | 内容质量参考 |
| CTOR（SKU 订单） | `raw_video.ctor` | 内容质量参考 |
| 诊断 | `raw_video.raw_json` | 当前不派生 |
| 收藏（源表缺失） | `raw_video.favorites=NULL` | 页面固定显示“源表未提供” |

## 直播表（28 列）

| 原表字段 | DB 字段 | 指标映射 |
|---|---|---|
| 达人ID、达人信息、昵称 | `creators` 及 `raw_live.creator_id/creator_name/creator_username` | 搜索、达人归属 |
| 开播时间 | `raw_live.started_at/event_at_utc7` | 与达人键组成直播唯一键；日/周/月/年/期间筛选 |
| 直播时长 | `raw_live.raw_json` | 当前不派生 |
| 直播归因 GMV (₫) | `raw_live.attributed_gmv_vnd` | `live_attributed_gmv`、单/总直播 ROI |
| 直播 GMV (₫) | `raw_live.raw_json` | 当前不派生，避免与归因口径混用 |
| 直播间接 GMV (₫) | `raw_live.indirect_gmv_vnd` | 追溯字段，当前不派生 |
| 添加商品数、动销商品数 | `raw_live.raw_json` | 源表无商品名称，不能形成商品清单 |
| 已创建的订单数 | `raw_live.attributed_orders` | 结构化参考，当前不派生 |
| 支付订单数 | `raw_live.raw_json` | 当前不派生 |
| 直播归因成交件数 | `raw_live.attributed_items` | `live_attributed_items` |
| 直播商品成交件数、直播间接成交件数、去重客户数、件单价 | `raw_live.raw_json` | 当前不派生 |
| 点击成交转化率 | `raw_live.conversion_rate` | 档案参考 |
| 累计观看人数、观看人次 | `raw_live.viewers/view_count` | `live_viewers/live_view_count` |
| 人均观看时长（直播） | `raw_live.raw_json` | 当前不派生 |
| 评论次数、分享次数、直播点赞数 | `raw_live.comments/shares/likes` | `live_comments/shares/likes` |
| 新粉丝数（达人视频）、商品曝光次数、商品点击次数、曝光点击率 | `raw_live.raw_json` | 当前不派生 |
| 收藏（源表缺失） | `raw_live.favorites=NULL` | 页面固定显示“源表未提供” |

## 人工补录与派生表

| 表 | 关键字段 | 说明 |
|---|---|---|
| `costs` | 达人报价、合作成本、视频/直播坑位费 | 缺失保持 null；不以 0 代替 |
| `metrics` | 指标值、来源表、来源字段、来源批次、计算时间 | 一达人一指标 |
| `ratings` | 等级、分数、完整依据、规则哈希 | S/A/B/C/D 暂定评级 |
| `bd_followups`、`commissions` | BD 跟进、自然流/付费流佣金 | 人工补录 |
| `tags`、`creator_tags`、`creator_annotations` | 标签、达人标签关系、自由备注 | 列表/详情/对比/导出同步展示 |
| `recompute_queue` | 达人、原因、入队时间 | 仅记录待增量重算的 import/cost 影响对象 |
