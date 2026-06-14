# PartnerPulse — Demo Architecture Baseline

A copy-paste baseline for generating a system-architecture diagram (e.g. in Claude web)
for executive demos. Grounded in what's actually built (see `CLAUDE.md`). Two parts:
(1) the prompt to paste, (2) the structured content that grounds it.

---

## PART 1 — The prompt to paste into Claude web

> **Create a single-page system-architecture diagram** (clean, executive-friendly,
> left-to-right or top-to-bottom flow with labeled boxes and arrows) titled:
>
> **"PartnerPulse — AI-Driven Operational Intelligence — System Architecture"**
>
> Use the layered content below. Render it as a layered block diagram: each numbered
> section is a horizontal band of boxes, with arrows showing data flowing down from
> sources → ingestion → processing → AI scoring → outputs. Use a color legend:
> green = live connector, blue = AI/scoring engine, purple = governance,
> amber = feedback loop. Keep it clean and presentation-ready for an executive demo.
> Add small italic captions under each box for the tool/protocol used.

Then paste **Part 2** underneath that prompt.

---

## PART 2 — The structured content (the "what we built")

```
TITLE: PartnerPulse — AI-Driven Operational Intelligence
SUBTITLE: Executive partner-health & churn-risk dashboard for ITBD
          (white-label NOC/helpdesk; "partners" = MSPs)

─────────────────────────────────────────────
LAYER 1 — SOURCE SYSTEMS (live data we pull from)
─────────────────────────────────────────────
• HaloPSA              — Tickets, SLA breaches, contracts/renewals,
                         SIP action trackers, meeting minutes
                         (REST API + OAuth)
• TeamGPS              — CSAT, NPS, employee scorecards, goals, 1:1 reviews
                         (MCP connector, daily pull)
• SharePoint           — Partner data tree, WBR/MBR/QBR decks,
                         per-partner subfolders (MS Graph)
• MS Teams / Stream    — Service-review call transcripts & recordings
                         (MS Graph app-only pull, ~90-day retention)
• QuickBooks           — AR aging, financial exposure (MCP connector)
• External web         — News, M&A, layoffs, leadership change
                         (WebSearch / NewsAPI)

─────────────────────────────────────────────
LAYER 2 — INGESTION & CONNECTORS
─────────────────────────────────────────────
• Scheduled build pipeline (Python: extract.build_all)
• MCP servers + MS Graph app registration + HaloPSA OAuth
• markitdown — converts .docx/.vtt transcripts to text
• Incremental sync: cached results reused when inputs unchanged

─────────────────────────────────────────────
LAYER 3 — NORMALIZATION & FEATURE EXTRACTION
─────────────────────────────────────────────
• Partner-name matcher (TeamGPS ↔ SharePoint ↔ Halo ↔ QuickBooks IDs)
• Survey features      — CSAT split + sample size, NPS promoter %
• Service features     — SIP open/overdue counts, ticket health
• Sentiment features   — transcript tone / call-tone analysis
• Financial features   — AR aging, renewal timing, revenue exposure
• External signals     — M&A / layoff / leadership-change flags

─────────────────────────────────────────────
LAYER 4 — AI SCORING ENGINE  (the core)
─────────────────────────────────────────────
• Azure OpenAI gpt-5.4 churn analysis
• Outputs per partner: churn-risk score (0–100), top risk
  contributors, "why-it-changed" narrative, recommended actions
• Cached/keyed by input hash to prevent run-to-run score drift
• Tier breakpoints: Healthy / Watch / At-Risk / Critical

─────────────────────────────────────────────
LAYER 5 — DATA CACHE (build-time output)
─────────────────────────────────────────────
• Per-partner JSON caches  (data/{slug}.json)
• Portfolio index          (data/_index.json)
• Dashboard feed           (data/_overview.json)

─────────────────────────────────────────────
LAYER 6 — WHAT PEOPLE SEE  (frontend)
─────────────────────────────────────────────
• Executive Overview  — portfolio NPS, churn-risk by tier,
                        top movers, action queue
• Partner 360         — per-partner drilldown: sentiment trend,
                        SIP/ticket status, top-5 risk contributors,
                        CSAT comments, recommended mitigation
• Framework-free HTML/JS, served from repo root, no embedded data
  (fully data-driven from JSON)
```

---

## Demo talking points

- **One-liner that lands:** *"It pulls from every system we already use — Halo,
  TeamGPS, Teams calls, QuickBooks, SharePoint — and uses AI to turn that into a single
  churn-risk score per partner, with the reason it changed."*
- **All data is real** — no synthetic/demo partners; running against live Halo clients.
- **MCP connectors** (TeamGPS, QuickBooks, MS Graph) are the modern integration story —
  the impressive part for a technical audience.
- **Feedback loops** (SDM overrides, intervention outcomes → weight tuning) are roadmap
  (V2/V3), not built — label them as roadmap to stay honest.
