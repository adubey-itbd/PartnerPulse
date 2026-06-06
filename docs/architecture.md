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
        Engine[build_all.py / build_partner.py]
        Portfolio[portfolio.py]
        MID[MarkItDown Parser]
        Azure[Azure Foundry gpt-5.4]
    end

    subgraph Data Cache (Gitignored)
        Index[data/_index.json]
        PartnerC[data/{partner-slug}.json]
    end

    subgraph Presentation Layer (Frontend)
        IndexUI[index.html / portfolio.js]
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
    
    Server -->|Serve Assets| IndexUI
    Server -->|Serve Assets| DetailUI
    Index -->|Read Data| IndexUI
    PartnerC -->|Read Data| DetailUI
```

---

## 2. Ingestion & AI Engine Pipeline

The Python engine orchestrates the compilation of raw partner telemetry into a unified profile. The pipeline runs as follows:

1. **Partner Registry Resolution (`extract/partners.py`):** Resolves human-readable partner names to their respective HaloPSA Client IDs and TeamGPS company identifiers.
2. **Telemetry Fetching:**
   * **HaloPSA (`extract/halo.py`):** Queries custom RAG/risk fields, client metadata, review tickets, meeting notes, and attachments. Attachments support two delivery modes: inline raw bytes, or a JSON `{"link": <pre-signed CDN URL>}` response that must be followed — both handled transparently in `halo.download_attachment`.
   * **TeamGPS (`extract/teamgps.py`):** Fetches CSAT (filtered by company) and NPS (filtered by email domain). The full NPS set is fetched once in `build_all.py` and passed to each partner build to avoid redundant API calls.
3. **Document Extraction (`extract/transcripts.py`):** Uses Microsoft's `markitdown` library to convert local `.docx` meeting transcripts, PowerPoint decks, and PDF reports into Markdown text.
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
| `client` | `id`, `name`, `vip`, `rag`, `cancel_risk`, `health_reason`, `next_step`, `sip_ticket`, `service_line`, `account_manager` |
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
* **Tradeoff:** The dashboard displays cached data. Updates are not live and must be triggered via a recurring task (e.g., cron job) or manual execution of `python -m extract.build_all`.

### MarkItDown for Document Ingestion
* **Choice:** Integrated Microsoft's `markitdown` library in the build pipeline.
* **Why:** Avoids writing custom text parsers for different file types (`.docx`, `.pptx`, `.pdf`). It outputs clean Markdown that is easily consumed by the LLM and rendered consistently in the frontend transcript/deck tabs.

### Halo Attachment Two-Mode Download
* **Choice:** `halo.download_attachment` handles two delivery modes transparently: some attachments return inline raw bytes; others return a JSON envelope `{"link": <pre-signed CDN URL>}` that must be followed with a second HTTP request.
* **Why:** HaloPSA's attachment API changed behaviour across versions and partner configurations. Handling both modes in one function keeps `build_partner.py` clean.

### Vanilla Frontend Stack + Vendored Chart.js
* **Choice:** Pure HTML5, CSS, and modern ES6 JavaScript (`portfolio.js`, `partner.js`) with Chart.js 4.4.4 vendored locally under `vendor/`.
* **Why:** Eliminates React/Angular/Vue build steps. The frontend runs instantly on a basic HTTP file server (`server.py`) and works fully offline — no CDN dependency at runtime.

### Portfolio Aggregates Derived In-Process
* **Choice:** `extract/portfolio.py` builds all four chart datasets (risk distribution, weekly sentiment trend, feedback mix, top themed churn drivers) from the per-partner caches already in memory during `build_all.py`, with no additional API calls.
* **Why:** Keeps the build a single pass and avoids storing or re-fetching raw CSAT/NPS at the portfolio level. The themed top-drivers aggregation uses severity-weighted scoring of the gpt-5.4 `drivers[].factor` text against a curated keyword taxonomy.

---

## 5. Security & Secret Management

* **Configuration:** Credentials for Azure Foundry, HaloPSA, and TeamGPS are loaded via environment variables or a `.env` file through `extract/config.py`.
* **Important:** Live credentials should not be checked into Git. The project uses `.env.example` to track the expected keys. Active keys inside the SOP documents must be rotated and moved to a dedicated secrets manager prior to production deployment.
