# PartnerPulse System Architecture

PartnerPulse is an executive partner-health and churn-risk dashboard for ITBD, a white-label NOC/helpdesk provider whose "partners" are MSPs. It aggregates telemetry from multiple APIs and local documentation, runs AI-driven churn analytics, and presents them in a clean, high-performance UI.

---

## 1. System Overview

The system is split into two primary layers:
1. **Ingestion & AI Engine (Python):** A synchronous build-time pipeline that fetches data from APIs, parses files, runs LLM analysis, and exports static JSON caches. It is run ahead of time — not on page load.
2. **Presentation Layer (Frontend):** A lightweight, framework-free client-side dashboard that consumes the static JSON cache to render visualizations, health metrics, and transcripts.

```mermaid
graph TD
    subgraph Data Sources
        Halo[HaloPSA API]
        GPS[TeamGPS API]
        Docs[Local .docx Transcripts & Decks]
    end

    subgraph Ingestion & AI Engine (Python)
        Engine[extract/build_all.py / build_partner.py]
        Scripts[scripts/build_real_partners.py]
        Portfolio[extract/portfolio.py]
        MID[MarkItDown Parser]
        Azure[Azure Foundry gpt-5.4]
    end

    subgraph Data Cache (Gitignored)
        Index[data/_index.json]
        PartnerC[data/{partner-slug}.json]
    end

    subgraph Presentation Layer (Frontend)
        IndexUI[index.html — Executive Overview + Partner 360, embedded partner array]
        DetailUI[partner.html / partner.js]
        Server[server.py]
    end

    %% Data flow connections
    Halo --> Engine
    GPS --> Engine
    Docs -->|Raw Docs| MID
    MID -->|Markdown Text| Engine
    Engine -->|Metadata + Transcripts| Azure
    Azure -->|Churn Analysis & Actions| Engine
    Engine -->|Write Cache| PartnerC
    Engine --> Portfolio
    Portfolio -->|Portfolio Aggregates| Index
    Engine -->|Partner Rows| Index
    Scripts -->|Inject partner objects| IndexUI
    Scripts -->|Write/refresh caches| PartnerC

    Server -->|Serve Assets| IndexUI
    Server -->|Serve Assets| DetailUI
    PartnerC -->|Runtime fetch| DetailUI
```

> **Note:** `index.html` does **not** fetch `data/_index.json` at runtime — its partner array is **embedded in the page** and kept in sync by the injection scripts (see §4). Only `partner.html`/`partner.js` fetch JSON (`data/{slug}.json`) at runtime.

### Repository layout

```
index.html / partner.html / partner.js / refresh.js / styles.css / vendor/   the dashboard (served from repo root)
server.py / setup.ps1 / requirements.txt                        entry points (server.py also hosts the sync API)
extract/        ingestion + AI pipeline (Python package, run via python -m extract.*)
scripts/        operational scripts (build_real_partners.py, refresh_exec_row.py,
                setup_graph_transcript_access.ps1, probe_graph_transcripts.py)
data/           generated caches (whole dir gitignored): {slug}.json, _index.json, decks/, _sync.log
Transcripts/    input meeting transcripts, per partner (.docx Teams exports + .vtt Graph pulls)
docs/           architecture, changelog, SOPs, LLM-SOP, archive/
legacy/         superseded single-partner files
CLAUDE.md       LLM working context (commands, gotchas, doc-update rules)
```

---

## 2. Ingestion & AI Engine Pipeline

The Python engine orchestrates the compilation of raw partner telemetry into a unified profile. The pipeline runs as follows:

