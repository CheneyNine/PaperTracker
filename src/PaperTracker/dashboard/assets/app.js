"use strict";

const state = {
  activePapers: [],
  archivedPapers: [],
  queryLabels: [],
  researchThemes: [],
  themeBoards: [],
  selectedThemeId: null,
  editingThemeId: null,
  ccfVenueCount: 0,
  ccfLastUpdatedAt: null,
  updatedAt: null,
  currentView: "papers",
  settings: null,
  availableRefreshSources: [],
  selectedRefreshSources: [],
  expandedPaperKeys: new Set(),
  filterMode: "all",
  sortMode: "default",
  suggestingQueries: false,
  settingsFeedback: "",
  settingsFeedbackIsError: false,
  ccfFeedback: "",
  ccfFeedbackIsError: false,
  llmDiscoveryFeedback: "",
  llmDiscoveryFeedbackIsError: false,
  llmDiscoveredModels: [],
  llmDiscoveryRunning: false,
  settingsLoading: false,
  settingsSaving: false,
  loading: false,
  refreshing: false,
};

const DEFAULT_REFRESH_STATUS = "只会刷新当前选中的研究主题，并按这个主题下的关键词去检索、补齐摘要与贡献度。";
const SOURCE_LABELS = {
  dblp: "DBLP",
  openreview: "OpenReview",
  arxiv: "arXiv",
  openalex: "OpenAlex",
  pubmed: "PubMed",
};
const TARGET_LANGUAGE_OPTIONS = [
  "Simplified Chinese",
  "Traditional Chinese",
  "English",
  "Japanese",
  "Korean",
];
const SOURCE_STORAGE_KEY = "paper-tracker-dashboard-sources";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function paperKey(paper) {
  return `${paper.source || "unknown"}::${paper.source_id || paper.title || ""}`;
}

function renderKeywordChip(text, { tone = "blue" } = {}) {
  const className = tone === "gray" ? "keyword-chip keyword-chip-gray" : "keyword-chip";
  return `<span class="${className}"><span class="chip-mark">#</span>${escapeHtml(text)}</span>`;
}

function renderStatusChip(text, title = "") {
  const titleAttr = title ? ` title="${escapeHtml(title)}"` : "";
  return `<span class="status-chip"${titleAttr}>${escapeHtml(text)}</span>`;
}

function sourceLabel(sourceName) {
  return SOURCE_LABELS[String(sourceName || "").toLowerCase()] || String(sourceName || "").toUpperCase();
}

function renderTargetLanguageOptions(currentValue) {
  const normalizedCurrent = String(currentValue || "").trim();
  const options = [...TARGET_LANGUAGE_OPTIONS];
  if (normalizedCurrent && !options.includes(normalizedCurrent)) {
    options.unshift(normalizedCurrent);
  }
  return options.map((value) => `
    <option value="${escapeHtml(value)}" ${value === normalizedCurrent ? "selected" : ""}>${escapeHtml(value)}</option>
  `).join("");
}

function renderModelOptions(currentValue) {
  const normalizedCurrent = String(currentValue || "").trim();
  const options = [];
  const seen = new Set();

  if (!state.llmDiscoveredModels.length) {
    options.push(`<option value="">请先检测并加载模型</option>`);
  }

  if (normalizedCurrent) {
    seen.add(normalizedCurrent);
    options.push(`
      <option value="${escapeHtml(normalizedCurrent)}" selected>${escapeHtml(normalizedCurrent)}</option>
    `);
  }

  state.llmDiscoveredModels.forEach((value) => {
    const model = String(value || "").trim();
    if (!model || seen.has(model)) {
      return;
    }
    seen.add(model);
    options.push(`
      <option value="${escapeHtml(model)}" ${model === normalizedCurrent ? "selected" : ""}>${escapeHtml(model)}</option>
    `);
  });

  return options.join("");
}

function applySettings(data) {
  if (!data || typeof data !== "object") {
    return;
  }
  state.settings = {
    llm: data.llm || {},
    search: data.search || {},
  };
}

function filterChipDefinitions() {
  return [
    { mode: "all", label: "📚 全部", count: countFilteredPapers("all") },
    { mode: "arxiv", label: "🗂️ arXiv", count: countFilteredPapers("arxiv") },
    { mode: "ccfA", label: "🎤 CCF-A", count: countFilteredPapers("ccfA") },
    { mode: "ccfB", label: "📘 CCF-B", count: countFilteredPapers("ccfB") },
  ];
}

function renderFilterChipMarkup() {
  return filterChipDefinitions().map((chip) => `
      <button
        type="button"
        class="filter-chip ${state.filterMode === chip.mode ? "is-active" : ""}"
        data-filter-mode="${escapeHtml(chip.mode)}"
      >
        <span class="filter-chip-label">${escapeHtml(chip.label)}</span>
        <span class="filter-chip-count">${escapeHtml(String(chip.count))} 篇</span>
      </button>
  `).join("");
}

function renderKeywordRow(paper) {
  const chips = [];
  if (paper.matched_query) {
    chips.push(renderKeywordChip(paper.matched_query));
  }
  if (paper.primary_category) {
    chips.push(renderKeywordChip(paper.primary_category, { tone: "gray" }));
  }
  if (paper.ccf_rank) {
    chips.push(renderKeywordChip(paper.ccf_rank, { tone: "gray" }));
  }
  if (paper.source) {
    chips.push(renderKeywordChip(paper.source, { tone: "gray" }));
  }
  if (paper.theme_contribution_score !== null && paper.theme_contribution_score !== undefined) {
    chips.push(renderStatusChip(`贡献度 ${paper.theme_contribution_score}%`, paper.theme_contribution_rationale || ""));
  }
  return chips.join("");
}

