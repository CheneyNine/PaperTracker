# Paper Tracker

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)](https://github.com/CheneyNine/PaperTracker/releases)
[![Last Commit](https://img.shields.io/github/last-commit/CheneyNine/PaperTracker)](https://github.com/CheneyNine/PaperTracker/commits)

**English | [中文](./README.zh.md)**

Paper Tracker is a self-hosted paper tracking tool that queries arXiv, OpenAlex, DBLP, and OpenReview, optionally filters by CCF venue ranking, enriches results with LLM summaries, and presents everything in a local web dashboard so you can continuously follow the latest research in your field.

**If this project helps you, please consider giving it a Star ⭐. Thank you!**

## Demo

![Dashboard Preview](./docs/assets/preview_dashboard.png)

![Settings Preview](./docs/assets/preview_setting.png)

## Features

### Sources

Four sources supported, all can be enabled simultaneously:

| Source | Data Type | Query Support | Post-Filter | CCF Filter | Cross-Source Dedup |
|--------|-----------|:-------------:|:-----------:|:----------:|:-----------------:|
| `arxiv` | Preprints | Full | — | — | ✅ |
| `openalex` | Journals / Conferences / Preprints | Partial | ✅ | — | ✅ |
| `dblp` | CCF venue proceedings | Local keyword match | ✅ | ✅ | ✅ |
| `openreview` | CCF conference submissions | Local keyword match | ✅ | ✅ | ✅ |

> **openalex**: Result quality is still improving — it may occasionally return off-topic papers. Disable if results are consistently noisy.
>
> **dblp / openreview**: Requires `ccf_enabled: true`. Only papers from CCF A/B venues are fetched, then filtered by your keywords.

### Query and Filtering

- Field-based search: `TITLE`, `ABSTRACT`, `AUTHOR`, `JOURNAL`, `CATEGORY`
- Logical operators: `AND`, `OR`, `NOT`
- Global `scope` applied across all queries
- **CCF rank whitelist**: when `ccf_enabled: true`, DBLP/OpenReview only collects papers from venues at the specified ranks (default: A and B)

### Fetch Strategy

- Strict time window + backfill: fetches papers within `pull_every` days first, then looks further back (up to `max_lookback_days`) to reach the target count
- Cross-source deduplication after aggregation (DOI / arXiv ID / title fingerprint)

### Storage

- **SQLite** (default) — zero-config, single file, suitable for personal use
- **PostgreSQL** (optional) — recommended for Docker deployments or multi-user scenarios; enable via `storage.backend: postgres` or the `STORAGE_BACKEND` / `DATABASE_URL` environment variables
- Schema migrations are applied automatically on startup

### Output

- Formats: `console`, `json`, `markdown`, `html`
- HTML supports custom Jinja2 templates

### LLM Enhancement

- OpenAI-compatible API (OpenAI, DeepSeek, SiliconFlow, etc.)
- Abstract translation + structured summary (TLDR / motivation / problem / method / result / conclusion)
- Output language configurable via `llm.target_lang` (e.g. `Simplified Chinese`, `English`, `Japanese`)

### Dashboard

Run `paper-tracker dashboard` to open a local web UI at `http://127.0.0.1:8765`:

- Browse stored papers grouped by research theme and keyword
- Archive / restore papers; sort by LLM contribution score
- Trigger a manual refresh per-theme
- Manage research themes, keywords, and AI-assisted keyword suggestions
- Configure LLM provider, CCF filtering, and search sources in-browser

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| CLI | [Click](https://click.palletsprojects.com/) |
| Web server | [FastAPI](https://fastapi.tiangolo.com/) + [uvicorn](https://www.uvicorn.org/) |
| Frontend | [Vue 3](https://vuejs.org/) (CDN IIFE, no build step) |
| Database | SQLite (built-in) · PostgreSQL (optional, via psycopg2-binary) |
| Config | YAML (deep-merge defaults + user overrides) + python-dotenv |
| Containerization | Docker + Docker Compose |

## Project Layout

```
paper-tracker/
├── config/
│   ├── example.yml          # ready-to-run example config
│   └── docker.yml.example   # Docker + PostgreSQL config template
├── src/PaperTracker/
│   ├── cli/                 # Click entry points (search, dashboard)
│   ├── config/              # Config loading and validation
│   ├── core/                # Data models, dedup logic, query parser
│   ├── sources/             # Data source adapters
│   │   ├── arxiv/
│   │   ├── openalex/
│   │   ├── dblp/
│   │   └── openreview/
│   ├── llm/                 # OpenAI-compatible LLM client
│   ├── services/            # Search orchestration
│   ├── storage/             # Persistence layer
│   │   ├── migrations/      # Versioned schema migrations (v001–v006)
│   │   ├── db.py            # SQLite connection manager
│   │   └── pg_db.py         # PostgreSQL connection pool
│   ├── dashboard/
│   │   ├── server.py        # FastAPI app (14 API endpoints)
│   │   └── assets/          # Vue 3 frontend (index.html, app.vue.js, style.css)
│   ├── renderers/           # Output formatters (console / json / markdown / html)
│   └── ccf/                 # CCF venue whitelist cache
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Quick Start

### Option A — Local (pip)

```bash
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
pip install -e .
```

Fetch papers with the built-in example config:

```bash
paper-tracker search --config config/example.yml
```

Start the dashboard:

```bash
paper-tracker dashboard --config config/example.yml
# Open http://127.0.0.1:8765
```

### Option B — Docker (PostgreSQL backend)

```bash
# 1. Create your .env
cp .env.example .env
# Edit .env — set a strong POSTGRES_PASSWORD

# 2. Create your config
cp config/docker.yml.example config/custom.yml
# Edit config/custom.yml — add your queries, enable LLM if needed

# 3. Start
docker compose up -d
# Open http://localhost:8765
```

Data is persisted in the `postgres_data` named volume. The `config/` directory is mounted read-only into the container.

## Configuration

```bash
cp config/example.yml config/custom.yml
# Edit config/custom.yml
paper-tracker search --config config/custom.yml
```

**Required fields:**

- `queries`: at least one query must be defined
- `llm.base_url` and `llm.model`: required when `llm.enabled: true`

### Enable CCF Filtering (DBLP / OpenReview)

```yaml
search:
  sources: [arxiv, dblp, openreview]
  ccf_enabled: true
  ccf_ranks: [A, B]
  dblp_recent_years: 2
  openreview_recent_years: 2
```

### Configure LLM

```bash
cp .env.example .env
# Set LLM_API_KEY in .env
```

```yaml
llm:
  enabled: true
  base_url: https://api.openai.com/v1   # or any OpenAI-compatible endpoint
  model: gpt-4o-mini
  enable_translation: true
  enable_summary: true
  target_lang: Simplified Chinese
```

### Use PostgreSQL (local, without Docker)

```yaml
storage:
  backend: postgres
  database_url: postgresql://user:password@localhost:5432/paper_tracker
  db_path: database/papers.db   # unused in postgres mode, but must be non-empty
```

Or pass environment variables:

```bash
export STORAGE_BACKEND=postgres
export DATABASE_URL=postgresql://user:password@localhost:5432/paper_tracker
```

Install the PostgreSQL driver:

```bash
pip install -e ".[postgres]"
```

📚 More docs:

- [📖 User Guide](./docs/en/guide_user.md)
- [⚙️ Configuration Reference](./docs/en/guide_configuration.md)
- [🔍 Search Logic](./docs/en/architecture_search_logic.md)
- [🔍 arXiv Query Syntax](./docs/en/source_arxiv_api_query.md)
- [🔍 OpenAlex Query Parameters](./docs/en/source_openalex_api_query.md)

## Update

```bash
git pull
pip install -e . --upgrade
```

## Feedback

For bugs or feature requests, open an issue at [GitHub Issues](https://github.com/CheneyNine/PaperTracker/issues). Please include the runtime log (default location: `log/`).

## License

[MIT License](./LICENSE)

## Acknowledgments

Inspired by:

- [Arxiv-tracker](https://github.com/colorfulandcjy0806/Arxiv-tracker)
- [daily-arXiv-ai-enhanced](https://github.com/dw-dengwei/daily-arXiv-ai-enhanced)
