# 本期平台范围说明

## 已实现

- 平台：仅 TikTok Shop 越南站（`tiktok_shop_vn`）。
- 数据来源：授权后台导出的达人/视频/直播三张 XLSX，经 `TikTokManualImportAdapter.import_data` 标准化人工导入。
- 统一接口：`DataAdapter.fetch` 与 `DataAdapter.import_data` 定义获取/导入契约；TikTok 人工导入包装现有 importer。

## 仅占位或未实现

- `ShopeeAdapter` 只保留接口，`fetch`/`import_data` 均明确抛出 `NotImplementedError`；没有 Shopee 采集、同步、映射或页面。
- TikTok API、定时同步和爬虫未连接；`TikTokManualImportAdapter.fetch` 明确不可用。
- 未合作达人计算器不连接 TikTok/FastMoss；输入契约已定义，`calculator_formula` 默认 `null`，页面显示“接口已预留、计算逻辑待定”。

## 未真连原因与开启条件

当前没有经确认的 TikTok/Shopee 开放接口账号权限、字段授权范围、频率限制、凭据保管方案及正式同步口径。为避免绕权抓取、生产凭据落库和未经授权的数据外传，本期以标准化人工导入应答任务书验收第 2 条。

未来开启真实同步前必须同时满足：业务明确立项和平台范围；取得可验证的开放接口授权；完成字段映射、分页/限流/重试、幂等与审计设计；凭据进入专用私有配置且不写数据库/日志；用脱敏沙箱数据通过安全与回归验证。不得以页面占位或适配器存在宣称已实现平台同步。