1. **Partner Registry Resolution (`extract/partners.py`):** Resolves human-readable partner names to their respective HaloPSA Client IDs and TeamGPS company identifiers.
2. **Telemetry Fetching:**
   * **HaloPSA (`extract/halo.py`):** Queries custom RAG/risk fields, client metadata, review tickets, meeting notes, and attachments. Attachments support two delivery modes: inline raw bytes, or a JSON `{"link": <pre-signed CDN URL>}` response that must be followed — both handled transparently in `halo.download_attachment`.
   * **TeamGPS (`extract/teamgps.py`):** Fetches CSAT (filtered by company) and NPS (filtered by email domain). The full NPS set is fetched once in `build_all.py` and passed to each partner build to avoid redundant API calls.
   * **SIP counts (`extract/halo.py: count_sips`):** All-time Service Improvement Plan (Halo ticket type 99) counts per partner, split open/closed. Halo has no working server-side ticket-type filter, so the engine searches three free-text terms, filters rows client-side on `tickettype_id == 99`, and runs a second "bucket B" pass over SIPs filed under ITBD's own client record (id 12) whose summary names the partner. Open vs. closed is a status-**name** heuristic (no `isclosed` flag exists). Results land as `client.sip_open` / `client.sip_closed`.
3. **Document Extraction (`extract/transcripts.py`):** Uses Microsoft's `markitdown` library to convert local `.docx` meeting transcripts, PowerPoint decks, and PDF reports into Markdown text. Teams **WEBVTT** transcripts (`.vtt`, pulled from the Graph meeting-transcript API via the Claude M365 connector — see Data-Extraction-SOP §1 Option C) are parsed natively by `parse_vtt`, no markitdown needed.
4. **AI Synthesis & Analysis (`extract/ai.py`):** Feeds the compiled telemetry, meeting notes, and transcripts to **Azure Foundry gpt-5.4** (deployment `gpt-5.4`). The model evaluates:
   * Churn risk score (0-100) and risk band (Low / Medium / High / Critical).
   * Confidence level and sentiment trend (Improving / Stable / Declining).
   * Key churn drivers with severity and evidence quotes.
   * Remediation steps and extracted action items.
5. **Per-Partner Caching:** Outputs a unified data payload to `data/{slug}.json`.
6. **Portfolio Aggregation (`extract/portfolio.py`):** Derives portfolio-level aggregates (risk distribution, weekly CSAT/NPS sentiment trend, feedback mix by source, severity-weighted top churn drivers) from the already-fetched per-partner data — no new API calls, no ticket/SLA data. Results are written as the `portfolio` block in `data/_index.json`.
7. **Index Compilation:** `build_all.py` writes `data/_index.json` as an object containing a sorted `partners` array (one slim row per partner) plus the `portfolio` aggregate block.

> **Intentional exclusion:** Bulk ticket SLA/status data is not pulled. For the white-label NOC model, SLA volumes are end-customer metrics, not ITBD–partner churn signals.

---

## 3. Data Cache Schema

### Portfolio Index (`data/_index.json`)

A JSON **object** (not a bare array) with two top-level keys:

```json
{
  "partners": [
    {
      "slug": "logically",
      "name": "Logically",
      "client_id": 106,
      "rag": "Amber",
      "cancel_risk": "Low",
      "service_line": "NOC",
      "vip": false,
      "sip_ticket": "761066",
      "sip_open": 1,
      "sip_closed": 2,
      "account_manager": "Akhilesh Shukla (Dedicated Team Lead)",
      "csat_positive_pct": 93.3,
      "csat_total": 509,
      "nps_promoters": 19,
      "nps_detractors": 0,
      "risk_score": 34,
      "risk_band": "Medium",
      "sentiment_trend": "Stable",
      "summary": "...",
      "sources": { "csat": 509, "nps": 19, "calls": 4, "decks": 4, "transcripts": 6 }
    }
  ],
  "portfolio": {
    "risk_distribution": { "High": 2, "Watch": 1, "Healthy": 7 },
    "sentiment_trend": [
      { "label": "May 31", "csat_positive_pct": 95.7, "csat_total": 23, "nps_avg": null, "nps_count": 0 }
    ],
    "feedback_mix": {
      "csat": { "Positive": 833, "Neutral": 36, "Negative": 7 },
      "nps": { "Promoter": 54, "Passive": 20, "Detractor": 1 }
    },
    "top_drivers": [
      { "theme": "Engineer performance & quality", "score": 1.0, "weight": 25.0, "count": 14 }
    ],
    "generated_at": "2026-06-06T23:19:32.326667+00:00"
  }
}
```

