# Changelog

All notable changes to the **PartnerPulse** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0-beta.4] - 2026-06-07

### Changed
- **Dark sidebar navigation** across both the portfolio and per-partner pages: the left sidebar now uses a dark slate theme (nav links, brand, partner selector, and the Data Sources footer restyled for the dark background) while the header, content area, charts, and tables stay light. Styling is scoped entirely under `.sidebar` in `styles.css`.

---

## [1.0.0-beta.3] - 2026-06-07

### Added
- **Executive Overview chart suite:** Four Chart.js 4.4.4 charts on the portfolio landing page — portfolio sentiment trend (weekly CSAT positivity line), risk-distribution donut (High / Watch / Healthy tiers), feedback-mix-by-source stacked bar (CSAT Positive/Neutral/Negative + NPS Promoter/Passive/Detractor), and top-churn-drivers horizontal bar (severity-weighted, themed from gpt-5.4 `drivers[]`).
- **Chart.js vendored locally** (`vendor/chart.umd.min.js` v4.4.4) — dashboard works fully offline with no CDN dependency at runtime.
- **Portfolio aggregates in `data/_index.json`** (`extract/portfolio.py`): `_index.json` is now a JSON object `{ "partners": [...], "portfolio": {...} }` instead of a bare array. The `portfolio` block contains `risk_distribution`, `sentiment_trend` (12-week weekly buckets), `feedback_mix`, `top_drivers`, and `generated_at`, all derived in-process from per-partner caches — no new API calls.
- **Partner 360 view** on `index.html`: sortable churn-risk ranking table, RAG status filter, and highest-risk partner cards, selectable from the left sidebar alongside Executive Overview.
- **Data Sources sidebar footer** on `index.html`: live-status indicators for HaloPSA, TeamGPS CSAT/NPS, Transcripts & Decks, and Azure gpt-5.4, plus a last-sync timestamp drawn from `portfolio.generated_at`.
- **Per-partner page dynamic refactor** (`partner.html` + `partner.js`): partner loaded by `?partner=slug` query string with six sidebar tabs — Overview, AI Insights, Action Tracker, CSAT & NPS, Transcripts, and Service Decks.
- **Two-mode Halo attachment download** (`extract/halo.py`): `download_attachment` now handles both inline raw-byte responses and JSON `{"link": <pre-signed CDN URL>}` envelopes transparently.
- **`docs/` directory** for architecture, changelog, and the three SOP Markdown files; dead legacy single-partner files (`app.js`, `data.js`) moved to `legacy/`.

---

## [1.0.0-beta.2] - 2026-06-07

### Fixed
- Stopped tracking generated runtime log files (`data/*.log`) in version control, keeping the cache clean.

---

## [1.0.0-beta.1] - 2026-06-06

### Added
- **Ingestion & Processing Pipeline:**
  - Integrated **HaloPSA API** connection to retrieve client metadata, custom RAG (Red/Amber/Green) fields, review tickets, meeting notes, and attachments.
  - Integrated **TeamGPS API** connection to collect client CSAT and NPS metrics.
  - Added Microsoft **MarkItDown** processing for converting `.docx` transcripts, `.pptx` presentations, and `.pdf` reports to clean Markdown.
- **AI Churn Analytics:**
  - Implemented Azure OpenAI **gpt-5.4** analysis engine to generate partner churn risk scores (1-100), identify churn drivers, list positive indicators, and extract actionable remediation tasks.
  - Automated output caching to `data/{slug}.json` and index compilation to `data/_index.json`.
- **Frontend Dashboard:**
  - Created a responsive, framework-free executive landing page (`index.html`) displaying all partners sorted by churn risk.
  - Created a detailed per-partner drilldown view (`partner.html`) displaying AI Insights, Action Tracker, CSAT/NPS trendlines, and converted meeting transcripts/decks.
  - Implemented a unified stylesheet (`styles.css`) for consistent white-label brand presentation.
- **Developer Experience (DX):**
  - Added a self-contained local development server (`server.py`).
  - Created a automated PowerShell setup script (`setup.ps1`) to provision the Python virtual environment (`.venv`), install requirements, perform the first full data fetch, and run the server.
  - Created `.env.example` template for managing environment secret variables.
