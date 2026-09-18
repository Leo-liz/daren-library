(() => {
  'use strict';

  const DATA_URL = './demo_data.json';
  const CACHE_KEY = 'daren-library-demo-data-v1';
  const GRADES = ['S', 'A', 'B', 'C', 'D'];
  const PAGE_SIZE = 25;
  const MAX_COMPARE = 3;
  const app = document.getElementById('app');
  const compareCount = document.getElementById('compare-count');
  const toast = document.getElementById('toast');
  const timestamp = document.getElementById('data-timestamp');

  const metricLabels = {
    historical_gmv: '历史 GMV',
    post_collaboration_gmv: '合作后 GMV',
    sold_items: '历史出单件数',
    historical_roi: '历史 ROI',
    cost_ratio_roi: '费比 ROI',
    video_total_roi: '视频总 ROI',
    live_total_roi: '直播总 ROI',
    video_attributed_gmv: '视频归因 GMV',
    video_attributed_items: '视频归因件数',
    video_comments: '视频评论数',
    video_likes: '视频点赞数',
    video_new_followers: '视频新增粉丝',
    video_shares: '视频分享数',
    video_views: '视频播放量',
    live_attributed_gmv: '直播归因 GMV',
    live_attributed_items: '直播归因件数',
    live_comments: '直播评论数',
    live_likes: '直播点赞数',
    live_shares: '直播分享数',
    live_view_count: '直播观看次数',
    live_viewers: '直播观众数'
  };

  const metricGroups = [
    { title: '达人经营', keys: ['historical_gmv', 'post_collaboration_gmv', 'sold_items'] },
    { title: 'ROI', keys: ['historical_roi', 'cost_ratio_roi', 'video_total_roi', 'live_total_roi'] },
    { title: '视频表现', keys: ['video_attributed_gmv', 'video_attributed_items', 'video_views', 'video_likes', 'video_comments', 'video_shares', 'video_new_followers'] },
    { title: '直播表现', keys: ['live_attributed_gmv', 'live_attributed_items', 'live_view_count', 'live_viewers', 'live_likes', 'live_comments', 'live_shares'] }
  ];

  const state = {
    data: null,
    creatorMap: new Map(),
    selected: new Set(),
    list: {
      search: '',
      grades: new Set(GRADES),
      sort: 'historical_gmv',
      minGmv: '',
      maxGmv: '',
      page: 1
    }
  };

  const numberFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 });
  const decimalFormatter = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const percentFormatter = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function safeDecode(value) {
    try { return decodeURIComponent(value); } catch (_) { return ''; }
  }

  function metricValue(creator, key) {
    const value = creator?.metrics?.[key]?.value;
    return value === null || value === undefined ? null : Number(value);
  }

  function formatNumber(value) {
    return value === null || value === undefined || !Number.isFinite(Number(value))
      ? '待补录'
      : numberFormatter.format(Number(value));
  }

  function formatMoney(value) {
    return value === null || value === undefined || !Number.isFinite(Number(value))
      ? '待补录'
      : `${numberFormatter.format(Number(value))} ₫`;
  }

  function formatRoi(value) {
    return value === null || value === undefined || !Number.isFinite(Number(value))
      ? '待补录'
      : `${decimalFormatter.format(Number(value))}×`;
  }

  function formatMetric(key, value) {
    if (key.includes('gmv')) return formatMoney(value);
    if (key.includes('roi')) return formatRoi(value);
    return formatNumber(value);
  }

  function formatDate(value, withTime = false) {
    if (!value) return '待补录';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const options = withTime
      ? { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }
      : { year: 'numeric', month: '2-digit', day: '2-digit' };
    return new Intl.DateTimeFormat('zh-CN', options).format(date);
  }

  function gradeBadge(grade) {
    const safeGrade = GRADES.includes(grade) ? grade : 'D';
    return `<span class="grade-badge grade-${safeGrade}" aria-label="${safeGrade} 级">${safeGrade}</span>`;
  }

  function tagsHtml(tags) {
    return (Array.isArray(tags) ? tags : []).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join('');
  }

  function creatorUrl(key) {
    return `#/creator/${encodeURIComponent(key)}`;
  }

  function compareUrl(keys = [...state.selected]) {
    return keys.length ? `#/compare/${keys.map(encodeURIComponent).join('/')}` : '#/compare';
  }

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add('show');
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 2400);
  }

  function updateCompareCount() {
    compareCount.textContent = String(state.selected.size);
  }

  function setActiveNav(section) {
    document.querySelectorAll('[data-nav]').forEach(link => {
      const active = link.dataset.nav === section;
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function setPageTitle(title) {
    document.title = `${title} · 达人库合成数据演示`;
  }

  function focusMain() {
    window.scrollTo({ top: 0, behavior: 'instant' });
    app.focus({ preventScroll: true });
  }

  async function loadData() {
    const loadingLabel = document.getElementById('loading-label');
    const progress = document.getElementById('loading-progress');

    try {
      const cached = sessionStorage.getItem(CACHE_KEY);
      if (cached) {
        loadingLabel.textContent = '正在使用本次会话缓存…';
        progress.style.width = '100%';
        return JSON.parse(cached);
      }
    } catch (_) {
      // 浏览器可能禁用会话存储，不影响演示运行。
    }

    const response = await fetch(DATA_URL, { cache: 'default' });
    if (!response.ok) throw new Error(`数据请求失败（HTTP ${response.status}）`);

    let raw;
    if (response.body && typeof response.body.getReader === 'function') {
      const total = Number(response.headers.get('content-length')) || 0;
      const reader = response.body.getReader();
      const chunks = [];
      let received = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        if (total) {
          const ratio = Math.min(98, Math.round(received / total * 100));
          progress.style.width = `${ratio}%`;
          loadingLabel.textContent = `正在加载本地合成数据… ${ratio}%`;
        }
      }
      const merged = new Uint8Array(received);
      let offset = 0;
      chunks.forEach(chunk => { merged.set(chunk, offset); offset += chunk.length; });
      raw = new TextDecoder('utf-8').decode(merged);
    } else {
      raw = await response.text();
    }

    progress.style.width = '100%';
    try { sessionStorage.setItem(CACHE_KEY, raw); } catch (_) { /* 容量或隐私模式限制 */ }
    return JSON.parse(raw);
  }

  function validateData(data) {
    if (!data || data.synthetic !== true || !Array.isArray(data.creators) || !data.dashboard) {
      throw new Error('数据格式不符合演示契约或不是合成数据');
    }
  }

  function renderError(error) {
    setPageTitle('加载失败');
    app.innerHTML = `
      <section class="panel error-card">
        <span class="eyebrow">数据加载失败</span>
        <h1>暂时无法打开演示</h1>
        <p>请确认通过 HTTP 服务访问此目录，且 <code>demo_data.json</code> 与本页位于同一目录。</p>
        <div class="error-detail">${escapeHtml(error?.message || error)}</div>
        <button id="retry-load" class="btn btn-primary" type="button">重新加载</button>
      </section>`;
    document.getElementById('retry-load').addEventListener('click', () => window.location.reload());
  }

  function dashboardView() {
    const dashboard = state.data.dashboard;
    const total = Number(dashboard.creator_count) || 0;
    const statItems = [
      ['达人数', formatNumber(dashboard.creator_count), '位'],
      ['Σ 历史 GMV', formatMoney(dashboard.sum_historical_gmv), 'VND'],
      ['Σ 视频归因 GMV', formatMoney(dashboard.sum_video_attributed_gmv), 'VND'],
      ['Σ 直播归因 GMV', formatMoney(dashboard.sum_live_attributed_gmv), 'VND'],
      ['Σ 出单件数', formatNumber(dashboard.sum_sold_items), '件']
    ];

    const gradeRows = GRADES.map(grade => {
      const count = Number(dashboard.grade_distribution?.[grade]) || 0;
      const ratio = total > 0 ? count / total * 100 : 0;
      return `
        <div class="grade-row grade-${grade}">
          ${gradeBadge(grade)}
          <div class="grade-track"><span class="grade-bar" style="--bar-width:${ratio.toFixed(1)}%"></span></div>
          <div class="grade-value"><strong>${count}</strong> · ${percentFormatter.format(ratio)}%</div>
        </div>`;
    }).join('');

    const rankList = (items, type) => items.map((item, index) => `
      <li class="rank-item">
        <a class="rank-link" href="${creatorUrl(item.creator_key)}">
          <span class="rank-no">${String(index + 1).padStart(2, '0')}</span>
          <span class="rank-name">${escapeHtml(item.name)}</span>
          <span class="rank-meta">${gradeBadge(item.grade)}<span class="rank-value">${type === 'gmv' ? formatMoney(item.historical_gmv) : formatRoi(item.cost_ratio_roi)}</span></span>
        </a>
      </li>`).join('');

    app.innerHTML = `
      <section class="page-head">
        <div>
          <span class="eyebrow">TikTok Shop VN · 数据全景</span>
          <h1>达人经营看板</h1>
          <p class="lede">以合成数据展示达人分层、成交贡献与投入产出表现。所有数字只用于产品交互演示。</p>
        </div>
        <div class="head-actions"><a class="btn btn-primary" href="#/creators">浏览全部达人</a></div>
      </section>
      <section class="stats-grid" aria-label="核心统计">
        ${statItems.map(([label, value, unit]) => `<article class="stat-card"><span class="label">${label}</span><span class="value">${value}<small class="unit">${unit}</small></span></article>`).join('')}
      </section>
      <section class="dashboard-grid">
        <article class="panel">
          <div class="panel-head"><h2>等级分布</h2><span class="panel-note">共 ${formatNumber(total)} 位</span></div>
          <div class="grade-chart">${gradeRows}</div>
        </article>
        <article class="panel">
          <div class="panel-head"><h2>历史 GMV · TOP 10</h2><span class="panel-note">点击查看详情</span></div>
          <ol class="rank-list">${rankList(dashboard.top_by_gmv || [], 'gmv')}</ol>
        </article>
        <article class="panel">
          <div class="panel-head"><h2>费比 ROI · TOP 10</h2><span class="panel-note">合作后 GMV / 成本</span></div>
          <ol class="rank-list">${rankList(dashboard.top_by_cost_ratio_roi || [], 'roi')}</ol>
        </article>
      </section>`;
  }

  function creatorContext(creator) {
    const annotation = creator.annotation ? `<span class="annotation">${escapeHtml(creator.annotation)}</span>` : '';
    return `${tagsHtml(creator.tags)}${annotation}`;
  }

  function creatorsView() {
    const list = state.list;
    app.innerHTML = `
      <section class="page-head">
        <div>
          <span class="eyebrow">160 位合成达人 · 可筛选</span>
          <h1>达人列表</h1>
          <p class="lede">查找、筛选和排序达人；勾选 2–3 位即可进入并排对比。</p>
        </div>
        <div class="head-actions"><a id="compare-action" class="btn" href="${compareUrl()}">对比已选达人（${state.selected.size}）</a></div>
      </section>
      <section class="panel filter-panel" aria-label="达人筛选">
        <div class="filter-grid">
          <div class="field">
            <label for="creator-search">搜索达人</label>
            <input id="creator-search" class="control" type="search" value="${escapeHtml(list.search)}" placeholder="输入达人名或 @username" autocomplete="off">
          </div>
          <div class="field">
            <span>等级</span>
            <div class="grade-filter" aria-label="等级多选">
              <button id="grade-all" class="btn btn-quiet" type="button">全部</button>
              ${GRADES.map(grade => `<label class="grade-choice grade-${grade}"><input type="checkbox" value="${grade}" ${list.grades.has(grade) ? 'checked' : ''}><span>${grade}</span></label>`).join('')}
            </div>
          </div>
          <div class="field">
            <label for="creator-sort">排序</label>
            <select id="creator-sort" class="control">
              <option value="historical_gmv">历史 GMV ↓</option>
              <option value="post_collaboration_gmv">合作后 GMV ↓</option>
              <option value="sold_items">出单件数 ↓</option>
              <option value="cost_ratio_roi">费比 ROI ↓</option>
              <option value="score">评分 ↓</option>
            </select>
          </div>
          <div class="field">
            <span>历史 GMV 区间（VND）</span>
            <div class="range-inputs">
              <input id="gmv-min" class="control" type="number" min="0" step="100000" value="${escapeHtml(list.minGmv)}" placeholder="最低">
              <i>—</i>
              <input id="gmv-max" class="control" type="number" min="0" step="100000" value="${escapeHtml(list.maxGmv)}" placeholder="最高">
            </div>
          </div>
        </div>
      </section>
      <div id="creator-results"></div>`;

    document.getElementById('creator-sort').value = list.sort;
    bindListControls();
    updateCreatorResults();
  }

  function bindListControls() {
    const search = document.getElementById('creator-search');
    search.addEventListener('input', event => {
      state.list.search = event.target.value;
      state.list.page = 1;
      updateCreatorResults();
    });
    document.getElementById('creator-sort').addEventListener('change', event => {
      state.list.sort = event.target.value;
      state.list.page = 1;
      updateCreatorResults();
    });
    ['gmv-min', 'gmv-max'].forEach(id => {
      document.getElementById(id).addEventListener('input', event => {
        state.list[id === 'gmv-min' ? 'minGmv' : 'maxGmv'] = event.target.value;
        state.list.page = 1;
        updateCreatorResults();
      });
    });
    document.querySelectorAll('.grade-choice input').forEach(input => {
      input.addEventListener('change', event => {
        if (event.target.checked) state.list.grades.add(event.target.value);
        else state.list.grades.delete(event.target.value);
        state.list.page = 1;
        updateCreatorResults();
      });
    });
    document.getElementById('grade-all').addEventListener('click', () => {
      state.list.grades = new Set(GRADES);
      document.querySelectorAll('.grade-choice input').forEach(input => { input.checked = true; });
      state.list.page = 1;
      updateCreatorResults();
    });
  }

  function filteredCreators() {
    const query = state.list.search.trim().toLocaleLowerCase('zh-CN');
    const min = state.list.minGmv === '' ? null : Number(state.list.minGmv);
    const max = state.list.maxGmv === '' ? null : Number(state.list.maxGmv);
    const rows = state.data.creators.filter(creator => {
      const identity = `${creator.display_name || ''} ${creator.username || ''}`.toLocaleLowerCase('zh-CN');
      const gmv = metricValue(creator, 'historical_gmv');
      if (query && !identity.includes(query)) return false;
      if (!state.list.grades.has(creator.grade)) return false;
      if (min !== null && Number.isFinite(min) && (gmv === null || gmv < min)) return false;
      if (max !== null && Number.isFinite(max) && (gmv === null || gmv > max)) return false;
      return true;
    });
    const key = state.list.sort;
    rows.sort((a, b) => {
      const av = key === 'score' ? Number(a.score) : metricValue(a, key);
      const bv = key === 'score' ? Number(b.score) : metricValue(b, key);
      if (av === null && bv === null) return String(a.display_name).localeCompare(String(b.display_name));
      if (av === null) return 1;
      if (bv === null) return -1;
      return bv - av || String(a.display_name).localeCompare(String(b.display_name));
    });
    return rows;
  }

  function creatorRow(creator) {
    const score = Number.isFinite(Number(creator.score)) ? Number(creator.score) : 0;
    const selected = state.selected.has(creator.creator_key);
    return `
      <tr class="creator-row grade-${escapeHtml(creator.grade)}" tabindex="0" data-key="${escapeHtml(creator.creator_key)}" aria-label="查看 ${escapeHtml(creator.display_name)} 详情">
        <td class="check-cell"><input class="compare-check" type="checkbox" data-key="${escapeHtml(creator.creator_key)}" ${selected ? 'checked' : ''} aria-label="选择 ${escapeHtml(creator.display_name)} 加入对比"></td>
        <td class="creator-cell">
          <div class="creator-name-line"><span class="creator-name">${escapeHtml(creator.display_name)}</span>${gradeBadge(creator.grade)}</div>
          <div class="creator-handle">@${escapeHtml(creator.username || '—')}</div>
          <div class="creator-context">${creatorContext(creator)}</div>
        </td>
        <td class="num">${formatMoney(metricValue(creator, 'historical_gmv'))}</td>
        <td class="num">${formatMoney(metricValue(creator, 'post_collaboration_gmv'))}</td>
        <td class="num">${formatNumber(metricValue(creator, 'sold_items'))}</td>
        <td class="num">${formatMoney(metricValue(creator, 'video_attributed_gmv'))}</td>
        <td class="num">${formatMoney(metricValue(creator, 'live_attributed_gmv'))}</td>
        <td class="score-cell"><div class="score-line"><strong>${decimalFormatter.format(score)}</strong><span class="mini-track"><span style="--score-width:${Math.max(0, Math.min(100, score))}%"></span></span></div></td>
      </tr>`;
  }

  function updateCreatorResults() {
    const root = document.getElementById('creator-results');
    if (!root) return;
    const rows = filteredCreators();
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    state.list.page = Math.min(state.list.page, pages);
    const start = (state.list.page - 1) * PAGE_SIZE;
    const visible = rows.slice(start, start + PAGE_SIZE);
    root.innerHTML = `
      <div class="result-bar">
        <span>找到 <strong>${formatNumber(rows.length)}</strong> 位达人${rows.length ? ` · 显示 ${start + 1}–${Math.min(start + PAGE_SIZE, rows.length)}` : ''}</span>
        <span class="compare-hint">已选 ${state.selected.size}/${MAX_COMPARE} 位用于对比</span>
      </div>
      ${visible.length ? `
        <div class="table-wrap">
          <table>
            <thead><tr><th class="check-cell">对比</th><th>达人</th><th class="num">历史 GMV</th><th class="num">合作后 GMV</th><th class="num">出单件数</th><th class="num">视频归因 GMV</th><th class="num">直播归因 GMV</th><th>评分</th></tr></thead>
            <tbody>${visible.map(creatorRow).join('')}</tbody>
          </table>
        </div>` : '<div class="empty-state">没有符合当前条件的达人，请调整筛选。</div>'}
      <div class="pagination" aria-label="分页">
        <button class="btn btn-quiet" type="button" data-page="prev" ${state.list.page <= 1 ? 'disabled' : ''}>上一页</button>
        <span class="page-status">第 ${state.list.page} / ${pages} 页</span>
        <button class="btn btn-quiet" type="button" data-page="next" ${state.list.page >= pages ? 'disabled' : ''}>下一页</button>
      </div>`;

    root.querySelectorAll('.creator-row').forEach(row => {
      const open = () => { window.location.hash = creatorUrl(row.dataset.key); };
      row.addEventListener('click', event => { if (!event.target.closest('input, button, a')) open(); });
      row.addEventListener('keydown', event => {
        if (event.key === 'Enter') { event.preventDefault(); open(); }
      });
    });
    root.querySelectorAll('.compare-check').forEach(input => input.addEventListener('change', handleCompareCheck));
    root.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => {
      state.list.page += button.dataset.page === 'next' ? 1 : -1;
      updateCreatorResults();
      root.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
    refreshCompareAction();
  }

  function handleCompareCheck(event) {
    const key = event.target.dataset.key;
    if (event.target.checked) {
      if (state.selected.size >= MAX_COMPARE) {
        event.target.checked = false;
        showToast('最多可同时对比 3 位达人');
        return;
      }
      state.selected.add(key);
    } else {
      state.selected.delete(key);
    }
    updateCompareCount();
    refreshCompareAction();
    const hint = document.querySelector('.compare-hint');
    if (hint) hint.textContent = `已选 ${state.selected.size}/${MAX_COMPARE} 位用于对比`;
  }

  function refreshCompareAction() {
    const action = document.getElementById('compare-action');
    if (!action) return;
    action.textContent = `对比已选达人（${state.selected.size}）`;
    action.href = compareUrl();
  }

  function metricCards(creator, group) {
    return group.keys.map(key => {
      const metric = creator.metrics?.[key] || {};
      const value = metric.value;
      const missing = value === null || value === undefined;
      return `
        <details class="metric-card">
          <summary>
            <span class="metric-label">${metricLabels[key] || escapeHtml(key)}</span>
            <span class="metric-value${missing ? ' missing' : ''}">${formatMetric(key, value)}</span>
          </summary>
          <div class="metric-source">
            <div><b>来源表：</b>${escapeHtml(metric.source_table || '待补录')}</div>
            <div><b>来源字段：</b>${escapeHtml(metric.source_field || '待补录')}</div>
            <div><b>批次：</b>${escapeHtml(metric.source_batches || '待补录')}</div>
          </div>
        </details>`;
    }).join('');
  }

  function dataTable(headers, rows, emptyText) {
    if (!rows.length) return `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
    return `<div class="table-wrap"><table><thead><tr>${headers.map(header => `<th${header.numeric ? ' class="num"' : ''}>${header.label}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
  }

  function creatorDetailView(key) {
    const creator = state.creatorMap.get(key);
    if (!creator) {
      app.innerHTML = `<section class="panel error-card"><span class="eyebrow">未找到达人</span><h1>这个达人不存在</h1><p>链接可能已失效，或数据集已更新。</p><a class="btn btn-primary" href="#/creators">返回达人列表</a></section>`;
      setPageTitle('达人不存在');
      return;
    }

    const evidence = creator.rating_evidence || {};
    const interval = evidence.matched_interval || {};
    const selected = state.selected.has(key);
    const intervalText = `${interval.min_score ?? '—'} ≤ 分数 ${interval.max_inclusive ? '≤' : '<'} ${interval.max_score ?? '—'}`;
    const evidenceRows = (evidence.participating_metrics || []).map(item => `
      <tr><td>${escapeHtml(item.label || item.metric)}</td><td class="num">${formatMetric(item.metric, item.value)}</td><td class="num">${decimalFormatter.format(Number(item.normalized_score) || 0)}</td><td class="num">${percentFormatter.format((Number(item.configured_weight) || 0) * 100)}%</td><td class="num">${decimalFormatter.format(Number(item.weighted_score) || 0)}</td></tr>`);

    const videoRows = (creator.videos || []).map(item => `
      <tr><td>${escapeHtml(item.video_id)}</td><td><strong>${escapeHtml(item.title || '未命名视频')}</strong><br><span class="muted">${escapeHtml(item.product_name || '—')}</span></td><td>${formatDate(item.published_at)}</td><td class="num">${formatMoney(item.attributed_gmv_vnd)}</td><td class="num">${formatNumber(item.views)}</td><td class="num">${formatNumber(item.likes)}</td></tr>`);
    const liveRows = (creator.lives || []).map(item => `
      <tr><td>${escapeHtml(item.source_record_key)}</td><td>${formatDate(item.started_at, true)}</td><td class="num">${formatMoney(item.attributed_gmv_vnd)}</td><td class="num">${formatNumber(item.viewers)}</td><td class="num">${formatNumber(item.view_count)}</td><td class="num">${formatNumber(item.likes)}</td><td class="num">${escapeHtml(item.duration || '待补录')}</td></tr>`);
    const costRows = (creator.costs || []).map(item => `
      <tr><td>${item.target_type === 'live' ? '直播' : '视频'}</td><td>${escapeHtml(item.target_id || '—')}</td><td class="num">${formatMoney(item.quote_vnd)}</td><td class="num">${formatMoney(item.collaboration_cost_vnd)}</td><td class="num">${formatMoney(item.slot_fee_vnd)}</td></tr>`);
    const commissionRows = (creator.commissions || []).map(item => `
      <tr><td>${formatDate(item.period_start)} — ${formatDate(item.period_end)}</td><td class="num">${formatMoney(item.organic_commission_vnd)}</td><td class="num">${formatMoney(item.paid_commission_vnd)}</td></tr>`);
    const timeline = (creator.followups || []).length
      ? `<div class="timeline">${creator.followups.map(item => `<article class="timeline-item"><div class="timeline-meta">${formatDate(item.followed_at, true)} · ${escapeHtml(item.bd_name || '未署名 BD')}</div><p class="timeline-content">${escapeHtml(item.content || '暂无内容')}</p><div class="timeline-next">下一步：${escapeHtml(item.next_step || '待确认')}</div></article>`).join('')}</div>`
      : '<div class="empty-state">暂无 BD 跟进记录</div>';

    app.innerHTML = `
      <nav class="breadcrumb" aria-label="面包屑"><a href="#/creators">达人列表</a><span>/</span><span>${escapeHtml(creator.display_name)}</span></nav>
      <section class="creator-hero">
        <div>
          <span class="eyebrow">达人档案 · ${escapeHtml(creator.platform || state.data.platform)}</span>
          <div class="creator-title-line"><h1>${escapeHtml(creator.display_name)}</h1>${gradeBadge(creator.grade)}<span class="score-pill"><strong>${decimalFormatter.format(Number(creator.score) || 0)}</strong>/ 100</span></div>
          <p class="identity-line">${escapeHtml(creator.creator_key)} · @${escapeHtml(creator.username || '—')}</p>
          <div class="detail-context">${tagsHtml(creator.tags)}${creator.annotation ? `<span class="detail-annotation">${escapeHtml(creator.annotation)}</span>` : ''}</div>
        </div>
        <div class="head-actions">
          <button id="detail-compare" class="btn ${selected ? 'btn-danger' : 'btn-primary'}" type="button">${selected ? '移出对比' : '加入对比'}</button>
          <a class="btn" href="#/creators">返回列表</a>
        </div>
      </section>

      <section class="section-block">
        <div class="section-title"><h2>指标档案</h2><p>点击任一指标查看来源字段与批次</p></div>
        <div class="metric-groups">
          ${metricGroups.map(group => `<article class="panel metric-group"><h3>${group.title}</h3><div class="metric-grid">${metricCards(creator, group)}</div></article>`).join('')}
        </div>
      </section>

      <details class="panel section-block" open>
        <summary class="evidence-summary"><h2>评级依据</h2><span class="interval-chip">${escapeHtml(interval.grade || creator.grade)} 级 · ${escapeHtml(intervalText)}</span></summary>
        <div class="evidence-body">
          <p class="formula-note">${escapeHtml(evidence.formula || '暂无评分公式')} · ${escapeHtml(evidence.missing_metric_policy || '')}</p>
          ${dataTable([
            {label: '参与指标'}, {label: '原始值', numeric: true}, {label: '归一分', numeric: true}, {label: '权重', numeric: true}, {label: '加权分', numeric: true}
          ], evidenceRows, '暂无评级依据')}
        </div>
      </details>

      <section class="section-block detail-grid">
        <article class="subsection full">
          <div class="section-title"><h2>视频明细</h2><p>${formatNumber(creator.video_count)} 条</p></div>
          ${dataTable([{label:'视频 ID'},{label:'标题 / 商品'},{label:'发布时间'},{label:'归因 GMV',numeric:true},{label:'VV',numeric:true},{label:'点赞',numeric:true}], videoRows, '暂无视频记录')}
        </article>
        <article class="subsection full">
          <div class="section-title"><h2>直播明细</h2><p>${formatNumber(creator.live_count)} 场</p></div>
          ${dataTable([{label:'记录 ID'},{label:'开播时间'},{label:'归因 GMV',numeric:true},{label:'观众',numeric:true},{label:'观看次数',numeric:true},{label:'点赞',numeric:true},{label:'时长'}], liveRows, '暂无直播记录')}
        </article>
        <article class="subsection">
          <div class="section-title"><h2>成本与坑位费</h2><p>${costRows.length} 条</p></div>
          ${dataTable([{label:'类型'},{label:'目标 ID'},{label:'报价',numeric:true},{label:'合作成本',numeric:true},{label:'坑位费',numeric:true}], costRows, '暂无成本记录')}
        </article>
        <article class="subsection">
          <div class="section-title"><h2>自然流 / 付费流佣金</h2><p>${commissionRows.length} 个周期</p></div>
          ${dataTable([{label:'周期'},{label:'自然流佣金',numeric:true},{label:'付费流佣金',numeric:true}], commissionRows, '暂无佣金记录')}
        </article>
        <article class="panel subsection full">
          <div class="section-title"><h2>BD 跟进时间线</h2><p>${(creator.followups || []).length} 条</p></div>
          ${timeline}
        </article>
      </section>`;

    document.getElementById('detail-compare').addEventListener('click', event => {
      if (state.selected.has(key)) {
        state.selected.delete(key);
        event.currentTarget.textContent = '加入对比';
        event.currentTarget.className = 'btn btn-primary';
      } else if (state.selected.size >= MAX_COMPARE) {
        showToast('最多可同时对比 3 位达人');
        return;
      } else {
        state.selected.add(key);
        event.currentTarget.textContent = '移出对比';
        event.currentTarget.className = 'btn btn-danger';
      }
      updateCompareCount();
    });
  }

  function comparisonRows(creators) {
    const definitions = [
      ['评分', creator => Number(creator.score), value => decimalFormatter.format(value), true],
      ['历史 GMV', creator => metricValue(creator, 'historical_gmv'), formatMoney, true],
      ['合作后 GMV', creator => metricValue(creator, 'post_collaboration_gmv'), formatMoney, true],
      ['出单件数', creator => metricValue(creator, 'sold_items'), formatNumber, true],
      ['费比 ROI', creator => metricValue(creator, 'cost_ratio_roi'), formatRoi, true],
      ['历史 ROI', creator => metricValue(creator, 'historical_roi'), formatRoi, true],
      ['视频归因 GMV', creator => metricValue(creator, 'video_attributed_gmv'), formatMoney, true],
      ['视频总 ROI', creator => metricValue(creator, 'video_total_roi'), formatRoi, true],
      ['视频数量', creator => Number(creator.video_count), formatNumber, true],
      ['直播归因 GMV', creator => metricValue(creator, 'live_attributed_gmv'), formatMoney, true],
      ['直播总 ROI', creator => metricValue(creator, 'live_total_roi'), formatRoi, true],
      ['直播数量', creator => Number(creator.live_count), formatNumber, true]
    ];
    return definitions.map(([label, getter, formatter, highlight]) => {
      const values = creators.map(getter);
      const comparable = values.filter(value => value !== null && Number.isFinite(Number(value))).map(Number);
      const best = comparable.length ? Math.max(...comparable) : null;
      return `<tr><th scope="row">${label}</th>${values.map(value => `<td class="num ${highlight && best !== null && Number(value) === best ? 'best' : ''}">${formatter(value)}</td>`).join('')}</tr>`;
    }).join('');
  }

  function compareView(routeKeys) {
    if (routeKeys.length) {
      const valid = routeKeys.filter(key => state.creatorMap.has(key)).slice(0, MAX_COMPARE);
      state.selected = new Set(valid);
      updateCompareCount();
    }
    const creators = [...state.selected].map(key => state.creatorMap.get(key)).filter(Boolean);
    if (creators.length < 2) {
      const suggestions = [...state.data.creators]
        .sort((a, b) => (metricValue(b, 'historical_gmv') || 0) - (metricValue(a, 'historical_gmv') || 0))
        .slice(0, 8);
      app.innerHTML = `
        <section class="panel compare-empty">
          <span class="eyebrow">达人对比</span>
          <h1>还需选择 ${2 - creators.length} 位达人</h1>
          <p>并排对比需要 2–3 位达人。可返回列表筛选，或从下方高 GMV 达人中补选。</p>
          <a class="btn btn-primary" href="#/creators">前往达人列表</a>
          <div class="creator-picks">
            ${suggestions.map(creator => `<button class="btn btn-quiet" type="button" data-pick-key="${escapeHtml(creator.creator_key)}" ${state.selected.has(creator.creator_key) ? 'disabled' : ''}>${gradeBadge(creator.grade)} ${escapeHtml(creator.display_name)}</button>`).join('')}
          </div>
        </section>`;
      app.querySelectorAll('[data-pick-key]').forEach(button => button.addEventListener('click', () => {
        if (state.selected.size < MAX_COMPARE) state.selected.add(button.dataset.pickKey);
        updateCompareCount();
        if (state.selected.size >= 2) window.location.hash = compareUrl();
        else compareView([]);
      }));
      return;
    }

    app.innerHTML = `
      <section class="page-head">
        <div>
          <span class="eyebrow">并排研判 · ${creators.length} 位达人</span>
          <h1>达人对比</h1>
          <p class="lede">同一指标中数值最高者以绿色标记；“待补录”不参与高值判断。</p>
        </div>
        <div class="head-actions"><a class="btn" href="#/creators">调整选择</a></div>
      </section>
      <section class="compare-board">
        <table class="compare-table">
          <thead>
            <tr>
              <th>关键指标</th>
              ${creators.map(creator => `<th><div class="compare-person">${gradeBadge(creator.grade)}<strong>${escapeHtml(creator.display_name)}</strong><small>${escapeHtml(creator.creator_key)}</small><button class="btn btn-quiet btn-danger" type="button" data-remove-key="${escapeHtml(creator.creator_key)}">移出对比</button></div></th>`).join('')}
            </tr>
          </thead>
          <tbody>
            <tr><th scope="row">等级</th>${creators.map(creator => `<td>${gradeBadge(creator.grade)}</td>`).join('')}</tr>
            ${comparisonRows(creators)}
          </tbody>
        </table>
      </section>`;
    app.querySelectorAll('[data-remove-key]').forEach(button => button.addEventListener('click', () => {
      state.selected.delete(button.dataset.removeKey);
      updateCompareCount();
      window.location.hash = compareUrl();
      if (window.location.hash === '#/compare') compareView([]);
    }));
  }

  function route() {
    if (!state.data) return;
    const raw = window.location.hash || '#/dashboard';
    const segments = raw.replace(/^#\/?/, '').split('/').filter(Boolean);
    const section = segments[0] || 'dashboard';

    if (section === 'creators') {
      setActiveNav('creators');
      setPageTitle('达人列表');
      creatorsView();
    } else if (section === 'creator') {
      setActiveNav('creators');
      const key = safeDecode(segments.slice(1).join('/'));
      const creator = state.creatorMap.get(key);
      setPageTitle(creator ? creator.display_name : '达人详情');
      creatorDetailView(key);
    } else if (section === 'compare') {
      setActiveNav('compare');
      setPageTitle('达人对比');
      compareView(segments.slice(1).map(safeDecode));
    } else {
      if (section !== 'dashboard') history.replaceState(null, '', '#/dashboard');
      setActiveNav('dashboard');
      setPageTitle('经营看板');
      dashboardView();
    }
    focusMain();
  }

  async function init() {
    try {
      const data = await loadData();
      validateData(data);
      state.data = data;
      state.creatorMap = new Map(data.creators.map(creator => [creator.creator_key, creator]));
      timestamp.textContent = `数据生成：${formatDate(data.generated_at_utc, true)}`;
      updateCompareCount();
      window.addEventListener('hashchange', route);
      if (!window.location.hash) history.replaceState(null, '', '#/dashboard');
      route();
    } catch (error) {
      renderError(error);
    }
  }

  init();
})();