The `risk_distribution` tiers map from the AI `risk_band`: `Critical`/`High` → **High**, `Medium` → **Watch**, `Low` → **Healthy**.

### Partner Detail Cache (`data/{slug}.json`)

Contains all fetched data and the AI analysis block. Exact top-level keys:

| Key | Contents |
|---|---|
| `meta` | `generated_at`, `partner` (registry name), `sources` (counts per data type) |
| `client` | `id`, `name`, `vip`, `rag`, `cancel_risk`, `health_reason`, `next_step`, `sip_ticket`, `sip_open`, `sip_closed`, `service_line`, `account_manager` |
| `csat_stats` | Aggregated CSAT rating counts (`Positive`, `Neutral`, `Negative`, `Unrated`) |
| `csat_comments` | Raw CSAT records with `id`, `rating`, `comment`, `contact`, `contact_email`, `date`, `ticket_id`, `ticket_name` |
| `nps_stats` | Aggregated NPS category counts (`Promoter`, `Passive`, `Detractor`) |
| `nps_comments` | Raw NPS records with `score`, `category`, `respondent`, `comment`, `date` |
| `historical_calls` | Service-review meeting records: `ticket_id`, `summary`, `date`, `notes` (Markdown, joined from Halo action entries) |
| `action_items` | Left empty (`[]`) by the extractor — the AI's extracted items live under `ai.action_items` |
| `decks` | Converted service-review attachments: `ticket_id`, `attachment_id`, `filename`, `md_path`, `markdown` |
| `transcripts` | Local `.docx` files parsed to dialogue turns |
| `ai` | Full gpt-5.4 output: `risk_score`, `risk_band`, `confidence`, `summary`, `sentiment_trend`, `drivers[]`, `remediation[]`, `action_items[]`, `_model` |

---

## 4. Key Architectural Choices & Tradeoffs

### Build-Time Cache vs. Real-Time API Queries
* **Choice:** The application processes telemetry and runs AI analysis ahead of time (synchronously, as a CLI pipeline), generating static JSON.
* **Why:** Calling HaloPSA/TeamGPS APIs and running gpt-5.4 on page load would take 10–30 seconds per request, resulting in a poor user experience. It also prevents API rate-limiting issues and controls Azure API costs.
* **Tradeoff:** The dashboard displays cached data. Updates are not live — they are triggered by the dashboard's **"Sync Data"** header button (see *Manual Sync API* below), a recurring task (e.g., cron job), or manual execution of `python -m extract.build_all`.

### Manual Sync API + Dashboard Button
* **Choice:** `server.py` exposes a small stdlib-only sync API — `POST /api/refresh` starts a single-flight sync cycle (409 if one is running; optional `{"steps": [...]}` body runs a subset), `GET /api/refresh/status` reports per-step progress plus a live `activity` string. The cycle shells out sequentially to the existing entry points (`extract.build_all` → `scripts/build_real_partners.py` → `scripts/refresh_exec_row.py --all` → `extract.build_all --reindex`), one subprocess per step, **continue-on-failure**. The `exec-rows` step keeps the registry partners' static exec-overview rows in `index.html` in lockstep with the rebuilt caches — without it a full sync updates `data/*.json` but leaves those embedded rows stale (the two-data-layer drift). Each step's output is **streamed line-by-line** into `data/_sync.log`, and the pipeline's tagged phase lines (`=== Partner ===`, `[csat]`, `[nps]`, `[transcripts]`, "running gpt-5.4 churn analysis…", …) are translated by `parse_activity()` into the human-readable activity (e.g. "Logically: syncing TeamGPS CSAT"). The shared `refresh.js` wires the header "Sync Data" button on both pages: confirm dialog, polled progress (2s), a progress panel under the button listing every step (✓/⟳/✕) with the live activity, page reload when at least one step succeeded. The panel CSS is duplicated in `styles.css` and `index.html`'s inline `<style>` (the latter loads no external CSS).
* **Why:** Source systems change daily (e.g., a Halo SIP open today is closed tomorrow); the exec needs a way to know the dashboard is current *now* without touching a terminal. Subprocesses (rather than in-process imports) isolate module-level API caches, keep the server dependency-free, and make a missing optional dependency (e.g. `markitdown` for the registry step) degrade to a per-step failure instead of breaking the whole cycle.
* **Tradeoff:** A full cycle takes minutes and spends live Halo/TeamGPS calls + Azure gpt-5.4 tokens — hence manual, confirm-guarded, and single-flight. On machines without `markitdown` the registry step reports failed while the other steps still refresh Halo/TeamGPS data and the index.