function renderActionLink(label, href, { primary = false } = {}) {
  if (!href) {
    return `<span class="paper-inline-link is-disabled">${escapeHtml(label)}</span>`;
  }
  const classes = primary ? "paper-inline-link is-primary" : "paper-inline-link";
  return `<a class="${classes}" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
}

function renderSummaryBlock(label, value) {
  if (!value) {
    return "";
  }
  return `
    <section class="summary-block">
      <strong>${escapeHtml(label)}</strong>
      <p>${escapeHtml(value)}</p>
    </section>
  `;
}

function renderInsightRow(emoji, label, value) {
  if (!value) {
    return "";
  }
  return `
    <div class="insight-row">
      <div class="insight-label">${escapeHtml(emoji)} ${escapeHtml(label)}</div>
      <div class="insight-content">${escapeHtml(value)}</div>
    </div>
  `;
}

function renderPaperCard(paper) {
  const key = paperKey(paper);
  const isExpanded = state.expandedPaperKeys.has(key);
  const summaryToggleText = isExpanded ? "收起完整摘要" : "查看完整摘要";
  return `
    <article class="paper-card ${isExpanded ? "is-expanded" : ""}">
      <div class="paper-headline">
        <div>
          <h3 class="paper-title">${escapeHtml(paper.title)}</h3>
          <p class="paper-authors">${escapeHtml((paper.authors || []).join(", "))}</p>
          <div class="paper-keywords">${renderKeywordRow(paper)}</div>
        </div>
        <button
          type="button"
          class="paper-button is-danger"
          data-archive-action="archive"
          data-source="${escapeHtml(paper.source)}"
          data-source-id="${escapeHtml(paper.source_id)}"
        >
          Archive
        </button>
      </div>

      <div class="paper-insights">
        ${renderInsightRow("🎯", "研究动机", paper.motivation)}
        ${renderInsightRow("🧩", "解决问题", paper.problem)}
        ${renderInsightRow("🔎", "现状分析", paper.tldr)}
        ${renderInsightRow("🛠️", "主要方法和数据", paper.method)}
        ${renderInsightRow("🧪", "数据实验", paper.result)}
        ${renderInsightRow("🌟", "主要贡献", paper.conclusion)}
      </div>

      <div class="paper-actions">
        <button
          type="button"
          class="paper-toggle"
          data-summary-action="toggle"
          data-paper-key="${escapeHtml(key)}"
        >
          ${escapeHtml(summaryToggleText)}
        </button>
        ${renderActionLink("查看 PDF", paper.pdf_url, { primary: false })}
        ${renderActionLink("打开原链接", paper.abstract_url, { primary: false })}
      </div>

      <div class="paper-summary">
        <div class="summary-grid">
          ${renderSummaryBlock("📝 摘要翻译", paper.abstract_translation)}
          ${renderSummaryBlock("📄 英文摘要", paper.abstract)}
        </div>
      </div>

      <div class="paper-footer">
        <span>Published: ${escapeHtml(paper.published_at || "-")}</span>
        <span>Updated: ${escapeHtml(paper.updated_at || "-")}</span>
        <span>Fetched: ${escapeHtml(paper.fetched_at || "-")}</span>
      </div>
    </article>
  `;
}

function renderArchivedPaper(paper) {
  return `
    <article class="archive-card">
      <h3>${escapeHtml(paper.title)}</h3>
      <p class="paper-authors">${escapeHtml((paper.authors || []).join(", "))}</p>
      <div class="archive-meta">
        ${paper.source ? renderKeywordChip(paper.source, { tone: "gray" }) : ""}
        ${paper.matched_query ? renderKeywordChip(paper.matched_query) : ""}
        ${paper.archived_at ? renderStatusChip(`归档于 ${paper.archived_at}`) : ""}
      </div>
      <div class="paper-actions">
        ${renderActionLink("查看 PDF 文件", paper.pdf_url)}
        ${renderActionLink("打开原链接", paper.abstract_url)}
        <button
          type="button"
          class="paper-button"
          data-archive-action="restore"
          data-source="${escapeHtml(paper.source)}"
          data-source-id="${escapeHtml(paper.source_id)}"
        >
          Restore
        </button>
      </div>
    </article>
  `;
}

function applySnapshot(data) {
  state.activePapers = Array.isArray(data.active_papers) ? data.active_papers : [];
  state.archivedPapers = Array.isArray(data.archived_papers) ? data.archived_papers : [];
  state.queryLabels = Array.isArray(data.query_labels) ? data.query_labels : [];
  state.researchThemes = Array.isArray(data.research_themes) ? data.research_themes : [];
  state.themeBoards = Array.isArray(data.theme_boards) ? data.theme_boards : [];
  const validThemeIds = new Set(
    state.themeBoards
      .map((board) => Number(board?.theme?.id))
      .filter((value) => Number.isInteger(value) && value > 0)
  );
  if (!validThemeIds.has(Number(state.selectedThemeId))) {
    state.selectedThemeId = state.themeBoards.length ? Number(state.themeBoards[0].theme.id) : null;
  }
  const selectedBoard = getSelectedThemeBoard();
  const selectedQueryLabels = Array.isArray(selectedBoard?.query_labels) ? selectedBoard.query_labels : [];
  if (
    !selectedBoard
    || (state.filterMode.startsWith("label:")
      && !selectedQueryLabels.includes(state.filterMode.slice("label:".length)))
  ) {
    state.filterMode = "all";
  }
  state.ccfVenueCount = Number(data.ccf_venue_count || 0);
  state.ccfLastUpdatedAt = data.ccf_last_updated_at || null;
  state.updatedAt = data.updated_at || null;
  state.availableRefreshSources = Array.isArray(data.available_refresh_sources)
    ? data.available_refresh_sources
      .map((item) => String(item || "").trim().toLowerCase())
      .filter(Boolean)
    : [];
  const defaultSources = Array.isArray(data.default_refresh_sources)
    ? data.default_refresh_sources
      .map((item) => String(item || "").trim().toLowerCase())
      .filter(Boolean)
    : [];
  const storedSources = loadStoredRefreshSources();
  const currentSources = state.selectedRefreshSources.length
    ? state.selectedRefreshSources
    : storedSources.length
      ? storedSources
      : defaultSources;
  const allowedSources = new Set(state.availableRefreshSources);
  const nextSources = currentSources.filter((source) => allowedSources.has(source));
  state.selectedRefreshSources = nextSources.length
    ? nextSources
    : defaultSources.filter((source) => allowedSources.has(source));
  persistRefreshSources(state.selectedRefreshSources);
}

function filterPaperList(papers) {
  return filterPaperListByMode(papers, state.filterMode);
}

function filteredActivePapers() {
  return filterPaperList(state.activePapers);
}

function groupPapersByQuery() {
  const groups = new Map();
  state.queryLabels.forEach((label) => groups.set(label, []));
  filteredActivePapers().forEach((paper) => {
    const label = paper.matched_query || "Unlabeled";
    if (!groups.has(label)) {
      groups.set(label, []);
    }
    groups.get(label).push(paper);
  });
  return Array.from(groups.entries());
}

function renderQueryDirectory(groups) {
  const directory = document.getElementById("query-directory");
  if (!directory) {
    return;
  }
  directory.innerHTML = groups.map(([label, papers]) => `
    <div class="query-row">
      <a class="query-link" href="#query-${encodeURIComponent(`${label}-${String(state.selectedThemeId || "")}`)}">
        <strong>${escapeHtml(label)}</strong>
        <span>${papers.length} 篇论文</span>
      </a>
      <button
        type="button"
        class="query-delete"
        data-query-action="delete"
        data-query-label="${escapeHtml(label)}"
      >
        删除
      </button>
    </div>
  `).join("");
}

function clearThemeForm() {
  const nameInput = document.getElementById("theme-name-input");
  const descriptionInput = document.getElementById("theme-description-input");
  if (nameInput instanceof HTMLInputElement) {
    nameInput.value = "";
  }
  if (descriptionInput instanceof HTMLTextAreaElement) {
    descriptionInput.value = "";
  }
}

function buildQueryGroups(queryLabels, papers) {
  const groups = new Map();
  (queryLabels || []).forEach((label) => groups.set(label, []));
  (papers || []).forEach((paper) => {
    const label = paper.matched_query || "Unlabeled";
    if (!groups.has(label)) {
      groups.set(label, []);
    }
    groups.get(label).push(paper);
  });
  return Array.from(groups.entries());
}

function contributionScore(paper) {
  const score = Number(paper?.theme_contribution_score);
  return Number.isFinite(score) ? score : -1;
}

function sortPaperGroups(groups) {
  if (state.sortMode !== "contribution") {
    return groups;
  }
  return groups
    .map(([label, papers]) => [
      label,
      [...papers].sort((left, right) => contributionScore(right) - contributionScore(left)),
    ])
    .sort((left, right) => {
      const leftTop = left[1].length ? contributionScore(left[1][0]) : -1;
      const rightTop = right[1].length ? contributionScore(right[1][0]) : -1;
      return rightTop - leftTop;
    });
}

function renderResearchThemes() {
  const directory = document.getElementById("theme-directory");
  if (!directory) {
    return;
  }
  if (!state.researchThemes.length) {
    directory.innerHTML = `<p class="empty-state">先添加一个研究主题，刷新后这里的论文卡片才会出现贡献度百分比。</p>`;
    return;
  }
  directory.innerHTML = state.researchThemes.map((theme) => {
    const board = state.themeBoards.find((item) => Number(item?.theme?.id) === Number(theme.id));
    const isEditing = Number(theme.id) === Number(state.editingThemeId);
    if (isEditing) {
      return `
    <article class="theme-card is-editing">
      <div class="theme-card-head">
        <div class="theme-inline-edit">
          <input
            type="text"
            class="sidebar-input theme-inline-input"
            value="${escapeHtml(theme.name)}"
            data-theme-edit-name="${escapeHtml(theme.id)}"
          >
          <textarea
            class="sidebar-input sidebar-textarea theme-inline-textarea"
            data-theme-edit-description="${escapeHtml(theme.id)}"
          >${escapeHtml(theme.description || "")}</textarea>
        </div>
      </div>
      <div class="theme-actions">
        <button
          type="button"
          class="theme-mini"
          data-theme-action="save-inline"
          data-theme-id="${escapeHtml(theme.id)}"
        >
          保存
        </button>
        <button
          type="button"
          class="theme-mini"
          data-theme-action="cancel-inline"
          data-theme-id="${escapeHtml(theme.id)}"
        >
          取消
        </button>
      </div>
    </article>
  `;
    }
    return `
    <article class="theme-card ${Number(theme.id) === Number(state.selectedThemeId) ? "is-active" : ""}">
      <div class="theme-card-head">
        <button
          type="button"
          class="theme-card-select"
          data-theme-select="${escapeHtml(theme.id)}"
        >
          <h3>${escapeHtml(theme.name)}</h3>
          <p>${escapeHtml(theme.description || "")}</p>
          <div class="theme-card-meta">
            <span class="theme-card-count">${escapeHtml(String(board?.paper_count || 0))} 篇论文</span>
            <span class="theme-card-count">${escapeHtml(String((board?.query_labels || []).length))} 个关键词</span>
          </div>
        </button>
      </div>
      <div class="theme-actions">
        <button
          type="button"
          class="theme-mini"
          data-theme-action="edit"
          data-theme-id="${escapeHtml(theme.id)}"
        >
          编辑
        </button>
        <button
          type="button"
          class="theme-mini"
          data-theme-action="delete"
          data-theme-id="${escapeHtml(theme.id)}"
        >
          删除
        </button>
      </div>
    </article>
  `;
  }).join("");
}

function renderSourceSelector() {
  const containers = document.querySelectorAll("#source-selector");
  if (!containers.length) {
    return;
  }
  const content = !state.availableRefreshSources.length
    ? `<p class="empty-state">当前配置里还没有可用渠道。</p>`
    : state.availableRefreshSources.map((sourceName) => `
    <button
      type="button"
      class="sidebar-button source-chip ${state.selectedRefreshSources.includes(sourceName) ? "is-active" : ""}"
      data-source-toggle="${escapeHtml(sourceName)}"
    >
      ${escapeHtml(sourceLabel(sourceName))}
    </button>
  `).join("");
  containers.forEach((container) => {
    container.innerHTML = content;
  });
}

function renderCcfStatus() {
  const statusNodes = document.querySelectorAll("#ccf-status");
  if (!statusNodes.length) {
    return;
  }
  const timeText = state.ccfLastUpdatedAt ? `上次写入 ${state.ccfLastUpdatedAt}` : "还没有本地缓存时间";
  const text = `当前缓存 ${state.ccfVenueCount} 个 CCF venue。${timeText}。`;
  statusNodes.forEach((status) => {
    status.textContent = text;
  });
}

function renderCcfFeedback() {
  const feedbackNodes = document.querySelectorAll("#ccf-feedback");
  if (!feedbackNodes.length) {
    return;
  }
  feedbackNodes.forEach((node) => {
    node.textContent = state.ccfFeedback || "";
    node.style.color = state.ccfFeedbackIsError ? "#b42318" : "";
  });
}

function renderLlmDiscoveryFeedback() {
  const feedbackNode = document.getElementById("llm-discovery-feedback");
  if (!feedbackNode) {
    return;
  }
  feedbackNode.textContent = state.llmDiscoveryFeedback || "";
  feedbackNode.style.color = state.llmDiscoveryFeedbackIsError ? "#b42318" : "";
}

function renderSettingsView() {
  const container = document.getElementById("settings-view");
  if (!container) {
    return;
  }
  if (state.currentView !== "settings") {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  if (state.settingsLoading && !state.settings) {
    container.innerHTML = `<p class="empty-state">正在加载设置…</p>`;
    return;
  }
  const settings = state.settings || { llm: {}, search: {} };
  const llm = settings.llm || {};
  const search = settings.search || {};
  const supportedSources = Array.isArray(search.supported_sources) ? search.supported_sources : [];
  const selectedSources = Array.isArray(search.sources) ? search.sources : [];
  const selectedRanks = Array.isArray(search.ccf_ranks) ? search.ccf_ranks : [];
  container.innerHTML = `
    <section class="settings-shell">
      <header class="settings-header">
        <div>
          <p class="content-kicker">Settings</p>
          <h2>配置中心</h2>
          <p class="content-sub">这里可以直接维护 LLM 和默认检索渠道设置，保存后下一次更新会立即按新配置生效。</p>
        </div>
      </header>
      <form id="settings-form" class="settings-form">
        <section class="settings-card">
          <div class="settings-card-head">
            <h3>LLM 设置</h3>
            <label class="settings-toggle">
              <input type="checkbox" name="llm_enabled" ${llm.enabled ? "checked" : ""}>
              <span>启用 LLM</span>
            </label>
          </div>
          <div class="settings-grid settings-grid-llm-top">
            <label class="settings-field">
              <span>Base URL</span>
              <input
                class="sidebar-input"
                type="text"
                name="llm_base_url"
                value="${escapeHtml(llm.base_url || "")}"
                placeholder="例如：https://api.openai.com/v1"
              >
            </label>
            <label class="settings-field">
              <span>${escapeHtml(llm.api_key_env || "LLM_API_KEY")}${llm.api_key_set ? ' <small style="opacity:0.6">（已配置，留空保持不变）</small>' : ''}</span>
              <input
                class="sidebar-input"
                type="password"
                name="llm_api_key"
                value=""
                placeholder="${llm.api_key_set ? '留空保持不变，或输入新 Key' : '例如：sk-...'}"
              >
            </label>
            <label class="settings-field">
              <span>连接检测</span>
              <button id="llm-discovery-button" type="button" class="sidebar-button settings-inline-button">${state.llmDiscoveryRunning ? "检测中…" : "检测并加载"}</button>
            </label>
          </div>
          <div class="settings-grid settings-grid-llm-bottom">
            <label class="settings-field">
              <span>Model</span>
              <select
                class="sidebar-input"
                name="llm_model"
              >
                ${renderModelOptions(llm.model || "")}
              </select>
            </label>
            <label class="settings-field">
              <span>目标语言</span>
              <select
                class="sidebar-input"
                name="llm_target_lang"
                autocomplete="off"
                autocapitalize="none"
                spellcheck="false"
                data-1p-ignore="true"
                data-lpignore="true"
                data-form-type="other"
              >
                ${renderTargetLanguageOptions(llm.target_lang || "Simplified Chinese")}
              </select>
            </label>
          </div>
          <div class="settings-check-row">
            <label class="settings-check">
              <input type="checkbox" name="llm_enable_translation" ${llm.enable_translation ? "checked" : ""}>
              <span>摘要翻译</span>
            </label>
            <label class="settings-check">
              <input type="checkbox" name="llm_enable_summary" ${llm.enable_summary ? "checked" : ""}>
              <span>结构化摘要</span>
            </label>
          </div>
          <p id="llm-discovery-feedback" class="sidebar-feedback"></p>
        </section>

        <section class="settings-card">
          <div class="settings-card-head">
            <h3>检索设置</h3>
            <label class="settings-toggle">
              <input type="checkbox" name="search_ccf_enabled" ${search.ccf_enabled ? "checked" : ""}>
              <span>启用 CCF 匹配</span>
            </label>
          </div>
          <div class="settings-field">
            <span>默认检索网站</span>
            <p class="sidebar-feedback">只有选中的渠道会参与本次更新。</p>
            <div class="settings-choice-grid">
              ${supportedSources.map((sourceName) => `
                <label class="settings-check settings-choice-item">
                  <input
                    type="checkbox"
                    name="search_sources"
                    value="${escapeHtml(sourceName)}"
                    ${selectedSources.includes(sourceName) ? "checked" : ""}
                  >
                  <span>${escapeHtml(sourceLabel(sourceName))}</span>
                </label>
              `).join("")}
            </div>
          </div>
          <div class="settings-field">
            <span>CCF 等级范围</span>
            <div class="settings-check-row">
              ${["A", "B", "C"].map((rank) => `
                <label class="settings-check">
                  <input type="checkbox" name="search_ccf_ranks" value="${rank}" ${selectedRanks.includes(rank) ? "checked" : ""}>
                  <span>CCF-${rank}</span>
                </label>
              `).join("")}
            </div>
          </div>
          <div class="settings-grid">
            <label class="settings-field">
              <span>arXiv 请求间隔（秒）</span>
              <input
                class="sidebar-input"
                type="number"
                step="0.5"
                min="1"
                name="search_arxiv_interval"
                value="${escapeHtml(String(search.arxiv_min_interval_seconds ?? 5))}"
              >
            </label>
            <label class="settings-field">
              <span>${escapeHtml(search.ncbi_api_key_env || "NCBI_API_KEY")}${search.ncbi_api_key_set ? ' <small style="opacity:0.6">（已配置，留空保持不变）</small>' : ''}</span>
              <input class="sidebar-input" type="password" name="search_ncbi_api_key" value="" placeholder="${search.ncbi_api_key_set ? '留空保持不变，或输入新 Key' : '可选，提升 PubMed 速率上限'}">
            </label>
          </div>
          <div class="settings-actions settings-actions-inline">
            <button id="ccf-refresh-button" type="button" class="sidebar-button">更新 CCF 白名单</button>
          </div>
          <p id="ccf-feedback" class="sidebar-feedback"></p>
          <p id="ccf-status" class="sidebar-feedback"></p>
        </section>

        <div class="settings-actions">
          <button type="submit" class="sidebar-button sidebar-button-primary">${state.settingsSaving ? "保存中…" : "保存设置"}</button>
          <p id="settings-feedback" class="sidebar-feedback"${state.settingsFeedbackIsError ? ' style="color:#b42318"' : ""}>${escapeHtml(state.settingsFeedback || "")}</p>
        </div>
      </form>
    </section>
  `;
}

function renderViewChrome() {
  const papersView = document.getElementById("papers-view");
  const settingsView = document.getElementById("settings-view");
  const themeSwitcher = document.getElementById("theme-switcher");
  const refreshButton = document.getElementById("refresh-button");
  const sortButton = document.getElementById("sort-button");
  const contentStatus = document.getElementById("content-status");
  const viewToggleButton = document.getElementById("view-toggle-button");
  const isSettings = state.currentView === "settings";
  if (papersView) {
    papersView.hidden = isSettings;
  }
  if (settingsView) {
    settingsView.hidden = !isSettings;
  }
  if (themeSwitcher) {
    themeSwitcher.hidden = isSettings;
  }
  if (refreshButton instanceof HTMLElement) {
    refreshButton.hidden = isSettings;
  }
  if (sortButton instanceof HTMLElement) {
    sortButton.hidden = isSettings;
  }
  if (contentStatus instanceof HTMLElement) {
    contentStatus.hidden = isSettings;
  }
  if (viewToggleButton instanceof HTMLButtonElement) {
    viewToggleButton.textContent = isSettings ? "返回看板" : "设置";
    viewToggleButton.classList.toggle("is-active", isSettings);
  }
}

function getSelectedThemeBoard() {
  return state.themeBoards.find((board) => Number(board?.theme?.id) === Number(state.selectedThemeId)) || null;
}

function renderSortButton() {
  const button = document.getElementById("sort-button");
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }
  const active = state.sortMode === "contribution";
  button.classList.toggle("is-active", active);
  button.textContent = active ? "恢复默认排序" : "按贡献度排序";
}

function countFilteredPapers(mode) {
  const selectedBoard = getSelectedThemeBoard();
  const papers = Array.isArray(selectedBoard?.papers) ? selectedBoard.papers : [];
  return filterPaperListByMode(papers, mode).length;
}

function filterPaperListByMode(papers, mode) {
  if (mode === "all") {
    return papers;
  }
  return papers.filter((paper) => {
    if (mode.startsWith("label:")) {
      return (paper.matched_query || "") === mode.slice("label:".length);
    }
    if (mode === "arxiv") {
      return String(paper.source || "").toLowerCase() === "arxiv";
    }
    if (mode === "ccfA") {
      return paper.ccf_rank === "CCF-A";
    }
    if (mode === "ccfB") {
      return paper.ccf_rank === "CCF-B";
    }
    return true;
  });
}

function renderFilterChips() {
  renderThemeSwitcher();
}

function renderThemeSwitcher() {
  const container = document.getElementById("theme-switcher");
  if (!container) {
    return;
  }
  const selectedBoard = getSelectedThemeBoard();
  if (!selectedBoard) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML = renderFilterChipMarkup();
}

function groupThemeBoardPapers(papers, queryLabels) {
  const groups = new Map();
  (queryLabels || []).forEach((label) => groups.set(label, []));
  filterPaperList(papers).forEach((paper) => {
    const label = paper.matched_query || "Unlabeled";
    if (!groups.has(label)) {
      groups.set(label, []);
    }
    groups.get(label).push(paper);
  });
  return Array.from(groups.entries()).filter(([, items]) => items.length > 0);
}

function renderLists() {
  const activeList = document.getElementById("active-list");
  const archiveList = document.getElementById("archive-list");
  const selectedBoard = getSelectedThemeBoard();
  const selectedBoardQueryLabels = selectedBoard && Array.isArray(selectedBoard.query_labels)
    ? selectedBoard.query_labels
    : [];
  const selectedBoardPapers = selectedBoard && Array.isArray(selectedBoard.papers)
    ? selectedBoard.papers
    : [];
  const selectedBoardAllGroups = selectedBoard
    ? buildQueryGroups(
      selectedBoardQueryLabels,
      selectedBoardPapers,
    )
    : [];
  const selectedBoardFilteredGroups = selectedBoard
    ? buildQueryGroups(
      selectedBoardQueryLabels,
      filterPaperList(selectedBoardPapers),
    ).filter(([, items]) => items.length > 0)
    : [];
  renderQueryDirectory(selectedBoardAllGroups);
  renderResearchThemes();
  renderSettingsView();
  renderLlmDiscoveryFeedback();
  renderSourceSelector();
  renderCcfFeedback();
  renderCcfStatus();
  renderThemeSwitcher();
  renderSortButton();
  renderViewChrome();

  if (activeList) {
    if (!state.researchThemes.length) {
      activeList.innerHTML = `<p class="empty-state">先添加一个研究主题。右侧会为每个主题单独生成一块论文看板。</p>`;
    } else if (!selectedBoard) {
      activeList.innerHTML = `<p class="empty-state">当前没有可展示的主题看板。</p>`;
    } else {
      const theme = selectedBoard.theme || {};
      const groupedPapers = sortPaperGroups(selectedBoardFilteredGroups);
      activeList.innerHTML = `
        <section class="theme-board">
          <header class="theme-board-head">
            <div>
              <h2>${escapeHtml(theme.name || "未命名主题")}</h2>
              <p>${escapeHtml(theme.description || "")}</p>
            </div>
            <span class="status-chip">${escapeHtml(String(selectedBoard.paper_count || 0))} 篇</span>
          </header>
          ${groupedPapers.length ? groupedPapers.map(([label, papers]) => `
            <section class="query-section" id="query-${encodeURIComponent(`${label}-${String(theme.id || "")}`)}">
              <header class="query-section-head">
                <h3>${escapeHtml(label)}</h3>
                <p>${papers.length} 篇论文</p>
              </header>
              <div class="paper-grid">
                ${papers.map(renderPaperCard).join("")}
              </div>
            </section>
          `).join("") : `<p class="empty-state">当前主题下的论文可能已经全部归档，或者暂时没有新的命中文献。如需获取新论文，请点击右上角“更新”。</p>`}
        </section>
      `;
    }
  }

  if (archiveList) {
    archiveList.innerHTML = state.archivedPapers.length
      ? state.archivedPapers.map(renderArchivedPaper).join("")
      : `<p class="empty-state">Archive 还是空的。你在主列表里点 Archive 后，论文会移动到这里。</p>`;
  }
}

function setRefreshStatus(text) {
  const el = document.getElementById("refresh-status");
  if (el) {
    el.textContent = text;
  }
}

function setRefreshProgress(percent) {
  const bar = document.getElementById("refresh-progress-bar");
  if (bar) {
    const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
    bar.style.width = `${safePercent}%`;
  }
}

function setQueryFeedback(text, isError = false) {
  const el = document.getElementById("query-feedback");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.style.color = text && isError ? "#b42318" : "";
}

function setThemeFeedback(text, isError = false) {
  const el = document.getElementById("theme-feedback");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.style.color = text && isError ? "#b42318" : "";
}

function selectTheme(themeId) {
  const nextThemeId = Number(themeId);
  if (!Number.isInteger(nextThemeId) || nextThemeId <= 0) {
    return;
  }
  if (Number(state.selectedThemeId) === nextThemeId) {
    return;
  }
  state.selectedThemeId = nextThemeId;
  state.filterMode = "all";
  state.expandedPaperKeys.clear();
  setQueryFeedback("");
  setThemeFeedback("");
  if (!state.refreshing) {
    setRefreshStatus(DEFAULT_REFRESH_STATUS);
    setRefreshProgress(0);
  }
  renderLists();
}

function loadStoredRefreshSources() {
  try {
    const raw = window.localStorage.getItem(SOURCE_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .map((item) => String(item || "").trim().toLowerCase())
      .filter(Boolean);
  } catch (error) {
    console.error("Failed to load stored refresh sources", error);
    return [];
  }
}

function persistRefreshSources(sources) {
  try {
    window.localStorage.setItem(SOURCE_STORAGE_KEY, JSON.stringify(sources));
  } catch (error) {
    console.error("Failed to persist refresh sources", error);
  }
}

function setSettingsFeedback(text, isError = false) {
  state.settingsFeedback = text;
  state.settingsFeedbackIsError = Boolean(text) && isError;
  const el = document.getElementById("settings-feedback");
  if (!el) {
    return;
  }
  el.textContent = text;
  el.style.color = state.settingsFeedbackIsError ? "#b42318" : "";
}

function setCcfFeedback(text, isError = false) {
  state.ccfFeedback = text;
  state.ccfFeedbackIsError = Boolean(text) && isError;
  renderCcfFeedback();
}

function setLlmDiscoveryFeedback(text, isError = false) {
  state.llmDiscoveryFeedback = text;
  state.llmDiscoveryFeedbackIsError = Boolean(text) && isError;
  renderLlmDiscoveryFeedback();
}

async function fetchSnapshot(options = {}) {
  const force = Boolean(options.force);
  if ((state.loading || state.refreshing) && !force) {
    return;
  }
  state.loading = true;
  try {
    const response = await fetch("/api/papers", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    applySnapshot(await response.json());
    renderLists();
  } catch (error) {
    console.error("Failed to fetch dashboard snapshot", error);
  } finally {
    state.loading = false;
  }
}

async function fetchSettings() {
  state.settingsLoading = true;
  try {
    const response = await fetch("/api/settings", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    applySettings(await response.json());
    renderLists();
  } catch (error) {
    console.error("Failed to fetch dashboard settings", error);
  } finally {
    state.settingsLoading = false;
  }
}

async function saveSettings(payload) {
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `HTTP ${response.status}`);
  }
  const data = await response.json();
  applySettings(data.settings || {});
  applySnapshot(data.snapshot || {});
  renderLists();
}

async function discoverLlmSettings(payload) {
  const response = await fetch("/api/settings/llm/discover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `HTTP ${response.status}`);
  }
  return response.json();
}

async function updateArchive(source, sourceId, archived) {
  const response = await fetch("/api/papers/archive", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, source_id: sourceId, archived }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  applySnapshot(await response.json());
  renderLists();
}

async function updateQueries(action, label) {
  if (!Number.isInteger(Number(state.selectedThemeId)) || Number(state.selectedThemeId) <= 0) {
    throw new Error("Theme selection is required");
  }
  const response = await fetch("/api/queries", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, label, theme_id: Number(state.selectedThemeId) }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  applySnapshot(await response.json());
  renderLists();
}

async function suggestQueries() {
  if (!Number.isInteger(Number(state.selectedThemeId)) || Number(state.selectedThemeId) <= 0) {
    throw new Error("Theme selection is required");
  }
  const response = await fetch("/api/queries/suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ theme_id: Number(state.selectedThemeId) }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const data = await response.json();
  applySnapshot(data.snapshot || {});
  renderLists();
  return {
    suggested: Array.isArray(data.suggested_queries) ? data.suggested_queries : [],
    added: Array.isArray(data.added_queries) ? data.added_queries : [],
  };
}

async function updateThemes(action, payload) {
  const response = await fetch("/api/themes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...payload }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  applySnapshot(await response.json());
  renderLists();
}

async function refreshCcfWhitelist() {
  const response = await fetch("/api/ccf/update", { method: "POST" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const data = await response.json();
  state.ccfVenueCount = Number(data.ccf_venue_count || 0);
  state.ccfLastUpdatedAt = data.ccf_last_updated_at || null;
  renderCcfStatus();
}

async function waitForRefreshToFinish() {
  while (true) {
    const response = await fetch("/api/refresh", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    if (!data.running) {
      if (data.last_error) {
        throw new Error(data.last_error);
      }
      setRefreshProgress(data.progress_percent || 100);
      if (data.message) {
        setRefreshStatus(data.message);
      }
      return;
    }
    setRefreshStatus(data.message || "正在刷新…");
    setRefreshProgress(data.progress_percent || 5);
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
  }
}

async function triggerRefresh() {
  if (state.refreshing) {
    return;
  }
  if (!state.selectedRefreshSources.length) {
    setRefreshStatus("请至少保留一个检索渠道，再点击更新。");
    setRefreshProgress(0);
    return;
  }
  state.refreshing = true;
  setRefreshStatus("正在检索当前主题下的关键词，并补齐摘要与贡献度…");
  setRefreshProgress(2);
  try {
    const response = await fetch("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        theme_id: Number.isInteger(Number(state.selectedThemeId)) && Number(state.selectedThemeId) > 0
          ? Number(state.selectedThemeId)
          : null,
        sources: state.selectedRefreshSources,
      }),
    });
    if (!response.ok && response.status !== 202) {
      throw new Error(`HTTP ${response.status}`);
    }
    await waitForRefreshToFinish();
    state.refreshing = false;
    await fetchSnapshot({ force: true });
    setRefreshStatus("刷新完成。");
    setRefreshProgress(100);
  } catch (error) {
    console.error("Failed to refresh dashboard data", error);
    setRefreshStatus("刷新失败，请查看启动 dashboard 的终端日志。");
    setRefreshProgress(0);
  } finally {
    state.refreshing = false;
  }
}

function initArchiveActions() {
  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const archiveAction = target.dataset.archiveAction;
    if (archiveAction) {
      const source = target.dataset.source;
      const sourceId = target.dataset.sourceId;
      if (!source || !sourceId) {
        return;
      }
      target.setAttribute("disabled", "disabled");
      try {
        await updateArchive(source, sourceId, archiveAction === "archive");
      } catch (error) {
        console.error("Failed to update archive state", error);
      } finally {
        target.removeAttribute("disabled");
      }
      return;
    }

    const summaryAction = target.dataset.summaryAction;
    if (summaryAction === "toggle") {
      const key = target.dataset.paperKey;
      if (!key) {
        return;
      }
      if (state.expandedPaperKeys.has(key)) {
        state.expandedPaperKeys.delete(key);
      } else {
        state.expandedPaperKeys.add(key);
      }
      renderLists();
    }
  });
}

function initQueryActions() {
  const form = document.getElementById("query-form");
  const input = document.getElementById("query-input");
  const suggestButton = document.getElementById("query-suggest-button");
  if (form instanceof HTMLFormElement && input instanceof HTMLInputElement) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const label = input.value.trim();
      if (!label) {
        setQueryFeedback("先输入一个新的检索关键词。", true);
        return;
      }
      if (!Number.isInteger(Number(state.selectedThemeId)) || Number(state.selectedThemeId) <= 0) {
        setQueryFeedback("先在左侧选中一个研究主题，再给它添加关键词。", true);
        return;
      }
      form.setAttribute("aria-busy", "true");
      try {
        await updateQueries("add", label);
        input.value = "";
        setQueryFeedback("目录已加入，下次点击刷新并更新时会参与检索。");
      } catch (error) {
        console.error("Failed to add query", error);
        setQueryFeedback("新增目录失败，请查看 dashboard 终端日志。", true);
      } finally {
        form.removeAttribute("aria-busy");
      }
    });
  }

  if (suggestButton instanceof HTMLButtonElement) {
    suggestButton.addEventListener("click", async () => {
      if (state.suggestingQueries) {
        return;
      }
      if (!Number.isInteger(Number(state.selectedThemeId)) || Number(state.selectedThemeId) <= 0) {
        setQueryFeedback("先在左侧选中一个研究主题，再让 AI 帮你生成关键词。", true);
        return;
      }
      state.suggestingQueries = true;
      suggestButton.setAttribute("disabled", "disabled");
      try {
        const result = await suggestQueries();
        if (result.added.length) {
          setQueryFeedback(`AI 已生成并加入 ${result.added.length} 个关键词：${result.added.join("；")}`);
        } else if (result.suggested.length) {
          setQueryFeedback("AI 已生成关键词，但这些词当前都已存在于目录中。");
        } else {
          setQueryFeedback("AI 这次没有生成可用关键词，可以稍后再试。", true);
        }
      } catch (error) {
        console.error("Failed to suggest queries", error);
        setQueryFeedback("AI 生成关键词失败，请查看 dashboard 终端日志。", true);
      } finally {
        state.suggestingQueries = false;
        suggestButton.removeAttribute("disabled");
      }
    });
  }

  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (target.dataset.queryAction !== "delete") {
      return;
    }
    const label = target.dataset.queryLabel;
    if (!label) {
      return;
    }
    target.setAttribute("disabled", "disabled");
    try {
      await updateQueries("delete", label);
      setQueryFeedback(`已删除目录 “${label}”，并归档当前主列表下这组论文。`);
    } catch (error) {
      console.error("Failed to delete query", error);
      setQueryFeedback("删除目录失败，请查看 dashboard 终端日志。", true);
    } finally {
      target.removeAttribute("disabled");
    }
  });
}

function initThemeActions() {
  const form = document.getElementById("theme-form");
  const nameInput = document.getElementById("theme-name-input");
  const descriptionInput = document.getElementById("theme-description-input");
  if (
    form instanceof HTMLFormElement
    && nameInput instanceof HTMLInputElement
    && descriptionInput instanceof HTMLTextAreaElement
  ) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = nameInput.value.trim();
      const description = descriptionInput.value.trim();
      if (!name) {
        setThemeFeedback("先给研究主题起一个名字。", true);
        return;
      }
        if (!description) {
          setThemeFeedback("再补一段主题描述，后面才好评估贡献度。", true);
          return;
        }
      form.setAttribute("aria-busy", "true");
      try {
        await updateThemes("create", { name, description });
        clearThemeForm();
        setThemeFeedback("研究主题已创建。需要继续修改时，可在主题卡片里点“编辑”。");
      } catch (error) {
        console.error("Failed to save theme", error);
        setThemeFeedback("保存研究主题失败，请查看 dashboard 终端日志。", true);
      } finally {
        form.removeAttribute("aria-busy");
      }
    });
  }

  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const selectTrigger = target.closest("[data-theme-select]");
    if (selectTrigger instanceof HTMLElement) {
      const selectId = Number(selectTrigger.dataset.themeSelect);
      if (Number.isInteger(selectId) && selectId > 0) {
        selectTheme(selectId);
        return;
      }
    }
    const actionTrigger = target.closest("[data-theme-action]");
    if (!(actionTrigger instanceof HTMLElement)) {
      return;
    }
    const action = actionTrigger.dataset.themeAction;
    if (!action) {
      return;
    }
    const themeId = Number(actionTrigger.dataset.themeId);
    if (!Number.isInteger(themeId) || themeId <= 0) {
      return;
    }
    if (action === "edit") {
      state.editingThemeId = themeId;
      renderLists();
      setThemeFeedback("请直接在当前主题卡片内修改内容，保存后会恢复成普通按钮。");
      return;
    }
    if (action === "cancel-inline") {
      state.editingThemeId = null;
      renderLists();
      setThemeFeedback("已取消编辑。");
      return;
    }
    if (action === "save-inline") {
      const themeCard = actionTrigger.closest(".theme-card");
      if (!(themeCard instanceof HTMLElement)) {
        return;
      }
      const nameInput = themeCard.querySelector(`[data-theme-edit-name="${String(themeId)}"]`);
      const descriptionInput = themeCard.querySelector(`[data-theme-edit-description="${String(themeId)}"]`);
      if (!(nameInput instanceof HTMLInputElement) || !(descriptionInput instanceof HTMLTextAreaElement)) {
        return;
      }
      const name = nameInput.value.trim();
      const description = descriptionInput.value.trim();
      if (!name) {
        setThemeFeedback("先给研究主题起一个名字。", true);
        return;
      }
      if (!description) {
        setThemeFeedback("再补一段主题描述，后面才好评估贡献度。", true);
        return;
      }
      actionTrigger.setAttribute("disabled", "disabled");
      try {
        await updateThemes("update", { theme_id: themeId, name, description });
        state.editingThemeId = null;
        renderLists();
        setThemeFeedback("当前研究主题已更新。");
      } catch (error) {
        console.error("Failed to save inline theme", error);
        setThemeFeedback("保存研究主题失败，请查看 dashboard 终端日志。", true);
      } finally {
        actionTrigger.removeAttribute("disabled");
      }
      return;
    }
    actionTrigger.setAttribute("disabled", "disabled");
    try {
      await updateThemes(action, { theme_id: themeId });
      if (action === "delete" && Number(state.editingThemeId) === themeId) {
        state.editingThemeId = null;
      }
      setThemeFeedback("研究主题已删除，对应看板也已移除。");
    } catch (error) {
      console.error("Failed to update theme", error);
      setThemeFeedback("研究主题操作失败，请查看 dashboard 终端日志。", true);
    } finally {
      actionTrigger.removeAttribute("disabled");
    }
  });
}

function initRefreshButton() {
  const button = document.getElementById("refresh-button");
  if (!button) {
    return;
  }
  button.addEventListener("click", () => {
    void triggerRefresh();
  });
}

function initViewToggle() {
  const button = document.getElementById("view-toggle-button");
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }
  button.addEventListener("click", () => {
    state.currentView = state.currentView === "settings" ? "papers" : "settings";
    if (state.currentView === "settings" && !state.settingsLoading && state.settings === null) {
      void fetchSettings();
    }
    renderLists();
  });
}

function buildSettingsPayload(form) {
  const formData = new FormData(form);
  const sourceValues = formData.getAll("search_sources").map((value) => String(value).trim().toLowerCase()).filter(Boolean);
  const rankValues = formData.getAll("search_ccf_ranks").map((value) => String(value).trim().toUpperCase()).filter(Boolean);
  return {
    llm: {
      enabled: form.querySelector('input[name="llm_enabled"]')?.checked === true,
      provider: String(state.settings?.llm?.provider || "openai-compat").trim() || "openai-compat",
      base_url: String(formData.get("llm_base_url") || "").trim(),
      model: String(formData.get("llm_model") || "").trim(),
      target_lang: String(formData.get("llm_target_lang") || "").trim(),
      api_key: String(formData.get("llm_api_key") || "").trim(),
      enable_translation: form.querySelector('input[name="llm_enable_translation"]')?.checked === true,
      enable_summary: form.querySelector('input[name="llm_enable_summary"]')?.checked === true,
    },
    search: {
      sources: sourceValues,
      ccf_enabled: form.querySelector('input[name="search_ccf_enabled"]')?.checked === true,
      ccf_ranks: rankValues,
      arxiv_min_interval_seconds: Number(formData.get("search_arxiv_interval") || 5),
      ncbi_api_key: String(formData.get("search_ncbi_api_key") || "").trim(),
    },
  };
}

function initSettingsActions() {
  document.addEventListener("submit", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLFormElement) || target.id !== "settings-form") {
      return;
    }
    event.preventDefault();
    if (state.settingsSaving) {
      return;
    }
    const payload = buildSettingsPayload(target);
    state.settingsSaving = true;
    setSettingsFeedback("正在保存设置…");
    renderSettingsView();
    try {
      await saveSettings(payload);
      setSettingsFeedback("设置已保存，后续更新会按新配置执行。");
    } catch (error) {
      console.error("Failed to save dashboard settings", error);
      setSettingsFeedback("保存失败，请检查设置内容是否完整。", true);
    } finally {
      state.settingsSaving = false;
      renderSettingsView();
    }
  });

  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement) || target.id !== "llm-discovery-button") {
      return;
    }
    const form = target.closest("form");
    if (!(form instanceof HTMLFormElement) || form.id !== "settings-form") {
      return;
    }
    if (state.llmDiscoveryRunning) {
      return;
    }
    const baseUrlInput = form.querySelector('input[name="llm_base_url"]');
    const apiKeyInput = form.querySelector('input[name="llm_api_key"]');
    const modelInput = form.querySelector('select[name="llm_model"]');
    if (!(baseUrlInput instanceof HTMLInputElement) || !(apiKeyInput instanceof HTMLInputElement)) {
      return;
    }
    const baseUrl = baseUrlInput.value.trim();
    const apiKey = apiKeyInput.value.trim();
    if (!baseUrl || !apiKey) {
      setLlmDiscoveryFeedback("请先填写 Base URL 和 API Key。", true);
      return;
    }
    state.llmDiscoveryRunning = true;
    state.llmDiscoveredModels = [];
    renderLlmDiscoveredModels();
    if (target instanceof HTMLButtonElement) {
      target.disabled = true;
      target.textContent = "检测中…";
    }
    setLlmDiscoveryFeedback("正在检测可用 provider 和 model…");
    try {
      const data = await discoverLlmSettings({ base_url: baseUrl, api_key: apiKey });
      const models = Array.isArray(data.models)
        ? data.models.map((item) => String(item || "").trim()).filter(Boolean)
        : [];
      state.llmDiscoveredModels = models;
      if (modelInput instanceof HTMLSelectElement && models.length) {
        modelInput.innerHTML = renderModelOptions(models[0]);
        modelInput.value = models[0];
      }
      setLlmDiscoveryFeedback(
        models.length
          ? `已检测到 ${models.length} 个模型，并自动填入默认 model。`
          : "接口已连通，但没有返回可用模型列表。"
      );
    } catch (error) {
      console.error("Failed to discover LLM settings", error);
      state.llmDiscoveredModels = [];
      setLlmDiscoveryFeedback("检测失败，请检查 URL、API Key 或服务兼容性。", true);
    } finally {
      state.llmDiscoveryRunning = false;
      if (target instanceof HTMLButtonElement) {
        target.disabled = false;
        target.textContent = "检测并加载";
      }
    }
  });
}

function initSortButton() {
  const button = document.getElementById("sort-button");
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }
  button.addEventListener("click", () => {
    state.sortMode = state.sortMode === "contribution" ? "default" : "contribution";
    renderLists();
  });
}

function initCcfButton() {
  document.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement) || target.id !== "ccf-refresh-button") {
      return;
    }
    target.setAttribute("disabled", "disabled");
    setCcfFeedback("正在刷新本地 CCF 白名单缓存…");
    try {
      await refreshCcfWhitelist();
      setCcfFeedback("CCF 白名单已更新到本地缓存。下次刷新并更新时会立即生效。");
    } catch (error) {
      console.error("Failed to refresh CCF whitelist", error);
      setCcfFeedback("更新 CCF 白名单失败，请查看 dashboard 终端日志。", true);
    } finally {
      target.removeAttribute("disabled");
    }
  });
}

function initFilters() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const trigger = target.closest("[data-filter-mode]");
    if (!(trigger instanceof HTMLElement)) {
      return;
    }
    const mode = String(trigger.dataset.filterMode || "all");
    state.filterMode = mode;
    renderLists();
  });
}

function initSourceSelector() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const trigger = target.closest("[data-source-toggle]");
    if (!(trigger instanceof HTMLElement)) {
      return;
    }
    const sourceName = String(trigger.dataset.sourceToggle || "").trim().toLowerCase();
    if (!sourceName) {
      return;
    }
    if (state.selectedRefreshSources.includes(sourceName)) {
      if (state.selectedRefreshSources.length === 1) {
        setRefreshStatus("请至少保留一个检索渠道。");
        setRefreshProgress(0);
        return;
      }
      state.selectedRefreshSources = state.selectedRefreshSources.filter((item) => item !== sourceName);
    } else if (state.availableRefreshSources.includes(sourceName)) {
      state.selectedRefreshSources = [...state.selectedRefreshSources, sourceName];
    }
    persistRefreshSources(state.selectedRefreshSources);
    renderSourceSelector();
  });
}

function initPolling() {
  const seconds = Number(window.DASHBOARD_CONFIG?.autoRefreshSeconds || 30);
  window.setInterval(() => {
    void fetchSnapshot();
  }, Math.max(seconds, 5) * 1000);
}

document.addEventListener("DOMContentLoaded", () => {
  initArchiveActions();
  initQueryActions();
  initThemeActions();
  initViewToggle();
  initSettingsActions();
  initRefreshButton();
  initSortButton();
  initCcfButton();
  initFilters();
  initSourceSelector();
  initPolling();
  setRefreshStatus(DEFAULT_REFRESH_STATUS);
  void fetchSnapshot();
  void fetchSettings();
});
