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
python scripts/gen_demo_partners.py          # reseed 40 synthetic demo partners + reinject
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
  `data/{slug}.json` at runtime. `styles.css` shared; Chart.js vendored in `vendor/`.
- `refresh.js` — "Sync Data" header button (both pages). Talks to `server.py`'s
  sync API: `POST /api/refresh` (single-flight, optional `{"steps":[...]}` subset:
  `registry` | `real-extras` | `demo-reindex`), `GET /api/refresh/status`. Cycle =
  build_all → build_real_partners → gen_demo_partners, continue-on-failure, log in
  `data/_sync.log`. The `registry` step needs `markitdown`.
- `extract/` — pipeline library package (config, halo, teamgps, transcripts, ai,
  build_partner, build_all, portfolio). Secrets: env/.env first, live fallbacks
  baked in `extract/config.py` (beta only — never copy them elsewhere).
- `scripts/` — operational entry points; they sys.path-shim the repo root, run them
  from anywhere. New one-off scripts go here, library code goes in `extract/`.
- `data/` — generated, gitignored (partner JSONs, `_index.json`, `decks/`,
  `demo_exec_partners.js`). Never write generated artifacts to the repo root.
- `docs/` — architecture, changelog, 3 API/extraction SOPs, LLM-SOP, `archive/`
  (frozen, never edit). `Transcripts/` — input .docx. `legacy/` — dead code, kept.

## Critical gotchas

1. **Two data layers must stay in sync:** the embedded array in `index.html` vs the
   `data/*.json` caches. Partner-set changes go through the injection scripts
   (`scripts/build_real_partners.py`, `scripts/gen_demo_partners.py`), never by
   hand-editing one side.
2. **Injection anchors:** the scripts splice `index.html` at literal marker strings
   (`// ---- BEGIN/END real partners ----` and the last real partner's
   `lastCall: …, callsAnalyzed: N },` line). Don't reformat those lines.
3. **Slug ≠ slugified display name** ("MSP Corp" → `mspcorp`, "RealTime, LLC" →
   `realtime-it`, …). Use the explicit `slug` field; never derive from display name.
4. **`DEMO_COUNT = 40`** in `gen_demo_partners.py` — it purges and regenerates all
   `demo: true` files, so a smaller value silently shrinks the dashboard.
5. **Halo API is quirky** (no server-side ticket-type filter, unreliable
   `record_count`, no closed flag on statuses, custom fields only on detail calls).
   Check `docs/HaloPSA-API-SOP.md` quirks + addenda before writing Halo code.
6. **`markitdown` may be missing locally** — importing `extract.build_partner` then
   fails; one-off scripts inline their own `slugify` instead.
7. **`index.html` does NOT load `styles.css`** — it is fully self-contained (own
   inline `<style>` + `<script>`); `styles.css` applies only to `partner.html`.
   Shared UI (like the sync button) needs its CSS in BOTH places.