### MarkItDown for Document Ingestion
* **Choice:** Integrated Microsoft's `markitdown` library in the build pipeline.
* **Why:** Avoids writing custom text parsers for different file types (`.docx`, `.pptx`, `.pdf`). It outputs clean Markdown that is easily consumed by the LLM and rendered consistently in the frontend transcript/deck tabs.

### Halo Attachment Two-Mode Download
* **Choice:** `halo.download_attachment` handles two delivery modes transparently: some attachments return inline raw bytes; others return a JSON envelope `{"link": <pre-signed CDN URL>}` that must be followed with a second HTTP request.
* **Why:** HaloPSA's attachment API changed behaviour across versions and partner configurations. Handling both modes in one function keeps `build_partner.py` clean.

### Vanilla Frontend Stack + Vendored Chart.js
* **Choice:** Pure HTML5, CSS, and modern ES6 JavaScript (inline `<script>` in `index.html`, plus `partner.js`) with Chart.js 4.4.4 vendored locally under `vendor/`.
* **Why:** Eliminates React/Angular/Vue build steps. The frontend runs instantly on a basic HTTP file server (`server.py`) and works fully offline — no CDN dependency at runtime.
* **History:** The original portfolio SPA (`portfolio.js` + a separate `portfolio.html`) was retired; its Partner 360 list view now lives inside `index.html` as a second view (`view-partners`) alongside the Executive Overview, switched via the sidebar.

### Embedded Exec-Overview Array vs. Runtime Fetch (TWO data layers — keep in sync)
* **Choice:** `index.html` carries a **hardcoded `const partners = [...]` array** inside its inline `<script>`, mirrored from `data/_index.json`. Only `partner.html`/`partner.js` fetch JSON at runtime.
* **Why:** The Executive Overview renders instantly with zero fetch latency and survives being opened as a plain file; the data is build-time anyway.
* **Tradeoff / gotcha:** Any change to the partner set must land in **both** places or the two views disagree. The injection scripts own this sync:
  * `scripts/build_real_partners.py` splices real-partner objects between `// ---- BEGIN/END real partners ... ----` markers in `index.html` (replace-by-slug, append if new); `extract.build_all --reindex` regenerates `data/_index.json` from every per-partner cache.
  * `scripts/refresh_exec_row.py <slug>|--all|--remove <slug>` re-renders (or, with `--remove`, deletes) exec-overview rows from the rebuilt `data/{slug}.json` caches — needed because the registry partners' rows live in the **static** part of the array (outside the markers), where `build_real_partners.py` never touches them and would otherwise append a duplicate. `--all` runs as the sync cycle's `exec-rows` step so a full sync keeps every embedded row in lockstep with the caches. Single-partner refresh recipe: `build_all --only <Name>` → `build_all --reindex` → `refresh_exec_row.py <slug>`.
  * Each exec-overview object carries an explicit `slug` field because slug ≠ `slugify(display name)` for several real partners (`MSP Corp` → `mspcorp`, `RealTime, LLC` → `realtime-it`, etc.) — never derive the drilldown link from the display name client-side.

### Portfolio Aggregates Derived In-Process
* **Choice:** `extract/portfolio.py` builds all four chart datasets (risk distribution, weekly sentiment trend, feedback mix, top themed churn drivers) from the per-partner caches already in memory during `build_all.py`, with no additional API calls.
* **Why:** Keeps the build a single pass and avoids storing or re-fetching raw CSAT/NPS at the portfolio level. The themed top-drivers aggregation uses severity-weighted scoring of the gpt-5.4 `drivers[].factor` text against a curated keyword taxonomy.

