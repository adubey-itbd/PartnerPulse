# Changelog

All notable changes to the **PartnerPulse** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0-beta.6] - 2026-06-12

### Added
- **Graph transcript app registration tested + IT setup script:** IT provisioned the app registration from `docs/IT-Request-Graph-Transcript-Access.md` (client id `c7bc5538-…2983`, app display name "DESManagement@itbd.net"). Connection test 2026-06-12: token + calendar reads on DESManagement work; transcript reads still 403 (Teams application access policy missing), `OnlineMeetings.Read.All` not granted, and Calendars.Read is currently tenant-wide (Exchange policy missing — verified by reading an out-of-scope mailbox). Added `scripts/setup_graph_transcript_access.ps1` — a commented, idempotent one-shot script for IT that adds the missing permission + admin consent, creates/grants the Teams application access policy to the 3 organizer accounts, scopes calendar access via Exchange **RBAC for Applications** (mail-enabled security group → management scope → `Application Calendars.Read` role, then removes the now-redundant tenant-wide Calendars.Read consent), and verifies with `Test-ServicePrincipalAuthorization`. Cmdlet syntax web-verified against Microsoft Learn 2026-06-12 — notably `New-ApplicationAccessPolicy` (the older Exchange scoping) is now flagged "don't create new" by Microsoft, hence the RBAC approach. Credentials live in `.env` (gitignored); `GRAPH_TENANT_ID`/`GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET` documented in `.env.example`. Outcome recorded in the IT-request doc.
- **Milner 2026-06-12 service-call transcript** pulled via the M365 connector (Graph meeting-transcript flow, Data-Extraction-SOP §1 Option C) and ingested: `Transcripts/Milner/Milner _ ITBD Service Call-20260612.vtt` (35m 18s, 8th `.vtt` for Milner, 18 transcripts total). Milner rebuilt end-to-end (`build_all --only Milner` → `--reindex` → exec-row refresh). The first rebuild scored **61 (High)**; same-day re-analyses (full sync, then the duplicate-transcript fix below) re-scored it to **27 (Low)** with reviewVolume 109→114 — gpt-5.4 re-scores shift run to run, and Halo shows RAG Amber / cancel-risk Low, consistent with the lower band. Final state: risk **27 (Low)**, 18 transcripts, both data layers in sync.
- **`scripts/refresh_exec_row.py <slug>|--all`:** re-renders partners' embedded exec-overview rows in `index.html` from their `data/{slug}.json` caches. Registry partners' rows live in the *static* part of the array (outside the BEGIN/END markers), so `build_real_partners.py`'s injector can't update them and would append a duplicate — this script replaces each row by slug wherever it sits. Completes the scripted single-partner refresh path (`build_all --only <Name>` → `build_all --reindex` → `refresh_exec_row.py <slug>`).
- **Sync cycle step 3 of 4 — `exec-rows`:** the manual sync cycle now runs `refresh_exec_row.py --all` between the extras injection and the reindex. **Fixes a standing two-data-layer drift:** a full sync rebuilt every registry partner's `data/*.json` but never touched their static exec-overview rows in `index.html`, so the Executive Overview kept showing stale risk scores (observed live: Milner 61/High embedded vs 31/Low in the rebuilt cache after the 2026-06-12 sync re-analyzed it with the new transcript).
- **"Last sync" timestamp next to the Sync Data button** (both pages): `refresh.js` reads `portfolio.generated_at` from `data/_index.json` (no-cache fetch) and renders e.g. "Last sync: Jun 12, 1:23 PM" — survives server restarts and reflects CLI builds too; hidden silently on static hosting without `data/`.
- **`refresh_exec_row.py --remove <slug>`:** scripted offboarding — deletes a partner's embedded exec-overview row (used for the CW Now correction below).
- **`scripts/probe_graph_transcripts.py`:** the Graph app-registration acceptance test (token → resolve meeting from join URL → transcript fetch) promoted from a throwaway probe into a proper script — credentials now read from the `GRAPH_*` vars in `.env` (the throwaway had the client secret hardcoded and sat in `data/`, where `.py` files weren't gitignored). Referenced from the IT-request doc as the post-remediation verification step.

### Fixed
- **Milner's 2026-06-12 call was double-ingested:** both the Graph-pulled `.vtt` and a manual Teams `.docx` export of the same meeting (identical title/time/duration) were in `Transcripts/Milner/`, so the call counted twice in the AI input (19 transcript entries instead of 18). Removed the duplicate `.docx` and rebuilt Milner (risk now 27/Low — see the transcript entry above).
- **`.gitignore` now ignores all of `data/`** (was per-extension patterns `*.json`/`*.log`/`*.js`/`decks/`), closing the gap that let a stray script with a hardcoded secret sit in `data/` untracked-but-committable. Invariant updated in `docs/LLM-SOP.md` §3 rule 5.
- **Stale "CW Now" references swept from the docs** after the C&W Computers correction (below): `CLAUDE.md` and `docs/architecture.md` §9 no longer cite CW Now as the transcript-only example (that path is currently unused); `README.md`/`CLAUDE.md`/`Data-Extraction-SOP` §6 now say transcripts are `.docx` + `.vtt` (not Word-only) and list the two Graph scripts.

### Changed
- **Partner drilldown restyled to the claymorphic theme (`styles.css` only — presentation, no markup/JS changes):** `partner.html` now matches `index.html`'s approved design: lavender gradient backdrop with ambient blobs, sidebar and main content as floating rounded slabs, gradient active nav and partner avatar, KPI tiles turned pastel/gradient via `:has()` on the existing icon-wrapper classes (markup untouched), gradient feedback filter pills, restyled badges/cards/tables/accordions, ITBD chat bubbles use the shared purple gradient, and all hardcoded slate neutrals (`#f8fafc`/`#f1f5f9`/`#e2e8f0`) swapped to the lavender-tinted equivalents. The dark-slate `.sidebar` override block was removed; transcript/deck explorer heights adjusted for the new padding (`calc(100vh - 222px)`). Sync button/panel CSS kept mirrored with `index.html` (gotcha 7).
- **Executive Overview "claymorphic" restyle pass (`index.html` only, second mockup — presentation, no data/behaviour changes):** lavender gradient page backdrop with soft ambient blur blobs; the sidebar and main content now float as separate rounded slabs (26px radius, deep soft shadows; sidebar sticky at `calc(100vh - 36px)`); KPI tiles got bigger radii, inset top highlights, and tier-coloured glow shadows; filter pills and the rank-toggle are borderless white pills with soft shadows; the header sits directly on the shell (no white bar); the risk-ranking chart bars are fully pill-shaped (`borderRadius: 999`, `borderSkipped: false`) and the chart card header gained a static High/Watch/Healthy dot legend (mockup said "very high/high/medium" — kept our real tier names). All element ids, render functions, and data untouched.
- **Executive Overview visual redesign (`index.html` only — presentation, no data/behaviour changes):** restyled to the approved mockup. Light sidebar (was dark) with gradient active-nav pill and a new **Insights Snapshot** card that mirrors the portfolio KPI numbers (filled by `renderKPIs()`; its "View all insights" link jumps to the at-risk table); header gained a per-view subtitle; KPI tiles are now soft pastel cards with per-metric icons (Partners Tracked tile is purple-gradient); filter pills are gradient-filled when active; the risk-ranking chart and at-risk table sit **side by side** (`.overview-split`, stacks below 1380px — DOM moved, all element ids unchanged); chart bars render as left→right tier-coloured gradients (tier semantics unchanged); sidebar is sticky/viewport-height so the snapshot stays visible. The `prefers-color-scheme: dark` overrides were removed — the redesign is a committed light theme (the old dark palette clashed with the pastel tiles). `partner.html`/`styles.css` untouched; sync button/panel classes (`.sync-btn`, `.sync-stamp`, `.sync-panel`) kept for `refresh.js`; the BEGIN/END injection anchors and embedded partner array were not touched.
- **"CW Now" corrected to "C&W Computers" (Halo client 39):** the calendar-audit onboarding had created a transcript-only partner from the meeting title "CW Now", but those meetings belong to Halo client **C&W Computers** (attendees @cwnow.com = their domain; cwnow.com is a registered user domain on client 39). Replaced the `NEW` entry in `scripts/build_real_partners.py`, renamed `Transcripts/CW Now/` → `Transcripts/C&W Computers/`, removed `data/cw-now.json` + the embedded row, and rebuilt with the full Halo + TeamGPS path: 20 CSAT (95% positive), 10 NPS promoters / 0 detractors, 2 review calls, 2 transcripts, RAG Green → risk **18 (Low)** (was a transcript-only 52/High under the bogus name). Portfolio stays at 38 partners. Transcript access for the series confirmed (Amit is an invitee); the Apr 7 and Jun 9 occurrences have no transcript — the 2026-05-12 MBR and 2026-06-02 service call already pulled are the most recent available.
- **Live sync progress panel:** while a sync runs, the "Sync Data" button now shows a progress card beneath it (both pages) listing every cycle step with ✓/⟳/✕ state and the **live pipeline activity** — e.g. "Logically: syncing TeamGPS CSAT", "MSP Corp: running AI churn analysis (gpt-5.4)", "updating executive-overview partner array". `server.py` now streams each step's output line-by-line (previously buffered until the step finished), translates the pipeline's tagged phase lines (`[csat]`, `[nps]`, `[transcripts]`, `=== Partner ===`, …) into a human-readable `activity` field on `GET /api/refresh/status`, and `refresh.js` renders the panel (poll interval 3s → 2s). `data/_sync.log` now receives the full streamed output as it happens instead of an 8-line tail per step.
- **20 new partners onboarded into the dashboard** (transcript-access audit follow-up): Continuous Networks, APM IT Solutions, Matador Networks, Vitis Tech, Community IT, PEI, Prevare LLC, Perfect Cloud Solutions, Dependable Solutions, Pegasus Technology Solutions, Boomtown CIO, CW Now, Networking Now, Galactica Cybersecurity, ICSI, Infopathways, NerdsToGo, CMIT Solutions Stamford, Vistitude, Mission Technology — built via `scripts/build_real_partners.py` (Halo + TeamGPS + SIPs + gpt-5.4) and injected into the exec-overview array. Portfolio now tracks **38 real partners**.
- **Transcript-only build path:** NEW entries may carry `client_id=None` (no Halo record — e.g. CW Now); the build skips Halo/TeamGPS and runs the AI on call transcripts alone.
- **36 more Teams call transcripts pulled** (Apr 14 – Jun 11 window) across the new partners plus Computer Weavers, after a full calendar audit of desmanagement@itbd.net (377 events) determined per-meeting access. Notable availability gaps: Continuous Networks never had transcription enabled (0 transcripts despite 7 accessible calls); several single occurrences (Matador 05-04, APM April weeklies, Pegasus CalAmp 05-01, Community IT Innovators 05-13) have no transcript; Boomtown's QBR and Vistitude's QBR meetings aren't resolvable via Graph.

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
