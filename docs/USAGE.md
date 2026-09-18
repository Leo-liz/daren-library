# 启动与使用说明

## 环境与一键启动

仅需 Python 3 标准库。在项目目录执行：

```powershell
python web.py --db daren_library.db --config config/rating_rules.json --host 127.0.0.1 --port 8000
```

该命令会自动初始化空数据库并启动本机服务，入口为 `http://127.0.0.1:8000/`。Windows 未注册 `python` 时可用 `py -3`，或显式指定 Python 3 可执行文件。默认仅绑定 `127.0.0.1`，不要直接暴露到局域网或公网。

## 导入步骤

只导入已授权后台导出的脱敏 XLSX；三表写入同一数据库：

```powershell
python importer.py creator fixtures/creator_good.xlsx --db daren_library.db
python importer.py video fixtures/video_good.xlsx --db daren_library.db
python importer.py live fixtures/live_good.xlsx --db daren_library.db
```

每次导入返回批次号、新增/覆盖/隔离行数和坏行原因。成功行涉及的达人会自动增量计算指标与评级。退出码 `0` 表示无隔离行，`2` 表示存在隔离行（合法行仍已入库）。

## 期间与重导语义

- 视频表、直播表有日期范围横幅，按横幅中的开始/结束日期保存业务期间。
- 达人表没有日期范围横幅，使用固定的“无横幅”稳定期间键；导入日期只保留在批次时间中，不参与期间主键。
- 同一来源主键重复导入时覆盖当前记录并保留新批次号。即使跨日重导，达人表“总”口径也只取最新一次导入值，不会把历史 GMV 或历史出单件数重复累加。
- `/recompute` 默认只处理导入或成本补录队列中的受影响达人。`/recompute?full=1` 重算全库；当新数据或成本补录改变评级指标的全库 min-max 极值、配置整体变化、恢复后校验全库派生结果时，应使用全量重算。

## 路由清单

| 方法 | 路由 | 用途 |
|---|---|---|
| GET | `/` | 搜索、等级/GMV/期间筛选、排序、勾选对比 |
| GET | `/creator/<creator_key>` | 达人档案、期间/粒度分析、人工补录入口 |
| GET | `/compare?ids=...&ids=...&period=...` | 至少两位达人对比 |
| GET | `/export.csv?...` | 导出与当前列表查询、排序及 500 条上限一致的 UTF-8 BOM CSV |
| GET | `/dashboard?period=...&grain=...` | 达人数、GMV 分段、等级分布、双 TOP、趋势 |
| GET | `/calculator` | 未合作达人计算器接口占位 |
| GET/POST | `/config` | 暂定评级与 ROI 配置、变更留痕 |
| GET | `/recompute` | 只处理 import/cost 队列中的受影响达人 |
| GET | `/recompute?full=1` | 显式全量重算 |
| GET/POST | `/cost/<creator_key>` | 达人报价/合作成本补录 |
| POST | `/target-cost/<creator_key>` | 视频/直播坑位费补录 |
| POST | `/followup/<creator_key>` | BD 跟进新增/修改/删除 |
| POST | `/commission/<creator_key>` | 期间自然流/付费流佣金补录 |
| POST | `/annotation/<creator_key>` | 标签与自由备注维护 |

## 备份与重建

停服后复制 `daren_library.db` 即为一致性备份，同时备份 `config/rating_rules.json`。不要只备份其一：配置影响评级和 ROI 派生结果。

重建时先停止服务，将旧数据库移到备份位置，再按上面的三条导入命令从脱敏源文件重新导入；最后启动 Web。需要核对派生结果时访问 `/recompute?full=1`。删除或覆盖数据库属于破坏性操作，必须由操作者明确选择目标，本程序不会自动删除数据库。
