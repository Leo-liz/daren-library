# 合成夹具端到端演示案例

本案例只使用 `fixtures/` 中的合成数据，不对应真实达人或经营数据。

## 1. 导入并启动

```powershell
python importer.py creator fixtures/creator_good.xlsx --db demo.db
python importer.py video fixtures/video_good.xlsx --db demo.db
python importer.py live fixtures/live_good.xlsx --db demo.db
python web.py --db demo.db --config config/rating_rules.json --host 127.0.0.1 --port 8000
```

预期三表分别新增 2、3、2 条；打开 `/` 可见两位合成达人。`username:lananh.vn` 的初始口径值包括：历史 GMV 1,000,000 VND、出单 25 件、合作后 GMV 750,000 VND、视频归因 GMV 500,000 VND、直播归因 GMV 1,000,000 VND（两场直播 400,000+600,000 合计）。未补成本时 ROI 显示 null/待补录。

## 期间与重导语义

- 视频表和直播表按文件横幅中的日期范围形成期间；达人表无横幅，使用固定的“无横幅”稳定期间键。
- 可在不同日期再次执行同一条达人表导入命令：相同达人主键会覆盖当前期间行并把批次追溯更新到本次导入，历史 GMV、历史出单件数及“总”口径不会翻倍；旧批次本身仍保留作导入留痕。
- 导入和成本补录默认触发受影响达人的增量重算，手动访问 `/recompute` 也只消费待处理队列。若新导入极值或成本补录改变评级所用指标的全库 min-max 区间，或需要配置变更/恢复后的全库一致性校验，使用 `/recompute?full=1`。

## 2. 评级、补录和变化

1. 打开 `/creator/username%3Alananh.vn`，记录当前等级及规则依据。
2. 在“成本与报价补录”中填报价 150000、合作成本 100000。历史 ROI 变为 2，费比 ROI 变为 7.5，评级计算时间更新。
3. 为两条视频各补坑位费 100000；视频归因 GMV 分别为 300000、200000，因此单视频 ROI 为 3、2，总视频 ROI 为 2.5。
4. 为两场直播分别补坑位费 200000、300000；直播单场 ROI 均为 2，总直播 ROI 为 2。
5. 默认评级不使用 ROI，成本补录后字母等级可能不变。要演示字母等级变化，可在 `/config` 修改暂定权重/档位后保存，再回到详情页核对新等级与 `evidence_json` 对应依据；不要把演示规则当作正式业务规则。

## 3. 期间、对比与导出

- `/dashboard` 切换总/日/周/月/年，核对总 GMV、视频/直播分段、等级分布和两类 TOP。
- 在列表搜索 `lananh`，设置 GMV 范围与排序；勾选两位达人进入对比。
- 点击“导出当前筛选 CSV”。文件含 BOM，可由 Excel 直接打开中文/越南文；达人、评级、标签、备注、GMV、件数与当前筛选结果一致。

## 4. 重算边界

导入和成本补录会把受影响达人加入队列并立即增量重算。访问 `/recompute` 只消费仍待处理的达人；无待处理项时返回 0。只有配置整体变化、恢复校验或明确需要时使用 `/recompute?full=1`。
