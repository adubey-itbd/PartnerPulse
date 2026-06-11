# PartnerPulse

Executive **partner-health & churn-risk dashboard** for ITBD (a white-label NOC/helpdesk
provider). It consolidates every MSP partner into one portfolio view, scores churn risk with
**Azure Foundry gpt-5.4**, and drills into per-partner detail: CSAT/NPS, service-review meeting
notes, AI-extracted action items, call transcripts, and the converted service-review decks.

> ⚠️ **Private repo.** `extract/config.py` and the two SOP docs contain live API keys for
> convenience. Rotate them before this ever goes public, and move them to a secret manager for
> any real deployment.

## Quick start (fresh Windows machine)

Download/extract the repo, then from a PowerShell prompt in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

`setup.ps1` installs Python (via winget if missing), creates a `.venv`, installs dependencies,
builds every partner's data + gpt-5.4 churn analysis (~5 min, live API calls), then starts the
dashboard and opens it at **http://localhost:8000/**.

Useful flags: `-Rebuild` (force a fresh data build), `-Port 8080`, `-NoBrowser`.

## Manual usage

```powershell
pip install -r requirements.txt
python -m extract.build_all                  # build all partners + AI + portfolio index
python -m extract.build_partner "Logically"  # build a single partner
python -m extract.build_all --reindex        # rebuild data/_index.json from existing JSONs (no fetch)
python scripts/build_real_partners.py        # pull the extra real Halo clients + inject into exec overview
python scripts/gen_demo_partners.py          # seed 40 synthetic demo partners (scalability test)
python server.py                             # serve the dashboard at http://localhost:8000
```

## How it works

```
extract/                      Python extraction + AI engine
  config.py                   env-first secrets + paths
  partners.py                 partner registry (Halo client_id resolution by name)
  halo.py                     HaloPSA: client+custom fields, users, review tickets,
                              meeting notes, attachment list + two-mode download
  teamgps.py                  TeamGPS CSAT (company filter) + NPS (local domain filter)
  transcripts.py              MarkItDown: .docx transcripts + PDF/PPTX decks -> Markdown
  ai.py                       Azure Foundry gpt-5.4 churn analysis (risk, drivers, remediation)
  build_partner.py            orchestrates one partner -> data/{slug}.json
  portfolio.py                derives portfolio aggregates from per-partner caches
  build_all.py                all partners + AI + data/_index.json roll-up

scripts/                      operational entry-point scripts
  build_real_partners.py      pull a hardcoded set of real Halo clients + AI analysis
                              and inject them into the exec-overview partner array
  gen_demo_partners.py        seed 40 synthetic demo partners (scalability test)

index.html                    Executive Overview (Chart.js charts, embedded partner array)
partner.html / partner.js     per-partner detail (?partner=slug): Overview, AI Insights,
                              Action Tracker, CSAT & NPS, Transcripts, Service Decks
styles.css                    shared design system (light theme, dark sidebar nav)
vendor/
  chart.umd.min.js            Chart.js 4.4.4 vendored locally (no CDN)
server.py                     dependency-free local dev server (no-cache)
data/                         generated caches (gitignored) — built by the engine
Transcripts/                  local .docx meeting transcripts, per partner
docs/                         architecture.md, changelog.md, three SOP docs, LLM-SOP.md, archive/
legacy/                       superseded single-partner files (app.js, data.js)
CLAUDE.md                     LLM working context — commands, gotchas, doc-update rules
hooks/pre-commit              blocks code commits that don't update docs/changelog.md
                              (enabled via `git config core.hooksPath hooks`; setup.ps1 does this)
```

Data sources per partner: HaloPSA (client metadata, RAG/risk custom fields, review-ticket
meeting notes, deck attachments), TeamGPS (CSAT & NPS), local `.docx` transcripts, and the
service-review decks (PDF/PPTX → Markdown). Bulk ticket SLA/status is intentionally excluded —
for the white-label NOC model those are end-customer metrics, not partner-churn signals.

## Roadmap

- Deploy to Firebase Hosting + Cloud Functions; move secrets to Secret Manager.