---

## 5. Security & Secret Management

* **Configuration:** Credentials for Azure Foundry, HaloPSA, and TeamGPS are loaded via environment variables or a `.env` file through `extract/config.py`.
* **Important:** Live credentials should not be checked into Git. The project uses `.env.example` to track the expected keys. Active keys inside the SOP documents must be rotated and moved to a dedicated secrets manager prior to production deployment.
* **Current state (beta):** `extract/config.py` ships **live fallback secrets baked into source** (Halo client-secret, TeamGPS API key, Azure OpenAI key) so the engine runs out-of-the-box. These must be rotated and externalised before any wider deployment.

---

## 6. Data Sources, Connectors & Access Tiers

The engine integrates **three external systems plus local files**, all via direct REST calls (no managed connector/iPaaS layer). The table below also flags the account tier each currently runs on versus what a scaled/production deployment needs.

| Source | How it's accessed | Auth used today | Tier / scaling concern |
|---|---|---|---|
| **HaloPSA** (`extract/halo.py`) | Direct REST to `itbd.halopsa.com/api` | OAuth2 **client_credentials** app, read scope. (The claude.ai-side equivalent connector is named `HaloPSA_mcp_test` — a test instance.) | Works on the existing Halo tenant. Needs a **sanctioned, named API application** with least-privilege scope and rotating secrets — not a personal/test app registration. |
| **TeamGPS Open API** (`extract/teamgps.py`) | Direct REST to `api.team-gps.net/open-api/v1` | Single static **`X-API-KEY`** | Account-scoped personal key. For scale: an **org-issued key**, stored in a secret manager, with rotation. No server-side company filter on NPS (full set pulled and filtered locally). |
| **Azure OpenAI — gpt-5.4** (`extract/ai.py`) | Azure OpenAI SDK | API key against endpoint `leonwisoky.cognitiveservices.azure.com` | Appears to be an **individual/personal Azure Foundry resource**. Production needs an **enterprise Azure subscription**: provisioned throughput/quota, content filtering, private networking, and a data-processing agreement (partner notes are sent to the model). |
| **Local `.docx` transcripts & deck PDFs/PPTX** | Filesystem | none | Converted with the open-source **MarkItDown** library (no account). Transcripts are manually exported and dropped into `Transcripts/{Partner}/`. |
| **Chart.js 4.4.4** | Vendored locally under `vendor/` | none | No CDN/account dependency at runtime. |

> **No managed connectors are used in the deployed code.** All integration is hand-rolled `requests`/SDK calls with keys in `config.py`. If this is instead run through Claude/claude.ai connectors (HubSpot, QuickBooks, Microsoft 365, Atlassian, etc.), each of those is a separate OAuth app that would require **business/enterprise tenant authorization** — none are wired into PartnerPulse today.

---

## 7. External / Web Data Sources

**None.** PartnerPulse is **100% internal-data-driven**. Churn risk is inferred entirely from:

* Halo account-team risk flags (`CFMDERAG`, `CFCancelationRisk`, `CFHealthReason`, `CFNextStep`, SIP ticket),
* TeamGPS CSAT/NPS,
* meeting notes, decks, and local transcripts.

There is **no outside corroboration** of actual business loss or gain — no public-filings, news, WHOIS/domain, Crunchbase/LinkedIn, billing/revenue, or contract-system feed is consulted. The model's "risk" is a read of *internal sentiment and the account team's own flags*, **not** a confirmed record of whether a partner grew, shrank, or left. Treat the score as an early-warning signal, not ground truth on revenue impact.

---

## 8. Data Integrity Observations (source-data quality)

These are limitations in the **upstream Halo/TeamGPS data**, not bugs in the engine — but they cap how reliable the output can be, and the engine already compensates for several of them with heuristics.

