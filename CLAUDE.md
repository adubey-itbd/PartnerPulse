# CLAUDE.md — PartnerPulse

**AI-Driven Operational Intelligence** — executive partner-health & churn-risk dashboard
for ITBD (white-label NOC/helpdesk provider; "partners" are MSPs). Python build-time
pipeline (HaloPSA + TeamGPS + local docs → Grok `grok-4-1-fast-reasoning` churn
analysis → JSON caches)
+ framework-free HTML/JS frontend. ("PartnerPulse" is the legacy project name still used
in package/doc headers.)

**Production (since 2026-06-16):** the UI is hosted on **Firebase Hosting** behind
email/password sign-in restricted to a **named allowlist** of verified **`@itbd.net`**
accounts (a 6-person list since 2026-06-22, not the whole domain — kept in sync between
`firestore.rules` `isItbd()` and `auth.js` `ALLOWED_EMAILS`); all data is read from
**Cloud Firestore** (sharded) via `auth.js`; and the pipeline runs unattended as a
nightly **Cloud Run Job** (Cloud Scheduler, 21:00 America/New_York) that rebuilds and
republishes Firestore. The churn AI is **Grok (`grok-4-1-fast-reasoning`)** served via
an **Azure AI Foundry OpenAI-compatible endpoint** (OpenAI SDK, `base_url` + API key,
synchronous chat-completions) — this replaced the prior Azure gpt-5.4 (Batch-only
deployment, couldn't serve synchronous per-partner calls) on 2026-06-18. **Local dev
is unchanged** — `server.py` + `data/*.json`, no auth
(`auth.js` auto-detects localhost). See `docs/Data-Schema.md` (end-to-end source→store
map), `docs/Firebase-Deploy-SOP.md`, and `docs/Cloud-Pipeline-SOP.md`.

## Documentation mandate

**After ANY change, follow `docs/LLM-SOP.md`** — it lists every doc, when each must
be updated (changelog entries are required for every behavioural change), and the
repo invariants that code and docs must keep in sync. That SOP and this file are
themselves maintained under the same rule.

Enforced by `hooks/pre-commit` (`core.hooksPath=hooks`, set by `setup.ps1`): commits
touching code without staging `docs/changelog.md` are blocked. Never bypass it with
`--no-verify` or `SKIP_DOCS_CHECK=1` — update the docs instead.

## Commands

```powershell
python -m extract.build_all                  # build all partners + AI + portfolio index (INCREMENTAL: reuses cached AI+decks when inputs unchanged)
python -m extract.build_all --force-ai       # same, but re-run Grok for every partner (ignore AI cache)
python -m extract.build_all --only "Logically"  # build one partner (DO run via build_all, not build_partner — the latter skips AI)
python -m extract.build_all --reindex        # rebuild data/_index.json from existing JSONs (no fetch)
python scripts/build_real_partners.py        # extra real Halo clients (writes their data/*.json)
python scripts/build_overview.py             # rebuild data/_overview.json (the dashboard feed) from caches
python scripts/build_csat_recon.py           # rebuild data/_csat_recon.json (CSAT Reconciliation view); reads _overview.json + hits Halo for sent-side CSAT tickets
python scripts/audit_data.py                 # data-integrity audit (SIPs, AI, CSAT, last-call, transcript folders, feed)
#  single-partner refresh: build_all --only <Name> -> build_all --reindex -> build_overview.py
#  (refresh_exec_row.py is DEPRECATED — the dashboard is data-driven, no embedded array to refresh)
python server.py [port]                      # dev server, default http://localhost:8000
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # fresh-machine bootstrap
# --- Cloud / deploy (prod; full runbooks in docs/Firebase-Deploy-SOP.md + docs/Cloud-Pipeline-SOP.md) ---
python scripts/upload_firebase_data.py       # publish data/_overview.json + caches → Firestore (sharded)
python scripts/seed_secrets.py               # load Halo/TeamGPS/AI (ai-api-key)/Graph keys → Secret Manager
firebase deploy --only hosting               # ship the UI (and --only firestore:rules for rule changes)
gcloud run jobs execute partnerpulse-nightly --region=us-central1   # force an off-cycle data refresh
```

No test suite. Verify changes by running the relevant build script and loading the
dashboard. Full builds hit live APIs + the LLM (~5 min) — prefer single-partner or
`--reindex` runs.

## Layout

- `index.html` — Executive Overview + Partner 360 + **CSAT Reconciliation** views
  (sidebar-switched). **Fully data-driven: it `fetch`es `data/_overview.json` (Exec
  Overview + Partner 360) and `data/_csat_recon.json` (CSAT Reconciliation, lazy on
  first open) at runtime — there is NO embedded partner array** (changed 2026-06-13;
  see changelog beta.8). Self-contained inline `<style>` + `<script>`; does NOT load
  `styles.css` (gotcha 7). Uses Chart.js (vendored in `vendor/`) for the Exec-Overview
  risk-ranking bars and the CSAT sent/received combo chart.
- `data/_overview.json` — the dashboard feed, built by `scripts/build_overview.py`
  from `data/_index.json` + the per-partner `data/{slug}.json` caches (SIP totals,
  open/overdue action counts, real per-partner + portfolio NPS, CSAT split with sample
  size, honest call tone, themes, coverage window). Final step of the sync cycle.
- `data/_csat_recon.json` — the CSAT Reconciliation feed, built by
  `scripts/build_csat_recon.py` AFTER `build_overview.py`. Per DES/MDE partner and
  per month it reconciles CSAT **sent** (Halo tickets, types 36/163/164, one ticket =
  one sent; survey month from the ticket summary, year from `dateoccurred`) against
  CSAT **received** (TeamGPS responses in the `data/{slug}.json` caches, joined by
  `ticket_id`). Carries per-row Account Manager / Regional Manager / Site (Halo
  `accountmanagertech_name` / `regmanagertech_name` / `CFAccountSite`) so the view can
  re-group client-side. Published to Firestore as the single doc `meta/csatRecon`.
- `partner.html` + `partner.js` — per-partner drilldown (`?partner=<slug>`), fetches
  `data/{slug}.json` at runtime. Styled by `styles.css` (which `index.html` does
  NOT load — gotcha 7); Chart.js vendored in `vendor/`. **Unchanged by the beta.8 redesign.**
- `feedback.html` (NEW 2026-06-17) — a **public, ungated** feedback form, self-contained
  (own inline `<style>`, ITBD brand palette). Loads `firebase-config.js` + the firestore
  compat SDK but **NOT `auth.js`** (no sign-in — it's meant to be shared with anyone).
  Writes one auto-id doc to the Firestore **`feedback`** collection, which `firestore.rules`
  allows **create-only** (validated + size-capped, no client reads — review in the Firebase
  console). It is the **only** client-writable Firestore path. A "Share feedback" link in
  `index.html`'s sidebar footer opens it in a new tab.
- `refresh.js` — now ONLY renders the "Last sync" timestamp (`#sync-stamp`, both
  pages; = `portfolio.generated_at`, prod from Firestore `meta/overview` via
  `PP_AUTH.lastSyncStamp`, local from `data/_index.json`). **The manual "Sync Data"
  button was REMOVED 2026-06-16** when the pipeline moved to the cloud — there is no
  in-app sync anymore. The now-unused `.sync-btn`/`.sync-panel` CSS (in BOTH
  `styles.css` and `index.html`'s inline `<style>` — gotcha 7) is left in place,
  harmless. `server.py`'s `POST /api/refresh` sync API still exists for LOCAL dev use
  but nothing in the UI calls it.
- **Cloud pipeline (NEW 2026-06-16, see `docs/Cloud-Pipeline-SOP.md`)** — the cycle
  (pull_graph_transcripts --write → build_all → build_real_partners → build_all
  --reindex → build_overview → build_csat_recon → **upload_firebase_data.py**) runs unattended as a
  **Cloud Run Job** (`partnerpulse-nightly`) on a **Cloud Scheduler** trigger at
  **21:00 America/New_York**. Entrypoint `scripts/cloud_sync.py`; image from
  `Dockerfile`; secrets from Secret Manager (`scripts/seed_secrets.py`); `data/` +
  `Transcripts/` persisted in a GCS state bucket so the Grok AI cache + transcript
  history survive between runs. **Builds are INCREMENTAL** — Grok churn analysis
  and deck conversion are cached (keyed by input hash / attachment id) and skipped
  for unchanged partners, so a re-sync mostly just re-fetches Halo/TeamGPS; this keeps
  steps under the 30-min `STEP_TIMEOUT_S` and stops run-to-run score drift. (Transcript-
  pull caveats: skips manual-`.docx` folders, QBRs 403, ~90-day Teams content retention.)
- `extract/` — pipeline library package (config, halo, teamgps, transcripts, ai,
  build_partner, build_all, portfolio). `ai.py` calls Grok `grok-4-1-fast-reasoning`
  over the Azure AI Foundry OpenAI-compatible endpoint (synchronous OpenAI SDK; config
  `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL` in `extract/config.py` — the old
  `AZURE_OPENAI_*` constants are gone). Secrets: env/.env first, live fallbacks
  baked in `extract/config.py` (beta only — never copy them elsewhere).
- `scripts/` — operational entry points; they sys.path-shim the repo root, run them
  from anywhere. New one-off scripts go here, library code goes in `extract/`.
  `build_overview.py` builds the dashboard feed `data/_overview.json` from the caches
  (honours the demo allowlist — see gotcha 8). `build_csat_recon.py` builds the CSAT
  Reconciliation feed `data/_csat_recon.json` (runs after `build_overview.py`; reads its
  partner set, then hits Halo for the sent-side CSAT tickets + AM/RM/Site per client).
  `audit_csat_recon.py` cross-checks that feed against source for every partner (drift /
  impossible values / month-shift → `data/_csat_audit.json`). **Never run two Halo-hitting
  builds/audits concurrently** — Halo rate-limits and returns 500s (and on Windows the
  Store Python runs as `python3.13.exe`, so `Stop-Process -Name python` does NOT kill a
  stray build). `audit_data.py` is
  a data-integrity audit (run after a sync) flagging uncounted SIPs, missing AI, empty
  CSAT, stale/absent last-call, unmatched transcript folders, and feed/index mismatch;
  allowlist-aware. `refresh_exec_row.py` is DEPRECATED (no-op against the data-driven
  dashboard; kept for rollback to the `backups/` copy).
  `build_real_partners.py` NEW is the partner roster beyond the registry (70
  entries — the full DES/MDE book from Halo report 364 "DES RAG Status",
  filter `Area.CFMDERAG >= 1`, as expanded 2026-06-15); `client_id=None` marks a
  transcript-only partner with no Halo record
  — Halo/TeamGPS skipped, AI runs on call transcripts alone (path currently
  unused: its one user "CW Now" turned out to be Halo client 39 "C&W Computers",
  corrected 2026-06-12). `setup_graph_transcript_access.ps1` is for IT, not the
  pipeline: finishes the Graph app-registration provisioning (permissions +
  access policies — see `docs/IT-Request-Graph-Transcript-Access.md` § Outcome);
  `probe_graph_transcripts.py` is its acceptance test (token → meeting →
  transcript fetch). `pull_graph_transcripts.py` is the bulk transcript
  ingester — app-only Graph pull of partner service calls into
  `Transcripts/{Partner}/` with NO attendee constraint (dry-run by default,
  `--write` to save); Data-Extraction-SOP §1 Option D. Note Teams keeps
  transcript **content ~90 days** (older calls list but 404 on content), so run
  it monthly. Graph creds: `GRAPH_*` vars in `.env`.
- `data/` — generated, gitignored (partner JSONs, `_index.json`, `_overview.json`,
  `_demo_roster.json` (demo allowlist — gotcha 8), `decks/`, `_sync.log`). Never write
  generated artifacts to the repo root.
- `backups/` — saved copies of replaced dashboards for rollback, e.g.
  `index_pre-AIODI_2026-06-13.html` (the pre-redesign `index.html`).
- `docs/` — architecture, changelog, 3 API/extraction SOPs, LLM-SOP, `archive/`
  (frozen, never edit). `Transcripts/` — input .docx/.vtt, one folder per
  partner. `legacy/` — dead code, kept.

## Critical gotchas

1. **Single data source (changed 2026-06-13):** `index.html` is data-driven — it
   `fetch`es `data/_overview.json` (built by `scripts/build_overview.py`). There is **no
   embedded `const partners` array** anymore, so the old two-layer drift is gone. To
   refresh the dashboard after a data change, run `build_overview.py` (or let the
   nightly Cloud Run Job run the full cycle). Partner-set changes: `build_real_partners.py` (writes the
   JSONs) → `build_all --reindex` (`_index.json`) → `build_overview.py` (`_overview.json`).
2. **`build_real_partners.py` no longer injects into `index.html`** (the BEGIN/END
   marker block is gone with the embedded array); `inject_exec` skips gracefully.
   `refresh_exec_row.py` is likewise a no-op. Don't reintroduce an embedded array.
3. **Slug ≠ slugified display name** ("MSP Corp" → `mspcorp`, "RealTime, LLC" →
   `realtime-it`, …). Use the explicit `slug` field; never derive from display name.
4. **All data is real** — the synthetic demo partners were wiped 2026-06-11 (seeder
   deleted). If `demo: true` rows reappear, stale data is being restored.
5. **Halo API is quirky** (no server-side ticket-type filter, unreliable
   `record_count`, no closed flag on statuses, custom fields only on detail calls).
   Check `docs/HaloPSA-API-SOP.md` quirks + addenda before writing Halo code.
6. **`markitdown` is required** for the registry build path and `.docx` transcript
   ingestion (installed here 2026-06-11). Where it's missing,
   `build_real_partners.py` skips transcripts with a warning and
   `extract.build_all` fails outright. Transcript folders are matched
   case/punctuation-insensitively; unmatched folders trigger a warning.
   Transcripts can be `.docx` (manual Teams export) or `.vtt` (pulled from the
   Graph meeting-transcript API via the Claude M365 connector — agent-driven flow,
   see Data-Extraction-SOP §1 Option C; only works for meetings the connector
   user attended, else Graph 403s).
7. **`index.html` does NOT load `styles.css`** — it is fully self-contained (own
   inline `<style>` + `<script>`); `styles.css` applies only to `partner.html`.
   Shared UI needs its CSS in BOTH places. (The same duplication applies to the
   Firebase SDK `<script>` tags + `auth.js` + `firebase-config.js`, which are in
   BOTH `index.html` and `partner.html` heads — see gotcha 10.)
8. **Demo-roster allowlist:** if `data/_demo_roster.json` (a list of slugs) exists,
   `build_overview.py` filters the feed — and the portfolio rollups — to just those
   partners, so the dashboard shows a curated subset (currently the full
   DES/MDE roster from Halo report 364; was 20 for the CTO demo) without deleting
   any caches. It is **sync-proof** (a rebuild can't resurrect hidden
   partners) and reversible: edit the list to add/remove, or delete the file to show all
   built partners. `audit_data.py` scopes its checks to the allowlist when present.
9. **Production data source = Cloud Firestore, NOT `data/*.json` (since 2026-06-16).**
   Pages never read storage directly — they call `window.PP_AUTH.loadOverview()` /
   `loadPartner(slug)` / `lastSyncStamp()` (`auth.js`), which reads Firestore in prod and
   the local JSON on localhost, returning the SAME shapes. **Firestore is the serving
   source of truth**, republished nightly by the Cloud Run Job → `upload_firebase_data.py`;
   never hand-edit Firestore. A feed/blob key change must update its producer
   (`build_overview.py`/`build_partner.py`) AND `upload_firebase_data.py`
   (`_PROFILE_KEYS`/`_SECTIONS`) AND `docs/Data-Schema.md`. `firebase deploy` ships UI/rules
   only — data refresh is the Job, not a redeploy.
10. **Firebase tags in BOTH HTML heads:** the firebase-app/auth/firestore compat
   `<script>`s + `firebase-config.js` + `auth.js` are in `index.html` AND `partner.html`.
   Auth is email/password restricted to a **named allowlist** of verified `@itbd.net`
   accounts (ITBD is on M365, not Google Workspace) — the list lives in BOTH
   `firestore.rules` `isItbd()` (enforced) and `auth.js` `ALLOWED_EMAILS` (overlay bounce);
   edit both + redeploy rules + hosting to change who has access. Full deploy + provisioning runbooks: `docs/Firebase-Deploy-SOP.md` and
   `docs/Cloud-Pipeline-SOP.md`; end-to-end data map: `docs/Data-Schema.md`.
