# 达人库智能管理与数据分析 · Daren Library

面向跨境电商（TikTok Shop 越南站）达人运营的**轻量级本地 Web 应用**：把平台导出的达人/视频/直播三张 Excel 表导入 SQLite，自动计算可追溯的核心指标与 S–D 五级评级，提供服务端渲染的查询、筛选、看板、达人专属页与配置后台。

**零第三方依赖**——仅用 Python 3 标准库（`sqlite3` / `http.server` / `zipfile` / `xml` / `datetime`）。单文件数据库、单进程服务，适合运营本机运行。

> 在线演示与项目说明：<https://leo-liz.github.io/daren-library/>

## 功能概览

- **三表导入**：达人维度 / 视频维度 / 直播维度 Excel 导入，坏行隔离（行号 + 原因），重复导入按稳定主键覆盖并留痕批次
- **指标计算**：历史 GMV、合作后 GMV、出单件数、视频/直播归因 GMV、历史 ROI、费比 ROI、五级 ROI（总/单视频/总视频/单直播/总直播），每项指标可追溯 `source_table / source_field / source_batches`
- **S–D 评级**：外置 `config/rating_rules.json`（权重、阈值、公式全部可后台修改），全库 min-max 归一 + 加权评分，缺失指标按可用权重重归一
- **多时间维度**：日 / 周 / 月 / 年 / 总聚合（视频/直播按 UTC+7 行日期）
- **达人专属页**：BD 跟进记录、视频/直播坑位费、自然流/付费流佣金、自定义评级区间、自定义标签与备注
- **看板**：达人数、Σ联盟 GMV、视频/直播归因 GMV、S–D 分布、双 TOP 榜
- **配置后台**：`/config` 页改权重/阈值并逐键留痕；`/recompute?full=1` 全量重算
- **平台适配层**：`adapters.py` 抽象 DataAdapter，TikTok 手动导入已实现，Shopee 为占位（`NotImplementedError`）
- **未合作达人计算器**：`/calculator` 接口占位（本期不实现真实测算）

## 一键启动

```bash
python web.py --db daren_library.db --config config/rating_rules.json --host 127.0.0.1 --port 8000
```

自动初始化空库并启动本机服务，入口 <http://127.0.0.1:8000/>。

> Windows 未注册 `python` 时用 `py -3` 或显式 Python 3 路径。默认仅绑定 `127.0.0.1`——本应用无认证/CSRF，**请勿暴露到局域网或公网**。

## 导入数据

```bash
python importer.py creator <达人表.xlsx> --db daren_library.db
python importer.py video   <视频表.xlsx> --db daren_library.db
python importer.py live    <直播表.xlsx> --db daren_library.db
python metrics.py --db daren_library.db     # 全量重算指标
python rating.py  --db daren_library.db     # 重算评级
```

导入器退出码：`0` 全合格 / `2` 有坏行被隔离 / `1` 致命错误。坏行明细以 JSON 输出（行号 + 原因），UTF-8 安全（Windows GBK 管道亦可读）。

真实规模参考：64,657 / 64,875 / 6,831 行三表全量导入 + 8 万达人指标重算 + 评级，全链路约 78 秒（批量化 `executemany` + 分批事务 + 集合 SQL 聚合）。

## 试用合成样例

仓库自带合成 fixture（非真实业务数据）：

```bash
python fixtures/generate_fixtures.py        # 重新生成合成样例 xlsx
python importer.py creator fixtures/creator_good.xlsx --db demo.db
python importer.py video   fixtures/video_good.xlsx   --db demo.db
python importer.py live    fixtures/live_good.xlsx    --db demo.db
python metrics.py --db demo.db
python web.py --db demo.db --config config/rating_rules.json --port 8000
```

坏行样例：`fixtures/creator_bad_rows.xlsx`（主键缺失 / 数值非法，退出码 2）。

## 测试

```bash
python -m unittest discover -s tests -v          # 35 项单元测试
RUN_BENCHMARKS=1 python -m unittest tests.benchmark_import tests.benchmark_full_recompute
python tests/benchmark_incremental.py            # 增量重算基准（合成 8 万达人）
```

## 文档

| 文档 | 内容 |
|---|---|
| [docs/USAGE.md](docs/USAGE.md) | 使用与 HTTP 接口、路由、退出码契约 |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | 字段字典与表结构 |
| [docs/METRICS_AND_RATING.md](docs/METRICS_AND_RATING.md) | 指标口径与评级规则 |
| [docs/PLATFORM_SCOPE.md](docs/PLATFORM_SCOPE.md) | 平台范围（TikTok 实现 / Shopee 占位） |
| [docs/DEMO.md](docs/DEMO.md) | 演示案例与合成数据说明 |

## 技术栈与架构

- Python 3 标准库，无第三方依赖
- SQLite 单文件数据库（`schema.sql` 定义）
- `http.server` 服务端渲染 HTML + 原生 JS（无前端框架、无构建步骤）
- 外置 JSON 配置驱动评级规则，后台可改并留痕
- 增量重算队列（`recompute_queue`）：导入/成本补录后仅重算受影响达人；`/recompute?full=1` 全量

## 数据与隐私

仓库内 `fixtures/` 均为**合成数据**，不含任何真实经营数据。真实达人 GMV/佣金等业务数据仅在运营本机数据库内，不进入版本库。

## 许可与边界

本项目为协会赏金任务交付原型。评级权重/阈值标注"暂定"，待业务正式规则确认。Web 层无认证/CSRF，设计为单机 `127.0.0.1` 运行。
