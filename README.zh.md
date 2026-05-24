# Paper Tracker

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)](https://github.com/CheneyNine/PaperTracker/releases)
[![Last Commit](https://img.shields.io/github/last-commit/CheneyNine/PaperTracker)](https://github.com/CheneyNine/PaperTracker/commits)

**[English](./README.md) | 中文**

Paper Tracker 是一个自托管的论文追踪工具，支持从 arXiv、OpenAlex、DBLP、OpenReview 多个数据源检索论文，结合 CCF 等级过滤和 LLM 摘要增强，通过本地 Web 看板持续追踪领域最新进展。

**如果该项目对你有帮助，请麻烦点一个 Star ⭐，谢谢！**

## 效果展示

![Dashboard 预览](./docs/assets/preview_dashboard.png)

![设置页面预览](./docs/assets/preview_setting.png)

## 功能概览

### 数据源

支持 4 个数据源，可同时启用：

| 数据源 | 数据类型 | query 字段支持 | 本地精筛 | CCF 过滤 | 跨源去重 |
|--------|----------|:--------------:|:--------:|:--------:|:--------:|
| `arxiv` | 预印本 | 完整 | — | — | ✅ |
| `openalex` | 期刊 / 会议 / 预印本 | 部分 | ✅ | — | ✅ |
| `dblp` | CCF 会议论文集 | 本地关键词匹配 | ✅ | ✅ | ✅ |
| `openreview` | CCF 会议投稿 | 本地关键词匹配 | ✅ | ✅ | ✅ |

> **openalex 注意**：结果稳定性尚在改善中，可能偶尔返回无关论文，如偏差明显建议暂时关闭。
>
> **dblp / openreview**：依赖 CCF 白名单（`ccf_enabled: true`），仅拉取 CCF A/B 级会议/期刊的近期论文，再按关键词过滤。

### 检索与过滤

- 支持字段化检索：`TITLE`、`ABSTRACT`、`AUTHOR`、`JOURNAL`、`CATEGORY`
- 支持逻辑操作：`AND`、`OR`、`NOT`
- 支持全局 `scope`（对所有 queries 生效）
- **CCF 等级白名单**：`ccf_enabled: true` 时，DBLP/OpenReview 仅收录指定等级（默认 A/B）的会议/期刊

### 拉取策略

- 严格时间窗口 + 补全回溯：优先拉取 `pull_every` 天内新论文，不足时向前回溯至 `max_lookback_days`
- 多源结果聚合后执行跨源去重（DOI / arXiv ID / 标题指纹）

### 存储

- **SQLite**（默认）——零配置，单文件，适合个人本地使用
- **PostgreSQL**（可选）——推荐用于 Docker 部署或多用户场景；通过 `storage.backend: postgres` 或环境变量 `STORAGE_BACKEND` / `DATABASE_URL` 启用
- 数据库 Schema 迁移在启动时自动应用

### 输出

- 支持 `console`、`json`、`markdown`、`html` 格式
- HTML 支持自定义 Jinja2 模板

### LLM 增强

- 支持 OpenAI-compatible 接口（OpenAI、DeepSeek、SiliconFlow 等）
- 摘要翻译 + 结构化总结（TLDR / 动机 / 问题 / 方法 / 结果 / 结论）
- 通过 `llm.target_lang` 指定输出语言（如 `Simplified Chinese`、`English`、`Japanese`）

### 本地看板

运行 `paper-tracker dashboard` 可启动本地 Web 界面（默认 `http://127.0.0.1:8765`），功能包括：

- 按研究主题和关键词分组浏览已入库论文
- 归档 / 恢复论文；按 LLM 贡献度排序
- 按主题手动触发刷新
- 管理研究主题、检索关键词，支持 AI 智能生成关键词
- 在线配置 LLM 提供商、CCF 过滤和检索渠道

## 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| CLI | [Click](https://click.palletsprojects.com/) |
| Web 服务器 | [FastAPI](https://fastapi.tiangolo.com/) + [uvicorn](https://www.uvicorn.org/) |
| 前端 | [Vue 3](https://vuejs.org/)（CDN IIFE，无构建步骤） |
| 数据库 | SQLite（内置）· PostgreSQL（可选，via psycopg2-binary） |
| 配置 | YAML（默认值 + 用户覆盖深度合并）+ python-dotenv |
| 容器化 | Docker + Docker Compose |

## 项目结构

```
paper-tracker/
├── config/
│   ├── example.yml          # 开箱即用的示例配置
│   └── docker.yml.example   # Docker + PostgreSQL 配置模板
├── src/PaperTracker/
│   ├── cli/                 # Click 入口（search、dashboard）
│   ├── config/              # 配置加载与校验
│   ├── core/                # 数据模型、去重逻辑、查询解析
│   ├── sources/             # 数据源适配器
│   │   ├── arxiv/
│   │   ├── openalex/
│   │   ├── dblp/
│   │   └── openreview/
│   ├── llm/                 # OpenAI-compatible LLM 客户端
│   ├── services/            # 检索编排
│   ├── storage/             # 持久化层
│   │   ├── migrations/      # 版本化 Schema 迁移（v001–v006）
│   │   ├── db.py            # SQLite 连接管理
│   │   └── pg_db.py         # PostgreSQL 连接池
│   ├── dashboard/
│   │   ├── server.py        # FastAPI 应用（14 个 API 端点）
│   │   └── assets/          # Vue 3 前端（index.html、app.vue.js、style.css）
│   ├── renderers/           # 输出格式化（console / json / markdown / html）
│   └── ccf/                 # CCF 会议/期刊白名单缓存
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## 快速开始

### 方式 A — 本地安装（pip）

```bash
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
pip install -e .
```

使用内置示例配置直接运行：

```bash
paper-tracker search --config config/example.yml
```

启动本地看板：

```bash
paper-tracker dashboard --config config/example.yml
# 浏览器打开 http://127.0.0.1:8765
```

### 方式 B — Docker（PostgreSQL 后端）

```bash
# 1. 创建 .env 文件
cp .env.example .env
# 编辑 .env，设置一个强密码 POSTGRES_PASSWORD

# 2. 创建配置文件
cp config/docker.yml.example config/custom.yml
# 编辑 config/custom.yml，填入你的 queries，按需开启 LLM

# 3. 启动
docker compose up -d
# 浏览器打开 http://localhost:8765
```

数据持久化在 `postgres_data` 命名卷中。`config/` 目录以只读方式挂载进容器。

## 自定义配置

```bash
cp config/example.yml config/custom.yml
# 按需修改 config/custom.yml
paper-tracker search --config config/custom.yml
```

**必填字段：**

- `queries`：至少设置一条查询
- `llm.base_url` 和 `llm.model`：当 `llm.enabled: true` 时必须指定

### 启用 CCF 过滤（DBLP / OpenReview）

```yaml
search:
  sources: [arxiv, dblp, openreview]
  ccf_enabled: true
  ccf_ranks: [A, B]
  dblp_recent_years: 2
  openreview_recent_years: 2
```

### 配置 LLM

```bash
cp .env.example .env
# 在 .env 中填入 LLM_API_KEY
```

```yaml
llm:
  enabled: true
  base_url: https://api.openai.com/v1   # 或任意 OpenAI-compatible 接口
  model: gpt-4o-mini
  enable_translation: true
  enable_summary: true
  target_lang: Simplified Chinese
```

### 使用 PostgreSQL（本地，不使用 Docker）

```yaml
storage:
  backend: postgres
  database_url: postgresql://user:password@localhost:5432/paper_tracker
  db_path: database/papers.db   # postgres 模式下不使用，但不能为空
```

或直接通过环境变量传入：

```bash
export STORAGE_BACKEND=postgres
export DATABASE_URL=postgresql://user:password@localhost:5432/paper_tracker
```

安装 PostgreSQL 驱动：

```bash
pip install -e ".[postgres]"
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

[MIT License](./LICENSE)

## 致谢

本项目参考了以下开源工作：

- [Arxiv-tracker](https://github.com/colorfulandcjy0806/Arxiv-tracker)
- [daily-arXiv-ai-enhanced](https://github.com/dw-dengwei/daily-arXiv-ai-enhanced)
