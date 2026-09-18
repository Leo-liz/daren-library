# 达人库静态交互演示

`site/demo/` 是面向 GitHub Pages 的纯前端演示，不依赖 Python、SQLite、npm 或外部 CDN。页面只读取同目录的合成数据 `demo_data.json`。

## 文件结构

- `index.html`：单页应用入口与基础语义结构。
- `demo.css`：自包含的深色主题、响应式布局和组件样式。
- `app.js`：数据加载、会话缓存、hash 路由和四个视图的交互逻辑。
- `demo_data.json`：由仓库现有流程预生成的合成数据，本演示不会修改它。
- `screenshots/`：本地浏览器验收截图。

## 视图与路由

- `#/dashboard`：经营看板、等级分布及两个 TOP 10 榜单。
- `#/creators`：达人搜索、等级筛选、GMV 区间、排序、分页与对比选择。
- `#/creator/<creator_key>`：21 项指标及来源、评级依据、视频、直播、成本、佣金和 BD 跟进详情。
- `#/compare/<creator_key>/...`：2–3 位达人关键指标并排对比。

所有资源均使用当前目录相对路径，可在 `/daren-library/demo/` 等子路径下运行。`app.js` 会优先读取本次标签页的 `sessionStorage` 缓存；缓存不可用时仍可正常通过 `fetch('./demo_data.json')` 加载。

## 数据契约

页面要求 JSON 顶层包含 `synthetic: true`、`dashboard` 和 `creators`。达人指标从 `creators[].metrics` 读取，金额以 VND 展示；指标值为 `null` 时显示“待补录”，不转换为 0。列表和对比所用字段均来自该 JSON，不包含演示文件内硬编码的业务结果。

## 本地预览

在仓库根目录运行：

```powershell
python -m http.server 8170 --directory site
```

若系统 `python` 不在 PATH，可使用本机可用的 Python 可执行文件运行同一模块。然后访问：

```text
http://127.0.0.1:8170/demo/
```

不能直接双击 `index.html` 预览，因为浏览器通常会阻止 `file://` 页面读取同目录 JSON。

## 与真实应用的差异

这是只读静态演示：没有后端、SQLite、登录与权限校验，也不提供成本、标签、备注、佣金或 BD 跟进的新增和编辑操作。筛选、排序、分页、路由和对比均只发生在浏览器内，刷新页面后除当前标签页的数据缓存外不会持久化业务状态。

## 自验记录（2026-09-18）

在仓库根以 `python -m http.server 8170 --bind 127.0.0.1 --directory site` 启动静态服务后完成以下检查：

- `curl` 请求 `/demo/` 与 `/demo/demo_data.json` 均返回 HTTP 200；JSON 下载大小为 994,778 字节。
- 无头 Microsoft Edge 在 `http://127.0.0.1:8170/demo/` 渲染成功；资源记录为 `/demo/demo.css`、`/demo/app.js`、`/demo/demo_data.json`，确认资源和数据使用子路径内的相对地址。
- 看板显示达人数 160、历史 GMV 合计 3,123,227,833 ₫；详情页渲染 21 项指标；对比页渲染 3 位达人和 13 行对比项。
- 已验证搜索、费比 ROI 排序、GMV 区间过滤、列表行按 Enter 进入详情，以及 375px 窄屏无页面级横向溢出。
- 四个视图完成截图后，浏览器控制台为 0 errors / 0 warnings。

验收截图：

- `screenshots/dashboard.png`
- `screenshots/creators.png`
- `screenshots/creator-detail.png`
- `screenshots/compare.png`
