"use strict";

const DEFAULT_REFRESH_STATUS = "只会刷新当前选中的研究主题，并按这个主题下的关键词去检索、补齐摘要与贡献度。";
const SOURCE_LABELS = { dblp: "DBLP", openreview: "OpenReview", arxiv: "arXiv", openalex: "OpenAlex" };
const SOURCE_STORAGE_KEY = "paper-tracker-dashboard-sources";
const TARGET_LANGUAGE_OPTIONS = ["Simplified Chinese", "Traditional Chinese", "English", "Japanese", "Korean"];

Vue.createApp({
  data() {
    return {
      activePapers: [],
      archivedPapers: [],
      queryLabels: [],
      researchThemes: [],
      themeBoards: [],
      selectedThemeId: null,
      expandedPaperKeys: new Set(),
      filterMode: "all",
      sortMode: "default",

      refreshStatus: DEFAULT_REFRESH_STATUS,
      refreshProgress: 0,
      refreshing: false,
      loading: false,
      availableRefreshSources: [],
      selectedRefreshSources: [],

      ccfVenueCount: 0,
      ccfLastUpdatedAt: null,
      updatedAt: null,
      ccfFeedback: "",
      ccfFeedbackIsError: false,

      currentView: "papers",

      themeForm: { name: "", description: "" },
      themeFeedback: "",
      themeFeedbackIsError: false,
      editingThemeId: null,
      themeEditForm: { name: "", description: "" },

      queryInput: "",
      queryFeedback: "",
      queryFeedbackIsError: false,
      suggestingQueries: false,

      settings: null,
      settingsLoading: false,
      settingsSaving: false,
      settingsFeedback: "",
      settingsFeedbackIsError: false,
      settingsForm: {
        llm_enabled: false,
        llm_base_url: "",
        llm_api_key: "",
        llm_model: "",
        llm_target_lang: "Simplified Chinese",
        llm_enable_translation: false,
        llm_enable_summary: false,
        search_ccf_enabled: false,
        search_sources: [],
        search_ccf_ranks: [],
        search_arxiv_interval: 5,
      },

      llmDiscoveredModels: [],
      llmDiscoveryRunning: false,
      llmDiscoveryFeedback: "",
      llmDiscoveryFeedbackIsError: false,
    };
  },

  computed: {
    selectedBoard() {
      return this.themeBoards.find(
        (b) => Number(b?.theme?.id) === Number(this.selectedThemeId)
      ) || null;
    },
    selectedBoardPapers() {
      return this.selectedBoard?.papers || [];
    },
    selectedBoardQueryLabels() {
      return this.selectedBoard?.query_labels || [];
    },
    selectedBoardAllGroups() {
      return this._buildQueryGroups(this.selectedBoardQueryLabels, this.selectedBoardPapers);
    },
    filteredPapers() {
      return this._filterByMode(this.selectedBoardPapers, this.filterMode);
    },
    selectedBoardFilteredGroups() {
      return this._buildQueryGroups(this.selectedBoardQueryLabels, this.filteredPapers)
        .filter(([, items]) => items.length > 0);
    },
    sortedGroupedPapers() {
      return this._sortGroups(this.selectedBoardFilteredGroups);
    },
    filterChips() {
      return [
        { mode: "all",  label: "📚 全部",  count: this._filterByMode(this.selectedBoardPapers, "all").length },
        { mode: "arxiv", label: "🗂️ arXiv", count: this._filterByMode(this.selectedBoardPapers, "arxiv").length },
        { mode: "ccfA", label: "🎤 CCF-A", count: this._filterByMode(this.selectedBoardPapers, "ccfA").length },
        { mode: "ccfB", label: "📘 CCF-B", count: this._filterByMode(this.selectedBoardPapers, "ccfB").length },
      ];
    },
    supportedSources() {
      return Array.isArray(this.settings?.search?.supported_sources)
        ? this.settings.search.supported_sources
        : [];
    },
    ccfStatus() {
      const timeText = this.ccfLastUpdatedAt
        ? `上次写入 ${this.ccfLastUpdatedAt}`
        : "还没有本地缓存时间";
      return `当前缓存 ${this.ccfVenueCount} 个 CCF venue。${timeText}。`;
    },
    targetLanguageOptions() {
      return TARGET_LANGUAGE_OPTIONS;
    },
    modelSelectOptions() {
      const models = this.llmDiscoveredModels;
      const current = this.settingsForm.llm_model;
      if (!models.length) return current ? [current] : [];
      const seen = new Set(models);
      return current && !seen.has(current) ? [current, ...models] : [...models];
    },
    extendedTargetLanguageOptions() {
      const options = TARGET_LANGUAGE_OPTIONS;
      const current = this.settingsForm.llm_target_lang;
      return current && !options.includes(current) ? [current, ...options] : options;
    },
  },

  methods: {
    paperKey(paper) {
      return `${paper.source || "unknown"}::${paper.source_id || paper.title || ""}`;
    },

    sourceLabel(name) {
      return SOURCE_LABELS[String(name || "").toLowerCase()] || String(name || "").toUpperCase();
    },

    encodeQueryId(label) {
      return encodeURIComponent(`${label}-${this.selectedThemeId || ""}`);
    },

    autoGrow(el) {
      if (!el) return;
      el.style.height = "auto";
      el.style.height = el.scrollHeight + "px";
    },

    getThemeBoard(themeId) {
      return this.themeBoards.find((b) => Number(b?.theme?.id) === Number(themeId)) || null;
    },

    _filterByMode(papers, mode) {
      if (mode === "all") return papers;
      return papers.filter((paper) => {
        if (mode.startsWith("label:")) return (paper.matched_query || "") === mode.slice(6);
        if (mode === "arxiv") return String(paper.source || "").toLowerCase() === "arxiv";
        if (mode === "ccfA") return paper.ccf_rank === "CCF-A";
        if (mode === "ccfB") return paper.ccf_rank === "CCF-B";
        return true;
      });
    },

    _buildQueryGroups(queryLabels, papers) {
      const groups = new Map();
      (queryLabels || []).forEach((label) => groups.set(label, []));
      (papers || []).forEach((paper) => {
        const label = paper.matched_query || "Unlabeled";
        if (!groups.has(label)) groups.set(label, []);
        groups.get(label).push(paper);
      });
      return Array.from(groups.entries());
    },

    _sortGroups(groups) {
      if (this.sortMode !== "contribution") return groups;
      const score = (p) => {
        const s = Number(p?.theme_contribution_score);
        return Number.isFinite(s) ? s : -1;
      };
      return groups
        .map(([label, papers]) => [label, [...papers].sort((a, b) => score(b) - score(a))])
        .sort((a, b) => {
          const aTop = a[1].length ? score(a[1][0]) : -1;
          const bTop = b[1].length ? score(b[1][0]) : -1;
          return bTop - aTop;
        });
    },

    applySnapshot(data) {
      this.activePapers = Array.isArray(data.active_papers) ? data.active_papers : [];
      this.archivedPapers = Array.isArray(data.archived_papers) ? data.archived_papers : [];
      this.queryLabels = Array.isArray(data.query_labels) ? data.query_labels : [];
      this.researchThemes = Array.isArray(data.research_themes) ? data.research_themes : [];
      this.themeBoards = Array.isArray(data.theme_boards) ? data.theme_boards : [];

      const validThemeIds = new Set(
        this.themeBoards
          .map((b) => Number(b?.theme?.id))
          .filter((v) => Number.isInteger(v) && v > 0)
      );
      if (!validThemeIds.has(Number(this.selectedThemeId))) {
        this.selectedThemeId = this.themeBoards.length
          ? Number(this.themeBoards[0].theme.id)
          : null;
      }

      const selectedBoard = this.selectedBoard;
      const selectedQueryLabels = Array.isArray(selectedBoard?.query_labels)
        ? selectedBoard.query_labels
        : [];
      if (
        !selectedBoard ||
        (this.filterMode.startsWith("label:") &&
          !selectedQueryLabels.includes(this.filterMode.slice(6)))
      ) {
        this.filterMode = "all";
      }

      this.ccfVenueCount = Number(data.ccf_venue_count || 0);
      this.ccfLastUpdatedAt = data.ccf_last_updated_at || null;
      this.updatedAt = data.updated_at || null;

      this.availableRefreshSources = Array.isArray(data.available_refresh_sources)
        ? data.available_refresh_sources.map((s) => String(s || "").trim().toLowerCase()).filter(Boolean)
        : [];
      const defaultSources = Array.isArray(data.default_refresh_sources)
        ? data.default_refresh_sources.map((s) => String(s || "").trim().toLowerCase()).filter(Boolean)
        : [];
      const storedSources = this.loadStoredRefreshSources();
      const currentSources = this.selectedRefreshSources.length
        ? this.selectedRefreshSources
        : storedSources.length
          ? storedSources
          : defaultSources;
      const allowed = new Set(this.availableRefreshSources);
      const next = currentSources.filter((s) => allowed.has(s));
      this.selectedRefreshSources = next.length
        ? next
        : defaultSources.filter((s) => allowed.has(s));
      this.persistRefreshSources(this.selectedRefreshSources);
    },

    applySettings(data) {
      if (!data || typeof data !== "object") return;
      this.settings = { llm: data.llm || {}, search: data.search || {} };
      const llm = data.llm || {};
      const search = data.search || {};
      this.settingsForm = {
        llm_enabled: Boolean(llm.enabled),
        llm_base_url: String(llm.base_url || ""),
        llm_api_key: String(llm.api_key || ""),
        llm_model: String(llm.model || ""),
        llm_target_lang: String(llm.target_lang || "Simplified Chinese"),
        llm_enable_translation: Boolean(llm.enable_translation),
        llm_enable_summary: Boolean(llm.enable_summary),
        search_ccf_enabled: Boolean(search.ccf_enabled),
        search_sources: Array.isArray(search.sources) ? [...search.sources] : [],
        search_ccf_ranks: Array.isArray(search.ccf_ranks) ? [...search.ccf_ranks] : [],
        search_arxiv_interval: Number(search.arxiv_min_interval_seconds ?? 5),
      };
    },

    buildSettingsPayload() {
      const f = this.settingsForm;
      return {
        llm: {
          enabled: f.llm_enabled,
          provider: String(this.settings?.llm?.provider || "openai-compat").trim() || "openai-compat",
          base_url: f.llm_base_url.trim(),
          model: f.llm_model.trim(),
          target_lang: f.llm_target_lang.trim(),
          api_key: f.llm_api_key.trim(),
          enable_translation: f.llm_enable_translation,
          enable_summary: f.llm_enable_summary,
        },
        search: {
          sources: f.search_sources.map((s) => String(s).trim().toLowerCase()).filter(Boolean),
          ccf_enabled: f.search_ccf_enabled,
          ccf_ranks: f.search_ccf_ranks.map((r) => String(r).trim().toUpperCase()).filter(Boolean),
          arxiv_min_interval_seconds: Number(f.search_arxiv_interval || 5),
        },
      };
    },

    loadStoredRefreshSources() {
      try {
        const raw = window.localStorage.getItem(SOURCE_STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed.map((s) => String(s || "").trim().toLowerCase()).filter(Boolean);
      } catch {
        return [];
      }
    },

    persistRefreshSources(sources) {
      try {
        window.localStorage.setItem(SOURCE_STORAGE_KEY, JSON.stringify(sources));
      } catch {
        // ignore
      }
    },

    async fetchSnapshot(options = {}) {
      if ((this.loading || this.refreshing) && !options.force) return;
      this.loading = true;
      try {
        const resp = await fetch("/api/papers", { cache: "no-store" });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        this.applySnapshot(await resp.json());
      } catch (err) {
        console.error("Failed to fetch dashboard snapshot", err);
      } finally {
        this.loading = false;
      }
    },

    async fetchSettings() {
      this.settingsLoading = true;
      try {
        const resp = await fetch("/api/settings", { cache: "no-store" });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        this.applySettings(await resp.json());
      } catch (err) {
        console.error("Failed to fetch dashboard settings", err);
      } finally {
        this.settingsLoading = false;
      }
    },

    async saveSettingsAction() {
      if (this.settingsSaving) return;
      const payload = this.buildSettingsPayload();
      this.settingsSaving = true;
      this.settingsFeedback = "正在保存设置…";
      this.settingsFeedbackIsError = false;
      try {
        const resp = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) {
          const errorText = await resp.text();
          throw new Error(errorText || `HTTP ${resp.status}`);
        }
        const data = await resp.json();
        this.applySettings(data.settings || {});
        this.applySnapshot(data.snapshot || {});
        const newSources = Array.isArray(payload.search?.sources) ? payload.search.sources : [];
        if (newSources.length) {
          this.selectedRefreshSources = newSources;
          this.persistRefreshSources(newSources);
        }
        this.settingsFeedback = "设置已保存，后续更新会按新配置执行。";
        this.settingsFeedbackIsError = false;
      } catch (err) {
        console.error("Failed to save dashboard settings", err);
        this.settingsFeedback = "保存失败，请检查设置内容是否完整。";
        this.settingsFeedbackIsError = true;
      } finally {
        this.settingsSaving = false;
      }
    },

    async discoverLlmModels() {
      if (this.llmDiscoveryRunning) return;
      const baseUrl = this.settingsForm.llm_base_url.trim();
      const apiKey = this.settingsForm.llm_api_key.trim();
      if (!baseUrl) {
        this.llmDiscoveryFeedback = "请先填写 Base URL。";
        this.llmDiscoveryFeedbackIsError = true;
        return;
      }
      if (!apiKey) {
        this.llmDiscoveryFeedback = "请先填写 API Key。";
        this.llmDiscoveryFeedbackIsError = true;
        return;
      }
      this.llmDiscoveryRunning = true;
      this.llmDiscoveryFeedback = "正在连接，请稍候…";
      this.llmDiscoveryFeedbackIsError = false;
      try {
        const resp = await fetch("/api/settings/llm/discover", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
        const models = Array.isArray(data.models)
          ? data.models.map((m) => String(m || "").trim()).filter(Boolean)
          : [];
        this.llmDiscoveredModels = models;
        if (models.length && !this.settingsForm.llm_model) {
          this.settingsForm.llm_model = models[0];
        }
        this.llmDiscoveryFeedback = models.length
          ? `✓ 检测通过，共找到 ${models.length} 个可用模型。`
          : "已连通，但接口未返回模型列表，请手动填写模型名。";
        this.llmDiscoveryFeedbackIsError = false;
      } catch (err) {
        console.error("LLM discovery failed", err);
        this.llmDiscoveredModels = [];
        this.llmDiscoveryFeedback = `✗ ${err instanceof Error ? err.message : String(err)}`;
        this.llmDiscoveryFeedbackIsError = true;
      } finally {
        this.llmDiscoveryRunning = false;
      }
    },

    async archivePaper(paper) {
      try {
        const resp = await fetch("/api/papers/archive", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source: paper.source, source_id: paper.source_id, archived: true }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        this.applySnapshot(await resp.json());
      } catch (err) {
        console.error("Failed to archive paper", err);
      }
    },

    async restorePaper(paper) {
      try {
        const resp = await fetch("/api/papers/archive", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source: paper.source, source_id: paper.source_id, archived: false }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        this.applySnapshot(await resp.json());
      } catch (err) {
        console.error("Failed to restore paper", err);
      }
    },

    async addQuery() {
      const label = this.queryInput.trim();
      if (!label) {
        this.queryFeedback = "先输入一个新的检索关键词。";
        this.queryFeedbackIsError = true;
        return;
      }
      if (!Number.isInteger(Number(this.selectedThemeId)) || Number(this.selectedThemeId) <= 0) {
        this.queryFeedback = "先在左侧选中一个研究主题，再给它添加关键词。";
        this.queryFeedbackIsError = true;
        return;
      }
      try {
        const resp = await fetch("/api/queries", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "add", label, theme_id: Number(this.selectedThemeId) }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        this.applySnapshot(await resp.json());
        this.queryInput = "";
        this.queryFeedback = "目录已加入，下次点击刷新并更新时会参与检索。";
        this.queryFeedbackIsError = false;
      } catch (err) {
        console.error("Failed to add query", err);
        this.queryFeedback = "新增目录失败，请查看 dashboard 终端日志。";
        this.queryFeedbackIsError = true;
      }
    },

    async deleteQuery(label) {
      try {
        const resp = await fetch("/api/queries", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "delete", label, theme_id: Number(this.selectedThemeId) }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        this.applySnapshot(await resp.json());
        this.queryFeedback = `已删除目录 "${label}"，并归档当前主列表下这组论文。`;
        this.queryFeedbackIsError = false;
      } catch (err) {
        console.error("Failed to delete query", err);
        this.queryFeedback = "删除目录失败，请查看 dashboard 终端日志。";
        this.queryFeedbackIsError = true;
      }
    },

    async suggestQueriesAction() {
      if (this.suggestingQueries) return;
      if (!Number.isInteger(Number(this.selectedThemeId)) || Number(this.selectedThemeId) <= 0) {
        this.queryFeedback = "先在左侧选中一个研究主题，再让 AI 帮你生成关键词。";
        this.queryFeedbackIsError = true;
        return;
      }
      this.suggestingQueries = true;
      try {
        const resp = await fetch("/api/queries/suggest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ theme_id: Number(this.selectedThemeId) }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        this.applySnapshot(data.snapshot || {});
        const added = Array.isArray(data.added_queries) ? data.added_queries : [];
        const optimized = Array.isArray(data.optimized_queries) ? data.optimized_queries : [];
        const suggested = Array.isArray(data.suggested_queries) ? data.suggested_queries : [];
        const parts = [];
        if (added.length) parts.push(`新增 ${added.length} 个关键词：${added.join("；")}`);
        if (optimized.length) {
          const desc = optimized.map((o) => `"${o.from}" → "${o.to}"`).join("；");
          parts.push(`优化 ${optimized.length} 个关键词：${desc}`);
        }
        if (parts.length) {
          this.queryFeedback = `AI 已完成：${parts.join("；")}`;
        } else if (suggested.length) {
          this.queryFeedback = "AI 已分析关键词，当前所有生成词已存在，无需新增。";
        } else {
          this.queryFeedback = "AI 这次没有生成可用关键词，可以稍后再试。";
          this.queryFeedbackIsError = true;
        }
        this.queryFeedbackIsError = false;
      } catch (err) {
        console.error("Failed to suggest queries", err);
        this.queryFeedback = "AI 生成关键词失败，请查看 dashboard 终端日志。";
        this.queryFeedbackIsError = true;
      } finally {
        this.suggestingQueries = false;
      }
    },

    async createTheme() {
      const name = this.themeForm.name.trim();
      const description = this.themeForm.description.trim();
      if (!name) {
        this.themeFeedback = "先给研究主题起一个名字。";
        this.themeFeedbackIsError = true;
        return;
      }
      if (!description) {
        this.themeFeedback = "再补一段主题描述，后面才好评估贡献度。";
        this.themeFeedbackIsError = true;
        return;
      }
      try {
        const resp = await fetch("/api/themes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "create", name, description }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        this.applySnapshot(await resp.json());
        this.themeForm = { name: "", description: "" };
        this.themeFeedback = '研究主题已创建。需要继续修改时，可在主题卡片里点"编辑"。';
        this.themeFeedbackIsError = false;
      } catch (err) {
        console.error("Failed to create theme", err);
        this.themeFeedback = "保存研究主题失败，请查看 dashboard 终端日志。";
        this.themeFeedbackIsError = true;
      }
    },

    startEditTheme(themeId) {
      const theme = this.researchThemes.find((t) => Number(t.id) === Number(themeId));
      if (!theme) return;
      this.editingThemeId = Number(themeId);
      this.themeEditForm = { name: theme.name, description: theme.description || "" };
      this.themeFeedback = "请直接在当前主题卡片内修改内容，保存后会恢复成普通按钮。";
      this.themeFeedbackIsError = false;
      this.$nextTick(() => {
        const textarea = this.$el.querySelector(".theme-inline-textarea");
        if (textarea) this.autoGrow(textarea);
      });
    },

    cancelInlineTheme() {
      this.editingThemeId = null;
      this.themeFeedback = "已取消编辑。";
      this.themeFeedbackIsError = false;
    },

    async saveInlineTheme(themeId) {
      const name = this.themeEditForm.name.trim();
      const description = this.themeEditForm.description.trim();
      if (!name) {
        this.themeFeedback = "先给研究主题起一个名字。";
        this.themeFeedbackIsError = true;
        return;
      }
      if (!description) {
        this.themeFeedback = "再补一段主题描述，后面才好评估贡献度。";
        this.themeFeedbackIsError = true;
        return;
      }
      try {
        const resp = await fetch("/api/themes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "update", theme_id: Number(themeId), name, description }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        this.applySnapshot(await resp.json());
        this.editingThemeId = null;
        this.themeFeedback = "当前研究主题已更新。";
        this.themeFeedbackIsError = false;
      } catch (err) {
        console.error("Failed to save inline theme", err);
        this.themeFeedback = "保存研究主题失败，请查看 dashboard 终端日志。";
        this.themeFeedbackIsError = true;
      }
    },

    async deleteTheme(themeId) {
      try {
        const resp = await fetch("/api/themes", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "delete", theme_id: Number(themeId) }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        this.applySnapshot(await resp.json());
        if (Number(this.editingThemeId) === Number(themeId)) this.editingThemeId = null;
        this.themeFeedback = "研究主题已删除，对应看板也已移除。";
        this.themeFeedbackIsError = false;
      } catch (err) {
        console.error("Failed to delete theme", err);
        this.themeFeedback = "研究主题操作失败，请查看 dashboard 终端日志。";
        this.themeFeedbackIsError = true;
      }
    },

    selectTheme(themeId) {
      const next = Number(themeId);
      if (!Number.isInteger(next) || next <= 0 || Number(this.selectedThemeId) === next) return;
      this.selectedThemeId = next;
      this.filterMode = "all";
      this.expandedPaperKeys = new Set();
      this.queryFeedback = "";
      this.queryFeedbackIsError = false;
      this.themeFeedback = "";
      this.themeFeedbackIsError = false;
      if (!this.refreshing) {
        this.refreshStatus = DEFAULT_REFRESH_STATUS;
        this.refreshProgress = 0;
      }
    },

    togglePaperExpanded(key) {
      if (this.expandedPaperKeys.has(key)) {
        this.expandedPaperKeys.delete(key);
      } else {
        this.expandedPaperKeys.add(key);
      }
    },

    toggleView() {
      this.currentView = this.currentView === "settings" ? "papers" : "settings";
      if (this.currentView === "settings" && !this.settingsLoading && this.settings === null) {
        this.fetchSettings();
      }
    },

    toggleSort() {
      this.sortMode = this.sortMode === "contribution" ? "default" : "contribution";
    },

    toggleRefreshSource(sourceName) {
      if (this.selectedRefreshSources.includes(sourceName)) {
        if (this.selectedRefreshSources.length === 1) {
          this.refreshStatus = "请至少保留一个检索渠道。";
          this.refreshProgress = 0;
          return;
        }
        this.selectedRefreshSources = this.selectedRefreshSources.filter((s) => s !== sourceName);
      } else if (this.availableRefreshSources.includes(sourceName)) {
        this.selectedRefreshSources = [...this.selectedRefreshSources, sourceName];
      }
      this.persistRefreshSources(this.selectedRefreshSources);
    },

    async triggerRefresh() {
      if (this.refreshing) return;
      if (!this.selectedRefreshSources.length) {
        this.refreshStatus = "请至少保留一个检索渠道，再点击更新。";
        this.refreshProgress = 0;
        return;
      }
      this.refreshing = true;
      this.refreshStatus = "正在检索当前主题下的关键词，并补齐摘要与贡献度…";
      this.refreshProgress = 2;
      try {
        const resp = await fetch("/api/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            theme_id: Number.isInteger(Number(this.selectedThemeId)) && Number(this.selectedThemeId) > 0
              ? Number(this.selectedThemeId)
              : null,
            sources: this.selectedRefreshSources,
          }),
        });
        if (!resp.ok && resp.status !== 202) throw new Error(`HTTP ${resp.status}`);
        await this._waitForRefreshToFinish();
        this.refreshing = false;
        await this.fetchSnapshot({ force: true });
        this.refreshStatus = "刷新完成。";
        this.refreshProgress = 100;
      } catch (err) {
        console.error("Failed to refresh dashboard data", err);
        this.refreshStatus = "刷新失败，请查看启动 dashboard 的终端日志。";
        this.refreshProgress = 0;
      } finally {
        this.refreshing = false;
      }
    },

    async _waitForRefreshToFinish() {
      while (true) {
        const resp = await fetch("/api/refresh", { cache: "no-store" });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!data.running) {
          if (data.last_error) throw new Error(data.last_error);
          this.refreshProgress = data.progress_percent || 100;
          if (data.message) this.refreshStatus = data.message;
          return;
        }
        this.refreshStatus = data.message || "正在刷新…";
        this.refreshProgress = data.progress_percent || 5;
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
    },

    async refreshCcfWhitelist() {
      this.ccfFeedback = "正在刷新本地 CCF 白名单缓存…";
      this.ccfFeedbackIsError = false;
      try {
        const resp = await fetch("/api/ccf/update", { method: "POST" });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        this.ccfVenueCount = Number(data.ccf_venue_count || 0);
        this.ccfLastUpdatedAt = data.ccf_last_updated_at || null;
        this.ccfFeedback = "CCF 白名单已更新到本地缓存。下次刷新并更新时会立即生效。";
        this.ccfFeedbackIsError = false;
      } catch (err) {
        console.error("Failed to refresh CCF whitelist", err);
        this.ccfFeedback = "更新 CCF 白名单失败，请查看 dashboard 终端日志。";
        this.ccfFeedbackIsError = true;
      }
    },

    _initPolling() {
      const seconds = Number(window.DASHBOARD_CONFIG?.autoRefreshSeconds || 30);
      window.setInterval(() => {
        this.fetchSnapshot();
      }, Math.max(seconds, 5) * 1000);
    },
  },

  mounted() {
    this.fetchSnapshot();
    this.fetchSettings();
    this._initPolling();
  },
}).mount("#app");
