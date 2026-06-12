# Changelog

All notable changes to the **PartnerPulse** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0-beta.5] - 2026-06-11

### Added
- **Manual "Sync Data" button + sync API:** both dashboard pages now have a header button that starts a full data-sync cycle on demand. `server.py` grew a single-flight sync runner — `POST /api/refresh` (optional `{"steps": [...]}` subset; 409 if already running) and `GET /api/refresh/status` (per-step progress + log tail, also appended to `data/_sync.log`). The cycle shells out sequentially to `extract.build_all`, `scripts/build_real_partners.py`, and `extract.build_all --reindex`, continuing past failed steps and reporting each. The shared `refresh.js` drives the button: confirm dialog (live API + AI cost), spinner with step progress polled every 3s, page reload when data changed, honest "Sync failed" state otherwise.
- **Per-partner SIP counts (open / closed):** `extract/halo.py: count_sips()` counts all-time Service Improvement Plans (Halo ticket type 99) per partner — free-text search + client-side type filter (Halo has no working server-side type filter), a recovery pass for SIPs mis-filed under ITBD's own client record, and a status-name heuristic for open vs. closed. Surfaced as `client.sip_open`/`sip_closed` in partner JSON and index rows, and as a "SIPs (open / closed)" KPI + detail field on the partner page.
- **`scripts/build_real_partners.py`:** pulls 8 additional real Halo clients (Netgain, F12, RedHelm-1Path, Proda, Amoskeag, Granite Networks, Secure Future, Atlantic PC) through the same extraction + gpt-5.4 analysis (no deck/transcript path), writes `data/{slug}.json`, and injects exec-overview objects into `index.html`'s embedded partner array.
- **Transcript ingestion for every partner with a `Transcripts/` folder:** `scripts/build_real_partners.py` now parses local transcripts (when `markitdown` is available) and feeds them to the AI, same as the registry path. Folder matching is case/punctuation-insensitive (`extract/transcripts.py: resolve_partner_dir`), and any `Transcripts/` subfolder that matches **no** built partner triggers a loud warning instead of being silently ignored.
- **`docs/IT-Request-Graph-Transcript-Access.md`:** drafted IT request for an Entra app registration (`OnlineMeetingTranscript.Read.All` + `OnlineMeetings.Read.All` + `Calendars.Read`, application access policies scoping it to the MDE/DES/SBD Management accounts) so the pipeline can ingest call transcripts without the per-meeting attendee constraint.
- **Teams call-recording transcripts (`.vtt`):** `extract/transcripts.py: parse_vtt` parses Teams WEBVTT transcripts natively (NOTE metadata header, `<v Speaker>` voice tags, same-speaker cue merging) — `list_partner_transcripts` now picks up `.docx` + `.vtt`. Transcripts are pulled from the Graph meeting-transcript API via the Claude M365 connector (flow + 403 attendee constraint documented in Data-Extraction-SOP §1 Option C). First 5 pulled: Milner 05-29, ION247 06-03, Premier 05-15, Netgain 06-01 (new folder), MSP Corp CRDS 06-09. Backfill added 11 more (16 total): Milner 04-17→05-22 weeklies (6), Netgain 04-20 + 05-04, Premier 04-17, MSP Corp MBCCS 06-10, RealTime IT 06-11. ION247 05-15 has no transcript (recording stopped at a participant's request). NOTE-header parsing made case-insensitive (agent-written headers vary).
- **`CLAUDE.md`** (LLM working context) and **`docs/LLM-SOP.md`** (documentation-maintenance SOP for any LLM making changes).
- **`hooks/pre-commit` docs-enforcement hook:** any commit staging code/config without `docs/changelog.md` is blocked with a pointer to the LLM SOP registry; doc-only commits pass. Versioned in `hooks/` and activated via `git config core.hooksPath hooks` (now done automatically by `setup.ps1`); `.gitattributes` pins `hooks/*` to LF so the sh script survives Windows checkouts. Human-only bypass: `SKIP_DOCS_CHECK=1`.

### Fixed
- **Sync button rendered unstyled (giant icon) on the Executive Overview:** `index.html` is fully self-contained and does not load `styles.css`, so the `.sync-btn` rules never applied there. The rules are now duplicated in its inline `<style>` block, and the icon SVG carries explicit `width="16" height="16"` attributes as a fallback on both pages.

### Changed
- **Repo reorganization:** operational scripts moved from the repo root into `scripts/`; the saved build-session log moved to `docs/archive/PartnerPulse.txt`. README and architecture docs updated to match.
- **`extract.build_all --reindex` now indexes every per-partner JSON in `data/`** (previously only the 10 registry partners), so the extra real partners built by `scripts/build_real_partners.py` stay in `data/_index.json`. The sync cycle's final step uses it.
- **Partner page navigation:** back-link relabelled "All Partners" → "Dashboard".

### Removed
- **All synthetic demo data, wiped from the codebase:** the 36 seeded demo partners (`demo: true` JSONs in `data/`), the injected demo block in `index.html`'s embedded array, the generated `demo_exec_partners.js`, and the seeder script `scripts/gen_demo_partners.py` itself. The dashboard now shows the 18 real partners only.
- **`portfolio.js`** (and the old portfolio SPA): its Partner 360 list view is now a second view inside `index.html`, switched from the sidebar. The Executive Overview's partner array is embedded in the page and kept in sync by the two injection scripts — it is no longer fetched from `data/_index.json` at runtime.

---

## [1.0.0-beta.4] - 2026-06-07

### Changed
- **Dark sidebar navigation** across both the portfolio and per-partner pages: the left sidebar now uses a dark slate theme (nav links, brand, partner selector, and the Data Sources footer restyled for the dark background) while the header, content area, charts, and tables stay light. Styling is scoped entirely under `.sidebar` in `styles.css`.
- **Partner Health Profile labels clarified:** "Downgrade Rationale" relabelled to "Health Summary" (with its orange warning color removed, since `CFHealthReason` is often neutral/positive) and "Remediation Plan" relabelled to "Next Step" (`CFNextStep`). Halo field tags retained in parentheses.

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
