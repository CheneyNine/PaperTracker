# Paper Tracker

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)](https://github.com/CheneyNine/PaperTracker/releases)
[![Last Commit](https://img.shields.io/github/last-commit/CheneyNine/PaperTracker)](https://github.com/CheneyNine/PaperTracker/commits)
[![Code Size](https://img.shields.io/github/languages/code-size/CheneyNine/PaperTracker)](https://github.com/CheneyNine/PaperTracker)

**English | [中文](./README.md)**

Paper Tracker is a minimal paper tracking tool that queries multiple databases — arXiv, OpenAlex, DBLP, and OpenReview — filters results by CCF venue ranking, optionally enriches them with LLM summaries, and outputs structured results so you can continuously track the latest research in your field.

**If this project helps you, please consider giving it a Star ⭐. Thank you!**

## Demo

![Dashboard Preview](./docs/assets/preview_dashboard.png)

![Settings Preview](./docs/assets/preview_setting.png)

## Features

### Sources

Four sources supported, all can be enabled simultaneously:

| Source | Data Type | Query Field Support | Local Post-Filter | CCF Filter | Cross-Source Dedupe |
|--------|-----------|:-------------------:|:-----------------:|:----------:|:-------------------:|
| `arxiv` | Preprints | Full | — | — | ✅ |
| `openalex` | Journals / Conferences / Preprints | Partial | ✅ | — | ✅ |
| `dblp` | CCF venue proceedings | Local keyword match | ✅ | ✅ | ✅ |
| `openreview` | CCF conference submissions | Local keyword match | ✅ | ✅ | ✅ |

> **openalex note**: Result quality is still improving — it may occasionally return off-topic papers. Disable if results are consistently noisy.
>
> **dblp / openreview**: Requires `ccf_enabled: true`. Only papers from CCF A/B venues are fetched, then filtered by your keywords.

### Query and Filtering

- Field-based search: `TITLE`, `ABSTRACT`, `AUTHOR`, `JOURNAL`, `CATEGORY`
- Logical operators: `AND`, `OR`, `NOT`
- Global `scope` applied across all queries
- **CCF rank whitelist**: when `ccf_enabled: true`, DBLP/OpenReview only collects papers from venues at the specified ranks (default: A and B)

### Fetch Strategy

- Strict time window + backfill: fetches papers within `pull_every` days first, then looks further back (up to `max_lookback_days`) to reach the target count
- Cross-source deduplication after aggregation (DOI / arXiv ID / title similarity)

### Storage

- SQLite-backed deduplication — no repeated papers across runs
- Full paper content (title, abstract, authors, etc.) optionally persisted

### Output

- Formats: `console`, `json`, `markdown`, `html`
- HTML supports custom templates

### LLM Enhancement

- OpenAI-compatible API (OpenAI, DeepSeek, SiliconFlow, etc.)
- Abstract translation + structured summary (TLDR / motivation / method / conclusion)
- Output language configurable via `llm.target_lang` (e.g. `Simplified Chinese`, `English`, `Japanese`)

### Local Dashboard

Run `paper-tracker dashboard` to start a local web UI (default: `http://127.0.0.1:8765`) with:

- Browse and search stored papers
- Trigger manual refresh
- Configure LLM provider and query parameters in-browser

## Quick Start

A virtual environment is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
pip install -e .
```

Run with the built-in example config:

```bash
paper-tracker search --config config/example.yml
```

Start the local Dashboard:

```bash
paper-tracker dashboard --config config/example.yml
# Open http://127.0.0.1:8765 in your browser
```

## Custom Configuration

```bash
cp config/example.yml config/custom.yml
# Edit config/custom.yml as needed
paper-tracker search --config config/custom.yml
```

**Required fields:**

- `queries`: at least one query must be configured
- `llm.base_url` / `llm.model`: required when `llm.enabled: true`

### Enable CCF Filtering (DBLP / OpenReview)

```yaml
search:
  sources: [arxiv, dblp, openreview]
  ccf_enabled: true
  ccf_ranks: [A, B]          # only collect CCF A/B venues
  dblp_recent_years: 2       # fetch proceedings from the last N years
  openreview_recent_years: 2
```

### Configure LLM API Key (optional)

```bash
cp .env.example .env
# Edit .env and fill in your LLM_API_KEY
```

📚 Detailed docs:

- [📖 User Guide](./docs/en/guide_user.md)
- [⚙️ Configuration Reference](./docs/en/guide_configuration.md)
- [🔍 Search Logic Overview](./docs/en/architecture_search_logic.md)
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

This project is licensed under the [MIT License](./LICENSE).

## Acknowledgments

This project was inspired by the following open-source works:

- [Arxiv-tracker](https://github.com/colorfulandcjy0806/Arxiv-tracker)
- [daily-arXiv-ai-enhanced](https://github.com/dw-dengwei/daily-arXiv-ai-enhanced)
