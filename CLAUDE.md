# CLAUDE.md — PartnerPulse

Executive partner-health & churn-risk dashboard for ITBD (white-label NOC/helpdesk
provider; "partners" are MSPs). Python build-time pipeline (HaloPSA + TeamGPS + local
docs → Azure gpt-5.4 churn analysis → static JSON caches) + framework-free HTML/JS
frontend served from the repo root.

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
python -m extract.build_all                  # full build: all partners + AI + portfolio index
python -m extract.build_partner "Logically"  # build one partner
python -m extract.build_all --reindex        # rebuild data/_index.json from existing JSONs (no fetch)
python scripts/build_real_partners.py        # extra real Halo clients + exec-overview injection
python scripts/refresh_exec_row.py <slug>    # re-render one partner's embedded exec row from its JSON
python scripts/refresh_exec_row.py --all     # re-render ALL embedded exec rows (sync step "exec-rows")
python scripts/refresh_exec_row.py --remove <slug>   # delete a partner's embedded exec row (offboarding)
#  single-partner refresh: build_all --only <Name> -> build_all --reindex -> refresh_exec_row.py <slug>
python server.py [port]                      # dev server, default http://localhost:8000
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # fresh-machine bootstrap
```

No test suite. Verify changes by running the relevant build script and loading the
dashboard. Full builds hit live APIs + the LLM (~5 min) — prefer single-partner or
`--reindex` runs.

## Layout

- `index.html` — Executive Overview + Partner 360 views (sidebar-switched). Partner
  data is an **embedded array** in its inline `<script>`, NOT fetched.
- `partner.html` + `partner.js` — per-partner drilldown (`?partner=<slug>`), fetches
  `data/{slug}.json` at runtime. Styled by `styles.css` (which `index.html` does
  NOT load — gotcha 7); Chart.js vendored in `vendor/`.
- `refresh.js` — "Sync Data" header button + "Last sync" timestamp (both pages;
  timestamp = `portfolio.generated_at` from `data/_index.json`). Talks to
  `server.py`'s sync API: `POST /api/refresh` (single-flight, optional
  `{"steps":[...]}` subset: `registry` | `real-extras` | `exec-rows` |
  `reindex`), `GET /api/refresh/status` (per-step state + live `activity`
  parsed from streamed pipeline output — see `server.py: parse_activity`).
  While running, a progress panel under the button shows each step + current
  activity; its CSS lives in BOTH `styles.css` and `index.html`'s inline
  `<style>` (gotcha 7). Cycle = build_all → build_real_partners →
  refresh_exec_row --all → build_all --reindex, continue-on-failure, streamed
  log in `data/_sync.log`.
- `extract/` — pipeline library package (config, halo, teamgps, transcripts, ai,
  build_partner, build_all, portfolio). Secrets: env/.env first, live fallbacks
  baked in `extract/config.py` (beta only — never copy them elsewhere).
- `scripts/` — operational entry points; they sys.path-shim the repo root, run them
  from anywhere. New one-off scripts go here, library code goes in `extract/`.
  `build_real_partners.py` NEW is the partner roster beyond the registry (28
  entries); `client_id=None` marks a transcript-only partner with no Halo record
  — Halo/TeamGPS skipped, AI runs on call transcripts alone (path currently
  unused: its one user "CW Now" turned out to be Halo client 39 "C&W Computers",
  corrected 2026-06-12). `setup_graph_transcript_access.ps1` is for IT, not the
  pipeline: finishes the Graph app-registration provisioning (permissions +
  access policies — see `docs/IT-Request-Graph-Transcript-Access.md` § Outcome);
  `probe_graph_transcripts.py` is its acceptance test (token → meeting →
  transcript fetch). Graph creds: `GRAPH_*` vars in `.env`.
- `data/` — generated, gitignored (partner JSONs, `_index.json`, `decks/`,
  `_sync.log`). Never write generated artifacts to the repo root.
- `docs/` — architecture, changelog, 3 API/extraction SOPs, LLM-SOP, `archive/`
  (frozen, never edit). `Transcripts/` — input .docx/.vtt, one folder per
  partner. `legacy/` — dead code, kept.

## Critical gotchas

1. **Two data layers must stay in sync:** the embedded array in `index.html` vs the
   `data/*.json` caches. Partner-set changes go through
   `scripts/build_real_partners.py` (exec-array injection) + `extract.build_all
   --reindex` (index), never by hand-editing one side.
2. **Injection anchors:** `build_real_partners.py` splices `index.html` between the
   literal `// ---- BEGIN/END real partners ----` marker lines. Don't reformat them.
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
   Shared UI (like the sync button) needs its CSS in BOTH places.