1. **SIP ticket subjects have no standard format.** Across the 33 true SIP tickets (Halo ticket type 99) the summary field is free-text and wildly inconsistent: `"ITBD | Logically | Mazid | SIP"`, `"SIP - F12"`, `"Granite | Service Improvement Plan | Sophia Doctolero"`, `"Netgain Technologies - SIP 2026"`, `"Pritchard Industries - Helpdesk Resources and service Improvement Plan"`, and even `"Test"` and `"Baroan Technologies was acquired by Thrive NextGen…"` (a type-99 ticket with no SIP keyword at all). Pipe-, dash-, and prose-delimited styles all coexist; "SIP", "Service Improvement Plan", "Improvement Plan" and "Performance Improvement Plan/PIP" are used interchangeably. This is why `halo.count_sips` matches three search terms *and* filters client-side rather than trusting any naming convention.
2. **SIPs are filed against the wrong account.** 11 of 33 SIPs are saved under client_id 12 = **"IT by Design" (ITBD's own record)** rather than the partner they concern — the partner is named only in the free-text summary (e.g. `"OutsourceIT | Service Improvement Plan"`, `"ITBD | Logically | Emman | SIP"` both sit under ITBD, not the partner). The engine recovers these with a second "bucket B" pass that scans ITBD's own record for the partner name in the summary, but anything that doesn't name the partner is unattributable. (Operationally this is the *"logged under the account name but the correct account/contact isn't selected"* problem.)
3. **No reliable closed flag.** Halo `/api/Status` exposes no `isclosed` boolean (type 0 holds both "New" and "Closed"). Open-vs-closed SIP state is derived by a **name heuristic** against a terminal-status set — approximate, not authoritative.
4. **Ticket linkage / contact gaps.** List rows carry IDs only (no decoded names), `deadlinedate` is a `1900-01-01` null-sentinel, and duplicate identical timestamps appear on bulk-created SIPs — so ticket dates and links can't be taken at face value.
5. **Updates aren't consistently in the internal notes.** The AI only "sees" the conversation that was written into Halo **Actions** as properly-formatted notes (the engine keys on markers like "meeting summary"/"action items"). Status changes, action-item closures, and ad-hoc updates that aren't captured as a structured note are invisible to the analysis — there is no field that records "action item X closed on date Y", so progress between reviews can be under-counted.
6. **Name/identity drift.** The same partner appears under varying spellings across systems ("Proda Technology" vs "Proda Technologies", "NetGain Technology LLC" vs "Netgain", "Focus technology"/"Focus Techonology"), and the dashboard slug is derived from the registry name, **not** the Halo client name (e.g. `MSPCorp` file vs `MSP Corp` client) — a known cross-link gotcha.

---

## 9. Data Composition — Real Only

All data is **real**, pulled live from Halo/TeamGPS + gpt-5.4: **38 partners** —

* the 10 registry partners in `extract/partners.py` (Logically, MSPCorp, Liongard, Milner, ION247, Realtime IT, Stasmayer, Premier, Alliance, Computer Weavers),
* plus 28 in `scripts/build_real_partners.py` NEW: the original 8 extras (Netgain, F12, RedHelm-1Path, Proda, Amoskeag, Granite Networks, Secure Future, Atlantic PC) and 20 added 2026-06-12 from the transcript-access audit (Continuous Networks, APM IT Solutions, Matador Networks, Vitis Tech, Community IT, PEI, Prevare LLC, Perfect Cloud Solutions, Dependable Solutions, Pegasus Technology Solutions, Boomtown CIO, C&W Computers, Networking Now, Galactica Cybersecurity, ICSI, Infopathways, NerdsToGo, CMIT Solutions Stamford, Vistitude, Mission Technology).
* A **transcript-only** build path exists (`client_id=None` in NEW skips Halo/TeamGPS; the AI works from call transcripts alone) but is currently unused: its one user, "CW Now", was actually Halo client 39 **C&W Computers** (their domain is cwnow.com) and was corrected to the full Halo + TeamGPS path on 2026-06-12.

> **History:** until 2026-06-11 the cache also held ~36 synthetic demo partners (seeded by a since-deleted `gen_demo_partners.py`) to stress-test the portfolio at scale. All demo data was wiped from the codebase — partner JSONs, the injected exec-overview block, and the seeder itself. If a partner carrying `"demo": true` ever reappears, something is restoring stale data.
