# Paper Tracker

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)](https://github.com/CheneyNine/PaperTracker/releases)
[![Last Commit](https://img.shields.io/github/last-commit/CheneyNine/PaperTracker)](https://github.com/CheneyNine/PaperTracker/commits)
[![Code Size](https://img.shields.io/github/languages/code-size/CheneyNine/PaperTracker)](https://github.com/CheneyNine/PaperTracker)

**[English](./README.en.md) | 中文**

Paper Tracker 是一个最小化的论文追踪工具，支持从 arXiv、OpenAlex、DBLP、OpenReview 多个来源检索论文，结合 CCF 等级过滤和 LLM 摘要增强，按配置输出结构化结果，便于持续追踪领域最新进展。

**如果该项目对你有帮助，请麻烦点一个 Star ⭐，谢谢！**

## 效果展示

![Dashboard 预览](./docs/assets/preview_dashboard.png)

![设置页面预览](./docs/assets/preview_setting.png)

## 功能概览

### 数据源

支持 4 个数据源，可在配置中同时启用：

| 数据源 | 数据类型 | query 字段支持 | 本地精筛 | CCF 过滤 | 跨源去重 |
|--------|----------|:--------------:|:--------:|:--------:|:--------:|
| `arxiv` | 预印本 | 完整 | — | — | ✅ |
| `openalex` | 期刊 / 会议 / 预印本 | 部分 | ✅ | — | ✅ |
| `dblp` | CCF 会议论文集 | 本地关键词匹配 | ✅ | ✅ | ✅ |
| `openreview` | CCF 会议投稿 | 本地关键词匹配 | ✅ | ✅ | ✅ |

> **openalex 注意**：结果稳定性尚在改善中，可能返回少量无关论文，如结果偏差明显建议暂时关闭。
>
> **dblp / openreview**：依赖 CCF 白名单（`ccf_enabled: true`），仅拉取 CCF A/B 级会议/期刊的近期论文，再按关键词过滤。

### 检索与过滤

- 支持字段化检索：`TITLE`、`ABSTRACT`、`AUTHOR`、`JOURNAL`、`CATEGORY`
- 支持逻辑操作：`AND`、`OR`、`NOT`
- 支持全局 `scope`（对所有 queries 生效）
- **CCF 等级白名单**：`ccf_enabled: true` 时，DBLP/OpenReview 仅收录指定等级（默认 A/B）的会议/期刊

### 拉取策略

- 严格时间窗口 + 补全回溯：优先拉取 `pull_every` 天内新论文，不足时向前回溯到 `max_lookback_days`
- 多源结果聚合后执行跨源去重（基于 DOI / arXiv ID / 标题相似度）

### 存储

- SQLite 持久化去重，跨次运行不重复推送同一篇论文
- 完整论文内容（标题、摘要、作者等）可选持久化

### 输出

- 支持 `console`、`json`、`markdown`、`html` 格式
- HTML 支持自定义模板

### LLM 增强

- 支持 OpenAI-compatible 接口（OpenAI、DeepSeek、SiliconFlow 等）
- 摘要翻译 + 结构化总结（TLDR / 动机 / 方法 / 结论）
- 通过 `llm.target_lang` 指定输出语言（如 `Simplified Chinese`、`English`、`Japanese`）

### 本地 Dashboard

运行 `paper-tracker dashboard` 可启动本地 Web 界面（默认 `http://127.0.0.1:8765`），支持：

- 浏览、搜索已入库论文
- 手动触发刷新
- 在线配置 LLM 提供商与查询参数

## 快速开始

建议使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
pip install -e .
```

用内置示例配置直接运行：

```bash
paper-tracker search --config config/example.yml
```

启动本地 Dashboard：

```bash
paper-tracker dashboard --config config/example.yml
# 浏览器打开 http://127.0.0.1:8765
```

## 自定义配置

```bash
cp config/example.yml config/custom.yml
# 按需修改 config/custom.yml
paper-tracker search --config config/custom.yml
```

**必填字段：**

- `queries`：至少设置一条查询
- `llm.base_url` / `llm.model`：当 `llm.enabled: true` 时必须指定

### 启用 CCF 过滤（DBLP / OpenReview）

```yaml
search:
  sources: [arxiv, dblp, openreview]
  ccf_enabled: true
  ccf_ranks: [A, B]          # 仅收录 CCF A/B 级会议/期刊
  dblp_recent_years: 2       # 拉取近 N 年的 DBLP 论文集
  openreview_recent_years: 2
```

### 配置 LLM 环境变量（可选）

```bash
cp .env.example .env
# 编辑 .env，填入你的 LLM_API_KEY
```

📚 详细文档：

- [📖 使用指南](./docs/zh/guide_user.md)
- [⚙️ 详细参数配置说明](./docs/zh/guide_configuration.md)
- [🔍 查询内部逻辑说明](./docs/zh/architecture_search_logic.md)
- [🔍 arXiv 查询语法说明](./docs/zh/source_arxiv_api_query.md)
- [🔍 OpenAlex 查询语法说明](./docs/zh/source_openalex_api_query.md)

## 更新

```bash
git pull
pip install -e . --upgrade
```

## 反馈

如遇到问题或有功能建议，欢迎在 [GitHub Issues](https://github.com/CheneyNine/PaperTracker/issues) 提交，请附上运行日志（默认在 `log/` 目录下）。

## 许可证

本项目使用 [MIT License](./LICENSE)。

## 致谢

本项目参考了以下开源工作的功能思路：

- [Arxiv-tracker](https://github.com/colorfulandcjy0806/Arxiv-tracker)
- [daily-arXiv-ai-enhanced](https://github.com/dw-dengwei/daily-arXiv-ai-enhanced)
