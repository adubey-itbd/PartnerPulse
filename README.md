# PartnerPulse

Executive **partner-health & churn-risk dashboard** for ITBD (a white-label NOC/helpdesk
provider). It consolidates every MSP partner into one portfolio view, scores churn risk with
**Grok `grok-4-1-fast-reasoning`** (via an Azure AI Foundry OpenAI-compatible endpoint), and
drills into per-partner detail: CSAT/NPS, service-review meeting
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
builds every partner's data + Grok churn analysis (~5 min, live API calls), then starts the
dashboard and opens it at **http://localhost:8000/**.

Useful flags: `-Rebuild` (force a fresh data build), `-Port 8080`, `-NoBrowser`.

## Manual usage

```powershell
pip install -r requirements.txt
python -m extract.build_all                  # build all partners + AI + portfolio index
python -m extract.build_partner "Logically"  # build a single partner
python -m extract.build_all --reindex        # rebuild data/_index.json from existing JSONs (no fetch)
python scripts/build_real_partners.py        # pull the extra real Halo clients (writes their data/*.json)
python scripts/build_overview.py             # build data/_overview.json (the dashboard feed) from the caches
python scripts/build_csat_recon.py           # build data/_csat_recon.json (CSAT Reconciliation view) from _overview.json + Halo
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
  ai.py                       Grok grok-4-1-fast-reasoning churn analysis via Azure AI Foundry
                              OpenAI-compatible endpoint (OpenAI SDK) — risk, drivers, remediation
  build_partner.py            orchestrates one partner -> data/{slug}.json
  portfolio.py                derives portfolio aggregates from per-partner caches
  build_all.py                all partners + AI + data/_index.json roll-up

scripts/                      operational entry-point scripts
  build_real_partners.py      pull a hardcoded set of real Halo clients (+ transcripts,
                              + AI analysis) into their data/{slug}.json caches
  build_overview.py           roll the caches up into data/_overview.json — the feed the
                              dashboard fetches (SIP/action/NPS rollups, coverage window).
                              Honours data/_demo_roster.json (allowlist) when present.
  build_csat_recon.py         build data/_csat_recon.json — the CSAT Reconciliation view:
                              monthly CSAT sent (Halo tickets 36/163/164) vs received
                              (TeamGPS, joined by ticket_id), per partner/AM/RM/Site.
  audit_data.py               data-integrity audit across partners (uncounted SIPs,
                              missing AI, empty CSAT, stale last-call, unmatched
                              transcript folders, feed integrity); allowlist-aware
  cloud_sync.py               Cloud Run Job entrypoint: GCS state pull → full build cycle
                              → upload_firebase_data → state push (the nightly pipeline)
  upload_firebase_data.py     publish the sharded data tree → Cloud Firestore
  seed_secrets.py             load Halo/TeamGPS/AI (ai-api-key)/Graph keys → Secret Manager
  refresh_exec_row.py         DEPRECATED — no-op against the data-driven dashboard
                              (kept for rollback; use build_overview.py instead)
  setup_graph_transcript_access.ps1   for IT: completes the Graph app-registration
                              provisioning for transcript ingestion (see
                              docs/IT-Request-Graph-Transcript-Access.md)
  probe_graph_transcripts.py  acceptance test for that app registration (token ->
                              meeting -> transcript fetch; GRAPH_* creds from .env)

index.html                    AI-Driven Operational Intelligence — Executive Overview +
                              Partner 360 + CSAT Reconciliation, data-driven
                              (fetches data/_overview.json + data/_csat_recon.json)
partner.html / partner.js     per-partner detail (?partner=slug): Overview, AI Insights,
                              Action Tracker, CSAT & NPS, Transcripts, Service Decks
feedback.html                 PUBLIC, ungated feedback form (shareable link); writes the
                              create-only Firestore `feedback` collection (no auth.js)
refresh.js                    renders the "Last sync" freshness stamp (the manual "Sync
                              Data" button was removed 2026-06-16 — refresh is the nightly
                              cloud job; server.py's sync API remains for local dev only)
auth.js / firebase-config.js  prod auth gate + Firestore data layer (DEV no-op on localhost)
firebase.json / .firebaserc / firestore.rules / firestore.indexes.json   Firebase config
Dockerfile / .dockerignore / .gcloudignore   Cloud Run Job pipeline image
styles.css                    design system for partner.html (claymorphic light theme,
                              matches index.html's inline styles, which it does not share)
vendor/
  chart.umd.min.js            Chart.js 4.4.4 vendored locally (no CDN)
server.py                     dependency-free local dev server (no-cache) + manual sync API
                              (POST /api/refresh, GET /api/refresh/status -> data/_sync.log)
data/                         generated caches (gitignored) — built by the engine
Transcripts/                  meeting transcripts, one folder per partner — .docx
                              (manual Teams exports) + .vtt (Graph transcript pulls)
docs/                         architecture.md, Data-Schema.md, changelog.md, SOP docs (incl.
                              Firebase-Deploy-SOP, Cloud-Pipeline-SOP), LLM-SOP.md, archive/
legacy/                       superseded single-partner files (app.js, data.js)
CLAUDE.md                     LLM working context — commands, gotchas, doc-update rules
hooks/pre-commit              blocks code commits that don't update docs/changelog.md
                              (enabled via `git config core.hooksPath hooks`; setup.ps1 does this)
```

Data sources per partner: HaloPSA (client metadata, RAG/risk custom fields, review-ticket
meeting notes, deck attachments), TeamGPS (CSAT & NPS), local call transcripts (`.docx`
Teams exports + `.vtt` Graph pulls), and the service-review decks (PDF/PPTX → Markdown). Bulk ticket SLA/status is intentionally excluded —
for the white-label NOC model those are end-customer metrics, not partner-churn signals.

## Production & roadmap

Deployed on **Firebase Hosting** (email/password sign-in, verified `@itbd.net`) reading
**Cloud Firestore**; the pipeline runs as a nightly **Cloud Run Job** (Cloud Scheduler,
21:00 America/New_York) that rebuilds and republishes Firestore — no local machine in the
loop. Secrets are in **Secret Manager**. See `docs/Data-Schema.md` (end-to-end data map),
`docs/Firebase-Deploy-SOP.md`, and `docs/Cloud-Pipeline-SOP.md`.

Outstanding:

- **Rotate the reused API keys** (Halo/TeamGPS/AI/Graph) in their source systems and
  publish new Secret Manager versions, then remove the in-repo `extract/config.py` fallbacks.
