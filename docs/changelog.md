# Changelog

All notable changes to the **PartnerPulse** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — Access allowlist: +3 users (2026-07-09)

### Changed
- **Added `sarbjeet.singh@itbd.net`, `ankur.kumar@itbd.net`, `kpatel@itbd.net`** to the
  access allowlist in BOTH `auth.js` `ALLOWED_EMAILS` and `firestore.rules` `isItbd()`
  (now 10 named `@itbd.net` accounts — gotcha 10). Accounts pre-created in Firebase Auth
  (email/password, `email_verified=true`, admin-provisioned rather than self-signup).
  Shipped via `firebase deploy --only firestore:rules,hosting`.

## [Unreleased] — Transcript-pull: make PARTNER_ALIASES authoritative (2026-07-09)

### Fixed
- **`target_folder()` now treats a `PARTNER_ALIASES` match as AUTHORITATIVE** — it routes
  to the canonical folder (existing or newly-created) and never falls back to the
  raw/stripped name. The prior fix (below) only created the canonical folder when *no*
  folder existed; if a **stale mis-stripped folder was already present** (e.g. a `CP/`
  folder in the cloud state bucket from an old pre-fix pull of "CP Corp"), the
  stripped-name branch still won and transcripts kept landing in `CP/` — which
  `build_real_partners` (matches folders by display name `CPCORP Inc`) never picked up, so
  CPCorp stayed **"No calls"** in prod even after the image rebuild. Verified against the
  stale-folder case + regressions (Netgain/MSPCorp/Infopathways still resolve to their
  existing folders). NOTE: the orphaned `CP/` folder in the state bucket is now a harmless
  unmatched folder (flagged by `warn_unmatched_transcript_dirs`); transcripts re-pull into
  `CPCORP Inc/` on the next run (within the ~90-day Teams content window).

## [Unreleased] — Transcript-pull folder routing: aliases now name NEW folders (2026-07-09)

### Fixed
- **`scripts/pull_graph_transcripts.py` `target_folder()` now uses a `PARTNER_ALIASES`
  entry to name a NEW folder, not just to match an existing one.** Previously an alias was
  consulted only via `resolve_partner_dir(alias)`; if that folder didn't exist yet the alias
  was silently ignored and the folder was created from the corp-suffix-stripped subject. That
  mis-routed any not-yet-onboarded aliased partner — notably **CPCORP Inc**, whose meeting
  subject `"CP Corp | … Service Call"` stripped to a `"CP"` folder that `build_real_partners`
  (which matches transcript folders by display name) never picked up, so CPCorp showed
  **"No calls"** despite having a recorded weekly service call. Existing aliases still resolve
  to their existing folders first (no regression: MSPCorp/Netgain/etc. verified `is_new=False`).
- **Added `PARTNER_ALIASES` entries** mapping mis-parsed meeting-subject short names to their
  exact roster display names: `"cp corp" → "CPCORP Inc"`, `"atlas ps" → "Atlas Professional
  Services"`, `"itbd-ironedge" → "IronEdge Group"`.

### Notes
- **Primary root cause of the CPCorp report was NOT the folder name — the transcript pull is
  down roster-wide.** A live Graph dry-run (`pull_graph_transcripts.py --since 2026-04-01`)
  found **all 112 partner service-call series return `resolve 403`** — `"No application access
  policy found for this app … on the user"`. The Teams application access policy grant on the
  **`DESManagement@itbd.net`** shared mailbox (organizer of ~125/152 calls, incl. CPCorp) has
  **lapsed** — it was verified working on 2026-06-13, so this is a regression, not a new gap.
  **Remediation (Teams-admin action, not code):** re-run the grant —
  `Grant-CsApplicationAccessPolicy -PolicyName 'PartnerPulse-Transcripts-Policy' -Identity 'DESManagement@itbd.net'`
  (or re-run `scripts/setup_graph_transcript_access.ps1`, whose Step 2 re-grants idempotently).
- **Policy decision (2026-07-09): management-mailbox-only, no individual accounts.** Transcripts
  are pulled only for calls organized by the DESManagement shared mailbox (which covers its
  MDE/SBD SMTP aliases — same object id). The 25 series organized by individual AMs (Luis.Gavino,
  SBhatia, Ashish.Paul, …), mostly QBRs, are **intentionally out of scope** and will stay 403.
- **One `MDEManagement`-tagged call is out of scope by that rule.** "Monthly Service call |
  Innovative Technology Solutions (ITS)" resolves to a *distinct* identity (oid `55eb5f1a`,
  = an individual, Gagan.Chowdhary) rather than the DESManagement mailbox (oid `3f79ace1`) —
  it used the MDE alias but was organized by a person. `MDEManagement` itself can't be granted
  (alias, "User does not exist"), so covering it would require an individual grant; left out of
  scope per the no-individuals decision.
- **QBR-format subjects still mis-parse** (`"ITBD x Acrisure : Quarterly Business Review"`,
  `"Omega Systems Corp - Bi-Weekly Service Call | <people>"`): `partner_from_subject` has no
  separator to split on, so the partner isn't isolated. Moot (those calls are organizer-out-of-
  scope) and not fixable by an alias; left as a known limitation.

## [Unreleased] — Remove baked-in secrets from config.py + scrub git history (2026-06-29)

### Security
- **Removed all hardcoded credentials from `extract/config.py`.** It previously carried
  live fallback secrets (Halo client id/secret, TeamGPS API key, Azure-AI/Grok key) as
  default args to `_secret(...)`. GitHub push-protection blocked pushing the repo to the
  ITBD remote because of them. The literals are gone — `_secret("KEY")` now resolves from
  env / `.env` only and warns once (then returns `""`) if unset.
- **`config.py` now loads `.env` with a built-in parser** (no `python-dotenv` dependency,
  which wasn't installed — so `.env` had silently never loaded and the baked defaults were
  always used). `os.environ.setdefault` keeps real env vars / Secret Manager values
  authoritative over `.env`.
- **Scrubbed the secrets from the entire git history** with `git filter-repo --replace-text`
  (every historical occurrence in `config.py`, including the older Azure `gpt-5.4` key,
  replaced with `***REMOVED***`) so no secret reaches GitHub. All commit SHAs were rewritten.
- **Local dev:** the keys were moved to the gitignored `.env` (HALO_CLIENT_ID/SECRET,
  TEAMGPS_API_KEY, AI_API_KEY — alongside the existing GRAPH_*). Cloud is unaffected
  (Secret Manager via `scripts/seed_secrets.py`). **Recommended follow-up: rotate these
  keys**, since they lived in git history (and possibly a prior personal remote).
- CLAUDE.md updated to state config.py is secret-free / env-and-.env-only.

## [Unreleased] — Data-audit accuracy fixes (2026-06-29)

### Fixed
- **`scripts/audit_data.py` clock un-frozen** — `TODAY` was hardcoded to `2026-06-13`,
  so the "last call stale (>60d)" check measured staleness from a fixed past date and
  under-reported. Now `date.today()`. (Surfaced e.g. Blackline IT at 73d, previously missed.)
- **Transcript-folder check (#5) no longer false-flags sub-team folders.** The build folds
  sub-team folders into their parent partner via `transcripts.partner_transcript_dirs`
  (`_alnum().startswith()` with a 6-char floor, since 2026-06-19 — e.g. `MSP Corp (HD Team)`,
  `(SOC)`, `(MBCCS Group)` all roll into `mspcorp`, which has 98 transcripts ingested), but
  the audit only did an exact-slug match and so reported those 6 folders as "not ingested."
  The audit now mirrors the build's fold rule (replicated locally — does **not** import
  `extract.transcripts`, which would pull in `markitdown` and break the audit's API-free,
  ~1s contract). Added `IGNORE_TRANSCRIPT_FOLDERS` for confirmed non-partners (`Network
  Builders IT` — Halo 426, contract cancelled, deliberately excluded per
  `build_real_partners.py`). Check #5 now reports 0.

### Notes (investigated, no code change)
- **Empty-CSAT partners are genuine data gaps, not name mismatches.** Probed TeamGPS for every
  plausible company name behind the 6 flagged partners: PEI (Dataprise) is by design (active
  CSAT is on the separate Dataprise/Halo-57 partner = 27 reviews); Stratti, Mission Technology,
  Spidernet, CPCORP, LATG return 0 under all spellings. No alias fix warranted.
- **CPCORP Inc (Halo 968) & LATG (883) kept on the roster** despite having no Halo/CSAT/
  transcript data yet (hence no AI score) — confirmed intentional; they'll populate as activity accrues.

## [Unreleased] — Dashboard re-themed to ITBD brand (cyan/Light) (2026-06-29)

### Changed
- **Theme swapped from claymorphic lavender → ITBD brand "Light"** across both UIs.
  Palette (from the ITBD brand set): `--primary`/accent **`#00AFDD`** cyan (was `#6d5ef0`
  violet; hover `#0090b8`, gradient `#22c3e8→#00AFDD`), `--bg-primary` **`#BED6E2`** pale
  blue, `--bg-shell` **`#F6F9FC`** ice, `--text-primary` **`#252525`** charcoal,
  `--success` **`#BFD730`** lime (text-dark `#5f7000`), `--warning` **`#FC9700`** orange
  (text-dark `#b56b00`). `--danger` red and `--info` blue kept (brand has no red). Cyan is
  reserved for fills/bars/active states (low contrast on white). Edited in **both**
  `index.html`'s inline `<style>` `:root` AND `styles.css` `:root` (gotcha 7), plus the
  matching hardcoded values: body gradient + `body::after` glow, the violet-tinted shadow
  rgba tokens (`76,70,160`/`109,94,240`/`64,58,150` → cyan tints `0,120,160`/`0,160,200`/
  `0,90,120`), `.status-dot.ai` ring, `.dw-asof` chip border/divider, and the **Chart.js
  colors** in `index.html` JS (`COL.success`/`warning`, the Renewal-MRR bar `#00AFDD`,
  `tierColor()` Watch/healthy pairs, `COL_CSAT`, and a grid line). `partner.js` has no
  hardcoded chart colors (drives off `styles.css` vars). **CSS/JS-only — no data, feed,
  Firestore, or pipeline change.** The previous dark theme backup
  (`backups/index_pre-darktheme_2026-06-24.html`) and pre-redesign backup remain for rollback.

## [Unreleased] — Renewal Risk view rebuilt on ConnectWise agreements (MRR + renewals + MRR-at-risk) (2026-06-26)

### Added
- **`scripts/build_cw_agreements.py`** — parses a static ConnectWise export
  (`CW Agreements*.xlsx` in `inputs/`) into **`data/_cw_agreements.json`**, the feed
  for the (now rebuilt) **Renewal Risk** view. Runs **after** `build_overview.py` (it joins
  partner health for the at-risk calc). Business rules (signed off 2026-06-26):
  - **Include** Agreement Type ∈ {Co-Managed, Self Managed, MSP Dedicated Engineer}; drop
    IMS, Team GPS (all), Project, Managed IT, Support By Design Complete.
  - **MRR** (col F) normalized to monthly: Monthly = Amount, Annual = Amount ÷ 12,
    One-Time / blank billing = 0. Summed per partner; ARR = MRR × 12.
  - **Partner match** to dashboard partners only (never creates partners): exact normalized
    name + a signed-off alias map (Dataprise→PEI (Dataprise), Redhelm→RedHelm -1Path,
    ETech 7 Inc→Etech7, Spidernet Technical Consulting→Spidernet Consulting, Vitis
    Technologies (ProSource)→Vitis Tech, Omega Systems Consultants Inc→Omega Systems Corp).
    Non-dashboard companies are ignored.
  - **At Risk** = an agreement renewing within **90 days** AND the partner is unhealthy
    (churn ≥ 45, RAG Red, confident-Negative call tone, or Declining trend). **Watch** =
    renewing ≤ 90d (healthy) or ≤ 180d (unhealthy). Partner tier = worst agreement tier;
    MRR-at-risk = Σ At-Risk agreement MRR. Blank end-dates are kept & flagged.
  - First export (June 2026): **76 partners, 208 agreements, ~$995K/mo MRR ($11.9M ARR);
    6 partners / 19 agreements / ~$58K/mo at risk.**
- **Renewal Risk view (`index.html`) rebuilt + unhidden** (was hidden 2026-06-23): replaces
  the old HaloPSA-contract renewal-adjusted score with CW-driven content — KPI cards
  (Total MRR/ARR, Partners, MRR-at-risk, Partners-at-risk), a **quarterly renewal forecast**
  chart, and a partner table (filter: All / At Risk / Watch / On Track) **expandable to
  agreement-level rows**. Loaded lazily via `PP_AUTH.loadCwAgreements()` (Firestore
  `meta/cwAgreements` in prod, `data/_cw_agreements.json` on localhost).
- **`scripts/upload_firebase_data.py`** publishes the feed as the single doc
  **`meta/cwAgreements`** (mirrors `meta/csatRecon`; absence tolerated, corrupt aborts).
  `auth.js` gains `loadCwAgreements()` (local + prod). `firestore.rules` already grants
  read via the `meta/{doc}` rule (no change).
- **Renewal Risk score (0–100), per partner** — `build_cw_agreements.py` adds
  `renewalRiskScore`/`renewalRiskBand` (+ `daysToNextRenewal`): a weighted blend of
  **renewal timing (40%) + account health (40%) + MRR exposure (20%)** (timing factor ≈ 0
  when nothing's renewing soon, so it's only meaningful for upcoming renewals). It **sits
  alongside** the Grok churn score — it does not blend with or replace it.
- **Renewal data now feeds the Executive Overview** (not just its own tab) — signed off
  2026-06-26, built additively (nothing removed):
  - New **"Revenue & renewals"** KPI row: Total Active MRR (+ARR), MRR renewing ≤90d
    (with 30/60-day split), MRR at risk, Partners at risk. Feed totals gain
    `mrrRenew30/60/90`.
  - The At-risk table gains **MRR** and **MRR-at-risk** columns.
  - **"Who needs attention"** keeps its churn ranking but adds **$-at-risk then MRR as a
    secondary sort** (and MRR in the bar tooltip), so within a tier the bigger-money
    partners surface first. Partners with no CW agreement keep their churn position.
  - `index.html` loads the CW feed once at init (cached promise, shared with the Renewal
    tab) and degrades gracefully when it's absent.
- **AI Findings — a "Renewal insights" card on the Executive Overview** (deterministic
  facts + a one-line "why it matters"): largest near-term MRR exposure, total MRR-at-risk,
  revenue concentration (top-5 %), partners with several agreements renewing together,
  high-value partners with no recent engagement, and recommended priority actions. Built in
  `build_cw_agreements.py` as `insights[]`.
- **Partner 360 — renewal detail + a "why at risk" reason engine.** Each partner row now
  carries `riskReasons[]` (computed from signals we have today: renewal timing, churn, RAG,
  declining trend, negative tone, low CSAT, no-engagement-90d as a QBR proxy, and a
  "no open SIP → open one" recommendation). The `partner.html` drilldown gains a **Revenue
  & Renewals** card (agreement count, MRR/ARR, renewal-risk score, MRR-at-risk, the why-at-
  risk badges, and an agreement-level table); the Partner 360 **table's renewal column now
  shows the CW renewal-risk score** (was the Halo `ai_renewal` band). `partner.js` loads the
  CW feed and matches its row by slug. **Deferred** (need data/decisions): GP/margin,
  ticket-trend, manual flags, true QBR date, and "missing renewal owner" (needs Regional
  Manager + Product Owner ingestion).
- **Privacy masking (HRIS-style).** A header eye toggle (`index.html` + `partner.html`)
  blurs all **money** figures (MRR/ARR/$-renewing/$-at-risk) when enabled — **visible by
  default**, click the eye to hide; choice persisted in `localStorage` (`pp_private`). Implemented via `.pp-money`
  + `body.pp-private` and the `m()` / `maskMoney()` helpers; scope is money only (scores,
  counts, % stay visible). Chart-canvas figures (tooltips/axes) aren't maskable and are
  left as-is.
- **AI "why" comment on at-risk dollars.** On the Renewal Risk page, every red MRR-at-risk
  figure now shows an italic **✦ AI** explanation composed from the reason engine
  (e.g. "Renewal in 4 days · Account RAG is Red · High churn risk (65)").
- **Recommended actions for at-risk renewals.** Each at-risk/watch partner now carries a
  `recommendation` (build_cw_agreements) — a concrete next step ordered by urgency (open a
  SIP, confirm renewal before end date, exec-sponsor save-play, schedule a QBR). Shown on
  the Renewal Risk page (a "→ Recommended:" line under the AI why-comment) and in the
  `partner.html` drilldown's Revenue & Renewals card.
- **Known gap — cancellations.** The CW export marks no cancellations/non-renewals (every
  row is Status "Active", no Do-Not-Renew/cancellation field), so the dashboard cannot flag
  a known cancellation (e.g. an engineer ending without renewal). Surfacing these needs the
  signal added to the source export; not inferred from proxies.

### Changed
- **Repo tidy: stray root files moved into folders.** The static `CW Agreements*.xlsx`
  export moved from the repo root into **`inputs/`** (`build_cw_agreements.py` now globs
  `inputs/`); the `UI Theme.png` design-reference screenshot moved into **`reference/`**.
  Both stay gitignored. No behavioural change to the pipeline or UI. Docs (`CLAUDE.md`,
  `Data-Schema.md`) updated to the new paths.

### Notes
- **Static source / manual refresh.** The xlsx is a manual export, not in the Cloud Run
  image or GCS, so the **nightly job does not refresh CW data** — it is built locally and
  published on request (re-drop the file → `build_cw_agreements.py` → `upload_firebase_data.py`).
  A ConnectWise API / GCS wiring is a future option if it needs to go automated.
- The base Partner-360 "Renewal" column still uses the Halo `ai_renewal` overlay (unchanged);
  only the dedicated Renewal Risk view moved to CW.

## [Unreleased] — Auto-exclude Halo-inactive partners from the dashboard (2026-06-25)

### Added
- **A partner flagged `inactive` in Halo is now automatically dropped from the
  dashboard feed and every portfolio rollup.** The per-partner build captures Halo's
  client `inactive` flag into the blob (`client.inactive`) — both
  `extract/build_partner.py` (`_client_block`, registry path) and
  `scripts/build_real_partners.py` (real-partner roster path); API-unreadable /
  transcript-only clients have no record and read as active (`False`).
  `scripts/build_overview.py` then excludes any `client.inactive` partner before the
  rollups, surfacing the drop (`Excluding N Halo-inactive partner(s): [...]`) and
  recording it in the feed as `inactiveCount` / `inactiveSlugs`.
- **Sync-proof & reversible** (like the demo-roster allowlist, gotcha 8): a rebuild
  keeps an inactive partner out as long as Halo still says inactive; flipping it back
  to active in Halo brings it back on the next sync. No caches deleted.
  `upload_firebase_data.py` needs no change — it derives the doc tree from
  `_overview.json` (already filtered) and its stale-partner reconcile prunes the
  now-absent partner's Firestore docs (sanity-gated).
- **First application: Thrive NextGen (Halo client 29) went inactive** — dropped from
  the feed (83→82 partners; its 1 open SIP and risk-90 row removed), its Firestore docs
  pruned (1 stale removed) on publish.

## [Unreleased] — CSAT recon: don't inflate a settled month's "sent" with month-less stragglers (2026-06-24)

### Fixed
- **CSAT Reconciliation over-counted SENT surveys in settled months** (e.g. **Logically
  May read 30 vs Halo's 27**). ITBD raises each monthly CSAT batch (~day 23) with bare
  `Monthly Feedback for <name>` summaries and stamps the `For The Month of <X>` text on
  later; most get stamped, a few stragglers/duplicates never do. `_ticket_month`
  (`scripts/build_csat_recon.py`) fell back to the ticket's **raise month** for any
  month-less ticket, so those unstamped stragglers were still counted into the month they
  were raised — inflating it above Halo's "Month of …" report.
  - The summary "Month of …" is now authoritative; the `dateoccurred` fallback applies
    **only to the current (in-progress) month**, whose freshly-raised batch is legitimately
    still month-less. Settled prior months now match Halo's per-month count; the current
    month's batch still shows.
  - `audit_csat_recon.py` reuses `_ticket_month`, so the audit picks up the same rule.
  - Effect (Logically): May 30→**27** (Halo: 27); also Jan 31→28, Mar 28→27; June (current)
    stays 30. Re-run `python scripts/build_csat_recon.py` (then `upload_firebase_data.py`)
    to republish the feed.

## [Unreleased] — Fix Etech7 (live client 934 not API-readable) + tolerate unreadable clients (2026-06-23)

### Fixed
- **Etech7 was pulling all-zero data** (CSAT/SIP/calls/AI empty). Root cause was Halo data
  hygiene: the roster pointed at **client 924 "ETech 7 Inc"**, a **stale empty duplicate**,
  while the **live** record is **"Etech7" (ticket `client_id=934`)** — whose `/api/Client/934`
  **404s** (the record isn't API-readable; its contacts even sit under the "HubSpot Unmatched"
  client 211), and whose TeamGPS CSAT name is the exact string **"Etech7"** (our roster used
  "ETech 7 Inc" → matched 0).
  - `scripts/build_real_partners.py`: roster entry repointed `924 → 934`, `halo_search`/
    `teamgps_company` → **"Etech7"**. The roster **label is kept as "ETech 7 Inc"** so the slug
    stays `etech-7-inc` (Firestore doc + demo-roster allowlist unchanged — no cascade); the
    **displayed** client name resolves to "Etech7".
  - **`build_real` now tolerates an API-unreadable Halo client** — when `get_client(id)` 404s (or
    returns no name) it builds from **ticket-space data only** (SIP / service-call notes /
    CSAT-sent all filter by `client_id` and work fine) with a manual display name from
    `halo_search`; RAG / custom fields / NPS-users stay blank because the record genuinely can't
    be read. General fix for any future "ghost client_id" partner (cf. the Acrisure 937→79
    class). Previously such a 404 aborted the partner's build.
  - Result: Etech7 now resolves to the live record — **1 open SIP**, **5 sent CSAT surveys
    (Jan–May 2026, 0 received)** in CSAT Reconciliation, churn 15 (Low). (CSAT ratings, MoM
    notes, and SIP-progress detail remain thin — genuine Halo data-entry gaps, not a pipeline
    bug.) `build_csat_recon.py` already tolerated the 934 detail-404 (WARN + continue).

### Added
- **`extract/ai.py` `_normalize_insight`** — repairs a Grok quirk where the churn JSON puts
  `action_items` under a BLANK/non-string key (`"": [...]`), which both failed the cache's
  required-key check and was rejected by Firestore (field names must be non-empty strings).
  Coalesces such a key into `action_items` and drops empty keys so every result is
  Firestore-safe. (Surfaced when the SIP-rollout upload failed on the Amoskeag cache.)

## [Unreleased] — Hide the Renewal Risk dashboard tab (2026-06-23)

### Changed
- **The "Renewal Risk" nav tab is hidden** in `index.html` — both the sidebar `<li>`
  and the mobile-nav `<a>` (`data-view="renewal"`) are commented out (marked
  "HIDDEN (2026-06-23, will unhide when needed)"). The Renewal Risk view section and
  its JS are left intact, so restoring is just uncommenting the two nav entries.
  - **Front-end only** (`index.html`) — no pipeline/Firestore/image change; the
    `ai_renewal` overlay still builds and publishes as before.

## [Unreleased] — CSAT Reconciliation: two-dimension breakdown (nested) (2026-06-23)

### Changed
- **The CSAT "Breakdown" now supports two dimensions at once.** The single "Group by"
  tab strip is replaced by two dropdowns — **Break down by** (`dim1`) and **then by**
  (`dim2`, optional, default None) — over Partner / Account Manager / Regional Manager /
  Site / Product (MDE). Period (Monthly/Quarterly) and Metric (Sent-Received / Response
  rate / CSAT %) are unchanged.
  - `dim2 = None` → the old flat single-dimension table.
  - `dim1 = coarse attr` + `dim2` → **nested rows**: a pooled bold subtotal per `dim1`
    group, then indented `dim2` sub-rows (e.g. Account Manager → Self/Co-Managed).
  - `dim1 = Partner` + `dim2` → partner rows with the `dim2` value as an extra label
    column (a partner can't be split further).
  - Footer "All (N)" sums only top-level rows so nested children aren't double-counted;
    all subtotals/totals are pooled (positive ÷ rated), not row averages.
  - **Front-end only** (`index.html`) — the feed already carries every dimension, so no
    pipeline/Firestore/image change. Unclassified partners (blank Halo `CFProductMDE` /
    no RM) group under "—"/"Unassigned" as before.
## [Unreleased] — Capture SIP progress notes (incl. private notes) into AI + Partner 360 (2026-06-23)

### Added
- **SIP ticket progress notes now feed the churn AI and a new Partner-360 "SIP Progress
  Notes" card.** Previously the pipeline only *counted* SIP tickets (`{open, closed}`) — the
  SDM's weekly progress write-ups (utilization, ticket-closure, governance review, on-track
  status) and the initial action plan never reached the analysis. QC on **Logically** (SIP
  ticket `0761066`) surfaced the gap: the AI mentioned the SIP only via the bi-weekly call
  notes, with none of the actual week-by-week SIP execution detail.
  - **Root Halo quirk (documented in HaloPSA-API-SOP):** those write-ups are filed as
    **PRIVATE notes** (`hiddenfromuser=true`), and Halo's `/api/Actions` **LIST endpoint
    silently omits private notes**. They are only retrievable by fetching each action by its
    (1-based, per-ticket) `id`. The earlier Stratti MoM gap was the same class of issue.
  - `extract/halo.py`: refactored SIP discovery into `_discover_sips` (+ `_count_sip_rows`);
    `count_sips` is unchanged behaviourally. Added `analyze_sips()` — one-pass discovery that
    returns **`{open, closed, sips}`** where `sips` is grouped **per SIP ticket** with status
    (`_sip_status_label` → Open / On Hold / Closed/Resolved/…), `started`/`latest` range, an
    engineer-derived `subject`, and `updates[]` (the progress write-ups; `_sip_ticket_notes`
    walks action ids to include the PRIVATE notes the LIST hides). Active SIPs sort before closed.
  - `extract/build_partner.py` + `scripts/build_real_partners.py`: call `analyze_sips`, write
    new top-level cache key **`sips`** (grouped).
  - `extract/ai.py`: `build_context` adds a **"## SIP progress notes"** section (flattens
    `sips[].updates`); counts toward `_has_substantive_signal`; `SCHEMA_HINT` now allows
    action_items from SIP notes too. New cached **`summarize_sips()`** — a small per-SIP Grok
    call that writes a start→date `summary` + `latest_status` onto each **active** SIP (keyed by
    a notes hash, so it only re-runs when a SIP's notes change). Wired into `build_all.py` +
    `build_real_partners.py` next to `analyze`/`analyze_renewal`. Only SIP partners' churn input
    hash changes, so only they re-score (no portfolio-wide drift).
  - `partner.html` + `partner.js`: new collapsible **SIP Progress Notes** card on the Action
    Tracker page — one entry per SIP ticket with a status badge + date range; active SIPs show
    the AI journey summary + latest status with the raw weekly notes behind a "Show updates"
    expander, closed SIPs collapse to a one-liner. Hidden when a partner has no SIPs. The
    MoM/SIP accordions share one builder.
  - `scripts/upload_firebase_data.py` `_SECTIONS` + `auth.js` `SECTIONS`: new **`sip`**
    subcollection (`sips`). `firestore.rules` already covers it via the recursive
    `match /{document=**}` under `partners/{slug}` (comment lists updated). `docs/Data-Schema.md`
    updated (top-level key, subcollection map, source-of-truth table).

## [Unreleased] — CSAT Reconciliation: add Product (MDE) group-by dimension (2026-06-22)

### Added
- **CSAT Reconciliation can now group by Product (MDE) — Self-Managed / Co-Managed**,
  alongside Partner / Account Manager / Regional Manager / Site. Sourced from the Halo
  client custom field **`CFProductMDE`** (the RAG-tab "ProductMDE" field).
  - `extract/halo.py`: added `CFProductMDE` to `_CF_KEYS` so `parse_custom_fields` returns it.
  - `scripts/build_csat_recon.py`: each row now carries `product` (the `CFProductMDE`
    display label, or `—` when unset / numeric-sentinel), mirroring how `site`
    (`CFAccountSite`) is captured.
  - `index.html`: new "Product (MDE)" group-by tab + `GRP_LABEL.product`. The grouping
    logic is generic (`r[reconState.grp]`), so no other JS changed.
  - Published in the existing whole-blob `meta/csatRecon` upload (no `upload_firebase_data.py`
    key change needed). Shipped durably: hosting redeploy + Cloud Run image rebuild so the
    nightly job keeps emitting `product`.

## [Unreleased] — Restrict access to a named 6-person allowlist; remove dup account (2026-06-22)

### Changed
- **Access is now a named allowlist, NOT the whole `@itbd.net` domain** (by request —
  "only these people, no one else for now"). `firestore.rules` `isItbd()` now requires
  `request.auth.token.email in [...]` (the enforced boundary) and `auth.js` gained a matching
  `ALLOWED_EMAILS` list + `isAllowed()` that bounces non-listed accounts at the sign-in overlay
  (cosmetic — rules would deny their reads regardless). The two lists **must stay in sync**; to
  add/remove a person edit BOTH and redeploy rules + hosting. Current allowlist (lowercase):
  `amit.dubey`, `vishal.dogra`, `keith.rozario`, `andrea.canlas`, `lee.cavellier`, `jkhan` @itbd.net.
  `email_verified == true` is still required.

### Removed
- **Deleted a dead duplicate `amit.dubey@itbd.net` Auth account** (uid `N25MyNExZ…`, unverified,
  never signed in) that coexisted with the verified, in-use account (uid `M5nMEG9x…`, kept). The
  two existed because the project permits multiple accounts per email; the unverified one could
  never pass the rules/`auth.js` gate and split UID-keyed `login_audit_summary`.

## [Unreleased] — Provision 5 dashboard users + sign-in audit log (2026-06-22)

### Added
- **Sign-in audit logging.** `auth.js` now calls `recordLogin(user)` when a verified
  `@itbd.net` session resolves, writing two Firestore paths: an immutable event doc to
  **`login_audit`** (`email`, `uid`, `ts`=serverTimestamp, `page`, `user_agent`) and a
  per-user rollup **`login_audit_summary/{uid}`** (`email`, `count` via `FieldValue.increment(1)`,
  `last_login`). A **sessionStorage guard (`pp_login_logged`)** fires it at most once per
  browser-tab session, so reloads / index↔partner navigation don't inflate the count. Writes
  are fire-and-forget and best-effort — a denied/failed write never blocks dashboard access.
  Review counts/times in the **Firebase console** (no client reads). Loaded on **both**
  `index.html` and `partner.html` (shared `auth.js`).
- **`firestore.rules`:** two new client-writable, create/append-only clauses
  (`login_audit/{id}` create-only; `login_audit_summary/{uid}` create + monotonic
  `count == prev + 1` update), each restricted via `isItbd()` to the signed-in user's **own**
  `uid`/`email`, with `keys().hasOnly(...)` locks and no client reads. These are the 2nd/3rd
  client-writable paths after `feedback`.

### Operational
- **Provisioned 5 Firebase Auth accounts** (vishal.dogra, keith.rozario, andrea.canlas,
  lee.cavellier, jkhan @itbd.net) via the Admin SDK with strong random passwords and
  **`email_verified=True`** (admin-vouched, so they sign in immediately without the mailbox
  verification step). Credentials delivered out-of-band, not stored in the repo.
- Deployed: `firebase deploy --only firestore:rules,hosting`.

## [Unreleased] — CSAT recon: reassign NDA monthly-CSAT from Dataprise(57) to PEI(137) (2026-06-19)

### Changed
- **CSAT survey tickets are now attributed by ticket-type/site, not just the Halo client
  they're filed under.** ITBD raises PEI's NDA monthly-engineer CSAT (ticket **type 163**,
  "DES Monthly Engineer CSAT - NDA") under the shared **"Dataprise"** Halo client (**57**),
  but it belongs to **PEI (Dataprise) (137**, the NDA account). `scripts/build_csat_recon.py`
  now applies a reassignment map (`_TICKET_REASSIGN = {(57,163): 137}`): the build resolves
  each survey ticket's **owner** partner, and attributes the TeamGPS response (by `ticket_id`)
  to that owner — **regardless of which partner's blob carries the response** (responses are
  now pooled globally and deduped by id, since the same TeamGPS "Dataprise" responses appear
  in both the PEI and Dataprise caches). Result: **PEI (Dataprise)** shows the NDA CSAT
  (15 sent / 12 received / 100% positive), and **Dataprise (57)** shows 0 (its only CSAT was
  the NDA tickets, now PEI's). `scripts/audit_csat_recon.py` mirrors `_claimed_tickets` for
  sent and skips the cross-blob clients from its per-partner DRIFT check (flags `REASSIGNED`).
  - Caveat: the per-partner **Partner 360 CSAT tile** is still TeamGPS-company based (it can't
    split by ticket type), so Dataprise's tile may still show those responses; the
    **CSAT Reconciliation** report (the authoritative split) attributes them to PEI.

## [Unreleased] — Build Dataprise (active); exclude Network Builders IT (cancelled) (2026-06-19)

### Added
- **Dataprise** (Halo client 57, added to the roster earlier today) **built** to fill the
  allowlisted-but-unbuilt gap → risk 25 / Stable. Confirmed active (`CFMDERAG=Amber`, cancel-risk Low).

### Removed
- **Network Builders IT** (Halo 426) was briefly added (its `Transcripts/` folder was unmatched) but
  is **deliberately EXCLUDED** — it's **not an active DES partner**: `CFMDERAG=0` (below the report-364
  roster threshold), contract **cancelled**, offboarding (`CFHealthReason` "client cancelled the
  contract, RJ LWD May 29"). A cancelled account is a past loss, not a current churn-risk to track —
  same policy as the excluded iStreet/InTelecom. Removed from `scripts/build_real_partners.py` (with a
  do-not-re-add note), the allowlist, GCS, and Firestore. Roster/feed back to **83 partners**.

## [Unreleased] — NPS: require a single unambiguous dominant domain (stop cross-attribution) (2026-06-19)

### Fixed
- **A stray cross-company contact no longer drags another partner's NPS over.** `extract/teamgps.py`
  `_dominant_domains` kept ALL domains tied for the top contact-count, so a 3-way 1-1-1 tie on
  **Perfect Cloud Solutions** (`cloudinvestmentsllc.com` / `milner.com` / `perfectcloudsolutions.com`,
  the `milner.com` from one misfiled contact `bturner@milner.com`) pulled **all 9 of Milner's NPS
  responses** onto Perfect Cloud — its entire NPS was Milner's. Now a domain is only used when it's
  the **single** clear dominant; a tie falls back to exact-email matching. Verified fleet-wide: **only
  Perfect Cloud changes** (NPS 9 → 0, its true value), Milner keeps its own 9 (`milner.com` sole
  dominant), all other 73 partners unaffected. Re-scored both (Perfect Cloud 15/Stable, Milner 30/Low).

## [Unreleased] — Halo client name = single source of truth; add Dataprise (57) (2026-06-19)

### Changed
- **Displayed account names now come from the live Halo Client Name** across every view.
  `scripts/build_real_partners.py` now stores the cache `client.name` as the **Halo** name
  (it previously overrode it with the roster label — which is why "PEI" never picked up
  Halo's "PEI (Dataprise)"); `meta.partner` keeps the roster label (drives the slug +
  Transcripts/ folder matching). `scripts/build_overview.py` then prefers `client.name`
  over the index label for the feed's `name` (slugs unchanged — still explicit). The
  registry path (`extract/build_partner.py`) already used the Halo name. So a Halo rename
  (e.g. "PEI" → "PEI (Dataprise)") propagates to Exec Overview, Partner 360 and CSAT
  Reconciliation automatically — Halo is the one source of truth for the name.

### Added
- **Dataprise (Halo client 57)** added to the roster (`scripts/build_real_partners.py`) and
  the demo allowlist (82 → 83). It is an **independent** DES/MDE account (site PH, RM Pritam
  Das), distinct from **PEI (Halo 137, site NDA)** — the two share engineers, which had
  caused confusion. Dataprise's monthly CSAT is filed under TeamGPS company **"Dataprise"**
  and is the active one (2026 surveys); PEI (137) is the older record (surveys ended 2025),
  so it correctly shows no 2026 CSAT. Each account now appears under its own Halo name with
  CSAT attributed by the Halo client the survey ticket is filed under (verified: all of
  Dataprise's responded surveys join to client 57; none to 137).
- **Roster/allowlist change checklist reminder:** this needs the Cloud Run image rebuilt
  AND the GCS state bucket's `data/_demo_roster.json` updated (cloud reads the allowlist
  from the bucket, code from the image) — otherwise prod silently regresses.

## [Unreleased] — Content-filter fallback so blocked partners still score (2026-06-19)

### Fixed
- **Azure content-filter blocks no longer leave a partner unscored.** Some service-call
  transcripts trip the Grok deployment's "Default" Responsible-AI content filter — a hard
  HTTP 400 (`finish_reason=content_filter`) the SDK does not retry, which left **F12** stuck
  on a stale score across every run. `extract/ai.py:analyze` now catches the content-filter
  error and **retries once without transcripts**, scoring the partner from CSAT/NPS/risk-flags/
  decks instead (flagged `_content_filtered`). Verified: F12 → risk 15/Stable. Also re-scored
  `blackline-it` and `pei`, which were never erroring — they only timed out late in the cloud
  step — bringing the book to **82/82 on `grok-4-1-fast-reasoning`** (published to GCS + Firestore).
  NOTE: the cleaner long-term fix is relaxing the RAI content filter on the `daku` Grok
  deployment (Azure side) so transcripts aren't dropped for filtered partners.

## [Unreleased] — Transcript sub-team folders roll into their parent partner (2026-06-19)

### Fixed
- **Sub-team transcript folders are now ingested.** `extract/transcripts.py` matched a partner to
  exactly one folder (`slugify` equality), so `MSP Corp (HD Team)`, `MSP Corp (SOC)`,
  `MSP Corp(Accounts Payable)`, `MSP Corp(CRDS Group)`, `MSP Corp(MBCCS Group)` were silently
  dropped (slugify keeps the hyphen: `msp-corp-hd-team` ≠ `mspcorp`). New `partner_transcript_dirs()`
  matches on an **alphanumeric-only** key and rolls **sub-team siblings** (folders whose alnum name
  starts with the partner's, ≥6-char floor to avoid collisions) into the parent — MSPCorp now
  ingests all 5 sub-team folders (98 transcript files). Other partners are unaffected.
  - Still unmatched (need a roster decision, NOT auto-added): `Network Builders IT/`, `Dataprise/`.

## [Unreleased] — CSAT Reconciliation: accuracy audit, "still collecting" markers (2026-06-19)

### Added
- **`scripts/audit_csat_recon.py`** — a cross-partner accuracy check for the CSAT
  Reconciliation feed. For every partner it recomputes sent/received/CSAT from source
  (Halo sent tickets + the per-partner `csat_comments`), reusing `build_csat_recon`'s own
  helpers so it can't drift from the builder, and flags: `DRIFT` (published feed disagrees
  with a fresh recompute — i.e. stale), `RECV_GT_SENT`/`RATED_GT_RECV` (impossible),
  `MONTH_SHIFT` (responses attributed to the survey's month but mostly *submitted* in a
  later month — by design, but it's what makes a recent month read low vs a TeamGPS
  submission-date view), `NO_CLIENT`, `HALO_FAIL`. Writes `data/_csat_audit.json`; exits
  non-zero on actionable flags. **First run: 0 drift / 0 impossible across all 82 partners**
  — the data is accurate; the per-month numbers are keyed to the survey's "Month of …"
  subject (so a May survey answered in June/July counts under May), not the submission date.
- **"Still collecting" markers (`index.html`).** Recent months (current + previous,
  derived from the feed `as_of`) are tagged **collecting** and lightly shaded in the
  Breakdown, with a caption explaining that response rate & CSAT % keep rising as late
  responses arrive — so a partial figure (e.g. May 55%) reads as in-progress, not a problem.

### Fixed
- **Unanswered surveys were counted as "received," inflating the response rate and
  showing RR with no CSAT.** The TeamGPS `/csat` endpoint returns *sent* surveys too — a
  not-yet-answered one has `is_responded=false` (empty rating/comment, null
  `submitted_date`). `build_csat_recon` had counted any matched row as received, so
  partners whose recent surveys were still unanswered (e.g. APM IT, Aqueduct, Uptime USA,
  Teal Tech, IronEdge, and Netgain's latest month) showed a response rate but no CSAT %.
  Now a row counts as received only when actually answered: `extract/teamgps.get_csat`
  carries `is_responded`, and `build_csat_recon` (+ `audit_csat_recon`) gate received on a
  `_responded()` check (prefers `is_responded`; falls back to rating/date presence for
  caches built before the field was added). Unanswered surveys no longer count toward RR
  and the misleading "RR but no CSAT" cells are gone.
- **Liongard (and any partner) under-count from a stale feed.** The published feed had been
  built against partner caches that were refreshed moments later, undercounting received
  (Liongard 36 vs the correct 45). Rebuilt against current caches and republished
  `meta/csatRecon`. (Root cause was local-only: a manual out-of-order rebuild; the nightly
  cloud cycle runs `build_csat_recon` *after* the caches are rebuilt, so it can't happen there.)

## [Unreleased] — Recency windows for churn analysis: newest-first + rolling 180d/90d (2026-06-19)

### Fixed
- **Stale meetings no longer distort the churn read.** `extract/ai.py:build_context` previously
  fed the model meetings "newest N by count" **without sorting and with no date cutoff**, so a
  partner could be scored off a 7-month-old call (and even *skip* newer ones). Now calls and
  transcripts are **sorted newest-first** and filtered to a **rolling 180-day analysis window**;
  meetings older than **90 days** are tagged `[HISTORICAL …]` and used as trend/background only —
  the model is told not to surface their (likely-resolved) action items as open.
  - Windows are **rolling (`today − N`)**, not a fixed calendar date, honouring `PARTNERPULSE_ASOF`
    (same "today" as `build_overview`). A fallback keeps the single newest meeting if a
    transcript-only partner has nothing inside the window, so prompts are never empty.
  - **Verified on Milner:** it had been scored off a Nov-2025 transcript (a stale "considering
    other vendors" comment) → risk ~55, **Declining**. With windowing it feeds the four newest
    (May–Jun 2026) calls → risk **25, Stable** — matching the real account state.
  - Changes `build_context` output, so all partners re-score on the next build. New tunables in
    `extract/ai.py`: `ANALYSIS_WINDOW_DAYS=180`, `ACTION_WINDOW_DAYS=90`.

## [Unreleased] — New dashboard view: CSAT Reconciliation (sent vs received) (2026-06-18)

A third sidebar view in `index.html`, below Partner 360, reconciles the monthly DES/MDE
CSAT surveys ITBD **sends** (HaloPSA) against the responses **received** (TeamGPS),
per partner and per month, in the same claymorphic-lavender theme as the rest of the
dashboard. Headline (current run): **1,201 sent / 852 received = 70.9% response rate**
across 82 partners, window **Jan–Jun 2026**.

### Added
- **`extract/halo.py` — `fetch_csat_tickets(client_id)`** pulls a client's monthly-CSAT
  survey tickets (the "sent" side). As with SIPs, Halo has no working server-side
  `tickettype` filter, so it narrows with the free-text `search="Monthly Feedback"`
  (honoured) and keeps rows whose `tickettype_id` is one of the CSAT types
  **`{36, 163, 164}`** (`CSAT_TICKET_TYPE_IDS`) — ~7 pages vs ~17 for a full sweep.
  `CFAccountSite` was added to `_CF_KEYS` so the Site dimension comes through the
  existing client-detail path.
- **`scripts/build_csat_recon.py`** — new aggregator that writes **`data/_csat_recon.json`**.
  It mirrors the dashboard's partner set (reads `data/_overview.json`, already
  demo-allowlist filtered), and per partner: takes the client_id + responses from the
  `data/<slug>.json` cache, fetches the sent tickets + AM/RM/Site from Halo, parses each
  sent survey's **month from the ticket summary** ("…For The Month of May") with the
  **year from `dateoccurred`** (Dec→Jan wrap corrected), and joins responses to sent
  tickets by **`ticket_id`** (each received is attributed to its sent ticket's month, so
  sent and received line up). Window = Jan of the current year → current month
  (`PARTNERPULSE_ASOF` override, same as `build_overview.py`). Per-row Account Manager
  (`accountmanagertech_name`), Regional Manager (`regmanagertech_name`) and Site
  (`CFAccountSite`) let the view re-group the same numbers client-side. `respondedNoMatch`
  = in-window responses whose `ticket_id` matches no in-window sent survey.
- **`index.html` — "CSAT Reconciliation" view** (nav item + section + JS): 6 KPI cards
  (DES/MDE partners, sent, received, response rate, **CSAT % positive**,
  responded-w/o-sent-match), a Chart.js combo (sent/received bars + **two** lines:
  response rate and CSAT % positive), and a Breakdown pivot table with
  **Partner / Account Manager / Regional Manager / Site** grouping, **Monthly / Quarterly**
  period, **Sent-Received / Response-rate / CSAT %** metric toggles, and a row filter.
  Loads lazily on first open via the new `PP_AUTH.loadCsatRecon()`.
- **CSAT % positive** (the satisfaction score, `positive ÷ rated responses`) added to the
  feed per partner / month (`pos`, `rated` per cell; `csat` per month; `csatPct` in totals)
  and surfaced as a KPI, a chart line, and a Breakdown metric. Distinct from the response
  rate: a survey counts as *received* once it gets any response (distinct answered tickets,
  so received ≤ sent), while CSAT % rates the sentiment of those responses.
- **Breakdown "CSAT %" mode now shows the response rate alongside it** — each cell
  stacks a labelled **CSAT** %-positive badge and an **RR** response-rate badge, so
  satisfaction can be read against how many actually responded. (The "Sent / Received"
  and "Response rate" modes are unchanged.)
- **Typography polish:** enabled `-webkit-font-smoothing: antialiased` /
  `text-rendering: optimizeLegibility` on `body`, and switched the Breakdown table to
  **tabular figures** with lighter, cleaner numeric cells (was the heavy display font) so
  the dense sent/received/% columns read cleanly and align.
- **Published to production:** wrote the `meta/csatRecon` Firestore doc and ran
  `firebase deploy --only hosting` so the view is live.

### Fixed
- **CSAT Reconciliation showed "No data yet" in production** for returning users.
  `index.html` is served `no-cache` (always fresh) but `auth.js` is cached
  `max-age=3600`, so a returning user loaded the new HTML against a stale cached
  `auth.js` that lacked `loadCsatRecon` → the method was undefined and the view fell
  back to its empty state. Fixed by making the always-fresh `index.html` self-sufficient:
  `loadReconData()` uses `PP_AUTH.loadCsatRecon` when present, else reads `meta/csatRecon`
  directly via the Firebase SDK (prod) or fetches the local JSON (dev). No dependency on
  the cached `auth.js` revision.
- **Prevented the whole class of drift:** `firebase.json` now serves the bootstrap files
  `auth.js` + `firebase-config.js` with `Cache-Control: no-cache` (a new, more-specific
  header rule that overrides the generic `**/*.@(js|css)` `max-age=3600`). The data/auth
  layer is now always as fresh as the no-cache HTML that loads it, so a future `auth.js`
  change can't leave returning users on a stale revision. Other JS/CSS keep the 1-hour
  cache. Verified live: `auth.js`/`firebase-config.js` → `no-cache`, `partner.js`/`styles.css`
  → `max-age=3600`. (The doc was written surgically
  rather than via a full `upload_firebase_data.py` run, to avoid overwriting prod's
  partner tree with local caches; the nightly Cloud Run Job — once its image carries the
  new `build_csat_recon.py` step — refreshes `meta/csatRecon` going forward.)
- **`auth.js` — `loadCsatRecon()`** returns the feed: Firestore `meta/csatRecon` in prod,
  `data/_csat_recon.json` on localhost (same two-runtimes-one-shape contract as
  `loadOverview`).
- **`scripts/upload_firebase_data.py`** publishes `data/_csat_recon.json` as the single
  Firestore doc **`meta/csatRecon`** (written with the `meta/overview` sentinel batch).
  The file is optional — its absence leaves the view empty; a corrupt file aborts the run.
- **Sync cycle:** `build_csat_recon` added as a soft step after `build_overview` in both
  `scripts/cloud_sync.py` (nightly Cloud Run Job) and `server.py` `SYNC_STEPS` (local).
  A failure leaves the recon view stale but never blocks the core publish.

## [Unreleased] — AI prompt: cite CSAT as a percentage, not the raw count (2026-06-18)

### Fixed
- **CSAT now passed to the model as a pre-computed percentage.** `extract/ai.py:build_context`
  previously fed only raw CSAT counts (`{'Positive': 75, ...}`), and the model misread
  "Positive: 75" as "75% positive" when the true rate is 97.4%. The prompt now adds a
  **`## CSAT summary`** line with the computed `% positive` / `% negative` and an explicit
  instruction to cite the percentage (counts are labelled as counts). Verified on Community IT:
  the driver evidence changed from "CSAT 75% positive" to "97.4% positive CSAT" (risk unchanged
  at 25). NOTE: this changes `build_context` output, so every partner's `_input_hash` changes and
  the next build re-scores all partners (the dashboard CSAT tile already showed the correct % —
  it is computed from data, not the model).

## [Unreleased] — AI churn engine switched to Grok (`grok-4-1-fast-reasoning`) via Azure AI Foundry; cloud nightly back online (2026-06-18)

The AI churn-analysis engine now runs on **Grok** — deployment `grok-4-1-fast-reasoning`
— served through an **Azure AI Foundry OpenAI-compatible endpoint** using the plain
**OpenAI SDK** (`from openai import OpenAI`, `base_url` + `api_key`), **not** the
`AzureOpenAI` client. This replaces the original Azure `gpt-5.4` and reverts/replaces a
short-lived Claude Agent SDK experiment from earlier the same day.

**Why:** the org's `gpt-5.4` Azure deployment is type "Global Batch" (asynchronous,
batch-only) and cannot serve the pipeline's synchronous per-partner calls. The
`grok-4-1-fast-reasoning` deployment is "Global Standard" (synchronous), so it serves the
per-partner requests directly over the OpenAI v1 surface.

### Changed
- **`extract/config.py`** — replaced the `AZURE_OPENAI_*` constants with provider-neutral
  AI config: `AI_BASE_URL` (`https://daku.services.ai.azure.com/openai/v1/`), `AI_API_KEY`
  (Secret Manager / `.env` first, in-repo baked fallback for local dev), and `AI_MODEL`
  (default `grok-4-1-fast-reasoning`).
- **`extract/ai.py`** — now builds an `OpenAI` client from `config.AI_BASE_URL` +
  `config.AI_API_KEY` (singleton) and makes a **synchronous** `chat.completions.create`
  call with `response_format={"type": "json_object"}` and
  `max_completion_tokens=8000`. `max_retries=5` because the deployment is rate-limited
  (**50k TPM / 50 RPM**) — the SDK backs off on 429s. JSON is parsed via the tolerant
  `_extract_json` helper (strips a stray code fence / leading reasoning token, else grabs
  the outermost `{...}` object). The per-partner AI cache now records
  `"_model": "grok-4-1-fast-reasoning"`, and the **cache-validity check additionally keys
  on `_model`** (`cached_ai.get("_model") == config.AI_MODEL`), so a model switch
  invalidates stale caches and re-scores cleanly. The result JSON shape is unchanged and
  `CACHE_SCHEMA_VERSION` stays `2`.
- **`scripts/seed_secrets.py`** — the secret entry changed from `azure-openai-key` to
  `ai-api-key`.
- **`.env.example`** — updated to document `AI_BASE_URL` / `AI_API_KEY` / `AI_MODEL`.
- **Frontend (`index.html`, `partner.html`, `partner.js`)** — the visible
  "Azure gpt-5.4" / "gpt-5.4" engine labels now read "Grok".

### Added
- A new Secret Manager secret **`ai-api-key`** holding the Grok/Foundry key.

### Removed
- The `AZURE_OPENAI_*` constants from `extract/config.py` and the `azure-openai-key`
  entry from `scripts/seed_secrets.py`.

### Deployed
- **Cloud nightly pipeline is fully online again** (not the "manual/retired" posture from
  the reverted Claude experiment). The nightly Cloud Run Job `partnerpulse-nightly` and
  Cloud Scheduler trigger `partnerpulse-nightly-trigger` remain **enabled**. Created the
  `ai-api-key` secret, rebuilt the pipeline image, and updated the Cloud Run Job to inject
  `AI_API_KEY` (from `ai-api-key`) plus `AI_BASE_URL` / `AI_MODEL` env, replacing the old
  `AZURE_OPENAI_KEY` (from `azure-openai-key`).

## [Unreleased] — AI outage no longer zeroes scores; restore after Azure key revocation (2026-06-18)

### Incident
The Azure OpenAI key (`AZURE_OPENAI_KEY`) was revoked/rotated between 2026-06-17 and
the 2026-06-18 01:00Z nightly. Every partner whose AI input changed that night re-ran
gpt-5.4, hit **HTTP 401**, and `ai.analyze` returned `risk_score=None` → `build_overview`
wrote `churnRisk=0`. 28 partners published to Firestore with a phantom **0 / "Healthy"**
score (Community IT, Marco, Logically, MSP Corp, Atlas, …); cache-reuse had masked the
dead key on prior nights.

### Fixed
- **`extract/ai.py` `analyze` now degrades gracefully.** On any LLM exception, if a usable
  prior cached result exists it is returned (flagged `_stale` / `_stale_reason`) instead of
  regressing the score to `None`/0. A transient AI outage can no longer wipe the book's
  scores — they hold at last-known-good until the next successful run.

### Restored
- Republished the last-good local `_overview.json` (79 scored) to Firestore and reseeded
  the GCS state-bucket partner caches, so the dashboard shows real scores again and the
  next nightly reuses them.

### Action required (operator)
- **Provide a valid Azure OpenAI key.** The current key 401s everywhere (verified live).
  Endpoint `https://leonwisoky.cognitiveservices.azure.com/`, deployment `gpt-5.4`. Update
  via `python scripts/seed_secrets.py` / Secret Manager `azure-openai-key` AND
  `extract/config.py`. Until then scores cannot be refreshed (they hold at last-good).

## [Unreleased] — Fix phantom "active SIP" in AI churn analysis + nightly roster regression (2026-06-17)

Two production-data corrections.

### Fixed
- **AI churn analysis treated stale `CFNextStep`/`CFSIPTicketMDE` as an active SIP.**
  `extract/ai.py` `build_context` fed the model the free-text `next_step` /
  `sip_ticket` client custom fields but **not** the authoritative open/closed SIP
  counts from `halo.count_sips` (which checks each ticket's real status). When an
  account team cancels a SIP without resetting `CFNextStep` (e.g. **Community IT**:
  `CFNextStep="SIP Is in progress"`, but its only SIP ticket **778319 is Cancelled**
  → `sip_open=0`), the model reported a non-existent "Active SIP" as the top churn
  driver and inflated the score. `build_context` now appends an authoritative
  correction line **only when the narrative implies a SIP but 0 are open**, so
  unaffected partners' context (and AI cache) stay byte-identical — no needless
  re-score. Re-scored the 4 affected partners: **Community IT 68 (High) → 42
  (Watch/Medium)**, RedHelm-1Path 32 → 28, Continuous Networks 12 → 14, Matador 18 → 18.
- **Nightly Cloud Run job regressed the roster 82 → 79.** The `pipeline:latest`
  image (built 06-16 12:18) predated the 06-16 15:42 "82 partners" roster commit,
  **and** the GCS state bucket's `data/_demo_roster.json` allowlist still listed only
  79 slugs — so the nightly dropped CPCORP, Stratti, and Mission Technology. Rebuilt
  the image, synced the 82-entry allowlist + the missing CPCORP/Stratti caches to the
  state bucket, and republished Firestore.

### Deployed
- Rebuilt `…/partnerpulse/pipeline:latest` (Cloud Build); job picks it up next run.
- `python scripts/upload_firebase_data.py` — republished 82 partners to Firestore
  with the corrected scores.
- Synced `data/_demo_roster.json` + corrected partner caches to
  `gs://operational-intelligence-ebe23-pipeline-state/data/` so the next nightly
  reuses the corrected AI cache (no re-run/drift) and keeps the full 82 roster.

## [Unreleased] — Public feedback form (2026-06-17)

Added a shareable, ungated feedback form so anyone (partners, colleagues, anyone
with the link) can send feedback and suggestions about the product. Submissions go
straight to Cloud Firestore; reviewed in the Firebase console (no in-app reader yet).

### Added
- **`feedback.html`** — a standalone, self-contained public page (ITBD brand
  palette, matching the sign-in overlay). Fields: optional name / email /
  company-role, a feedback category, an optional 1–5 star rating, and a required
  message (≤5000 chars) with a live char count; success + "submit more" states.
  It loads `firebase-config.js` + the firestore compat SDK but **deliberately NOT
  `auth.js`** — there is no sign-in gate. Writes one auto-id doc to the new
  `feedback` collection (`message`, `category`, `page`, `user_agent`,
  `submitted_at` server time, plus the optional fields).
- **`firestore.rules`:** new `feedback` collection — unauthenticated **CREATE
  only**, gated by an `isValidFeedback()` validator (required `message` 1–5000
  chars, `submitted_at == request.time`, optional fields type/size-capped, key set
  locked via `hasOnly`). No client reads/updates/deletes. This is the **only**
  client-writable path; everything else stays deny-all (the pipeline writes via
  the Admin SDK).
- **Sidebar link** in `index.html` — a "Share feedback" entry in the sidebar
  footer that opens `feedback.html` in a new tab.

### Deployed
- `firebase deploy --only hosting,firestore:rules` — rules compiled + released,
  form live at `https://operational-intelligence-ebe23.web.app/feedback.html`
  (HTTP 200 verified).

### Docs
- Updated `CLAUDE.md`, `README.md`, `docs/architecture.md`,
  `docs/Data-Schema.md`, `docs/Firebase-Deploy-SOP.md`, and `docs/LLM-SOP.md` to
  record the new public-write path and that "all client writes denied" is now
  "dashboard client writes denied, public `feedback` create-only".

---

## [Unreleased] — Roster reconciled to report 364: +2 partners, un-hid Mission Technology (2026-06-16)

Reconciled the dashboard against HaloPSA **report 364 "DES RAG Status"** after a
roster-gap query. The dashboard now shows **82** partners (was 79).

### Added
- **CPCORP Inc** (Halo 968) and **Stratti** (Halo 636) — `CFMDERAG>=1` report-364
  members that were never built. New `NEW` entries in `scripts/build_real_partners.py`
  (now **72** entries), built with full Halo + TeamGPS + gpt-5.4.

### Changed
- **Mission Technology** (Halo 975) **un-hidden** — it was built + indexed but missing
  from the `data/_demo_roster.json` allowlist (flagged by the audit). The allowlist was
  regenerated with `scripts/discover_des_roster.py --write` (now **82** slugs).
- Published the 82-partner feed to Firestore (`upload_firebase_data.py`); the sanity
  gate passed (count rose 79→82).

### Excluded (deliberate)
- **iStreet Solutions** (89) and **InTelecom** (81) — inactive accounts, kept in
  `discover_des_roster.py` `EXCLUDE_IDS` per ops.
- **Evernet** — on report 364 but has **no Halo client record**; cannot be built until
  ops provides a client id (tracked in `discover_des_roster.py` `UNRESOLVED`).

### Note
- The new client-name-mismatch guard in `build_real_partners.py` **skipped 2** existing
  partners this build (fuzzy display-vs-Halo-name check); they retain their prior caches
  and remain on the dashboard. The guard may be over-strict on known name-drift cases
  (e.g. "PEI" vs "Dataprise (PEI)") and is worth loosening — follow-up.

### Changed — sign-in UI (`auth.js`)
- **Login overlay restyled to the IT By Design brand.** Replaced the generic
  purple/lavender theme and placeholder "P" tile with the real ITBD logo
  (`assets/itbd-logo.webp`, served from the new repo `assets/` dir — Firebase
  hosting `public:"."` serves it; not in the `ignore` list) and the brand palette
  sampled from that logo: cyan-blue `#08A8D8`, deeper blue `#0C8FC0`, lime-green
  accent `#B8D030`, ink `#0F2C3A`. New look: branded blue→navy gradient backdrop,
  white card with a blue→green accent stripe, focus-ringed inputs, gradient primary
  button, and an "Authorized @itbd.net users only · Secured by Firebase" footer.
- `buildOverlay()` now injects a `<style>` block **scoped to `#pp-auth-overlay`**
  (so it can't leak into the dashboard) instead of all-inline styles; **all element
  IDs are unchanged** (`pp-email`/`pp-password`/`pp-auth-btn`/`pp-toggle`/
  `pp-forgot`/`pp-verify-actions`/`pp-verified-reload`/`pp-resend`/`pp-auth-msg`/
  `pp-auth-title`), so the sign-in / sign-up / verify-pending logic is untouched.
  `setMsg`'s neutral text colour moved `#4b5168` → `#5a6b75` to match.
- Prod-only (the overlay renders only when `auth.js` is in Firebase mode); local
  dev is unaffected. Verified by screenshotting the real code path under headless
  Chrome with a stubbed `firebase`.

---

## [Unreleased] — Audit hardening: publish safety, data-accuracy, resilience, UX, docs (2026-06-16)

Ran a comprehensive multi-agent ("ultracode") audit of the new Firebase + cloud
pipeline and the wider codebase (67 verified findings), then remediated them via
file-partitioned subagents. Net effect: the nightly pipeline is now recoverable,
guarded, and observable, and several long-standing data-accuracy bugs are fixed.

### Fixed — data accuracy
- **NPS cross-attribution** (`extract/teamgps.py`, `extract/halo.py`) — `get_users`
  no longer harvests free-mail (gmail/outlook/…) domains, and `filter_nps` now
  matches on a partner's **dominant corporate domain(s)** instead of every stray
  contact domain. Fixes the gmail respondents counted across ~5 partners and
  **Perfect Cloud Solutions' NPS being identical to Milner's** (stray `@milner.com`
  contacts). `audit_data.py` gained NPS-quality checks that flag these.
- **SIP over-count** (`extract/halo.py: count_sips`) — bucket-B now requires
  **word-boundary** name matches and drops short tokens, so tickets like
  `teal`/`tab`/`f12` no longer match other clients' SIPs.
- **Wrong-`client_id` guard** (`scripts/build_real_partners.py`, `extract/halo.py:
  fuzzy_name_match`) — warns/flags when a fetched Halo client name doesn't match
  the expected partner (the Acrisure 937→79 class).

### Fixed / Added — pipeline resilience
- **Firestore publish is now gated + ordered safely** (`scripts/upload_firebase_data.py`)
  — validates all blobs + the feed up front, **aborts if the partner count drops >
  `PP_MAX_DROP_PCT` (default 20%)** or the feed is empty/stale, and writes
  `meta/overview` **last** as a completion sentinel. The destructive stale-partner
  reconcile is guarded by the same gate. No more silent partner deletion from a thin
  build.
- **`cloud_sync.py`** — state is **pushed before** the hard publish and guaranteed via
  `try/finally` (never discards freshly-pulled transcripts/AI on an upload failure);
  per-step **timeouts**; **refuses to publish** stale data if `build_overview` failed;
  a **cache-bust guard** (aborts if the pulled `data/` is implausibly small) to avoid a
  cold full gpt-5.4 re-run + score drift; a `data/` **state-prune** (mirrors deletions);
  and an end-of-run **`RUN SUMMARY`** line (emitted on every path, for alerting).
- **GCS state bucket: Object Versioning ON** — a bad nightly run is now recoverable;
  rollback runbook added to `docs/Cloud-Pipeline-SOP.md`.
- **`extract/ai.py`** — Azure client `timeout`/`max_retries`; a cache **schema version**
  so malformed/old cached results invalidate; `build_context` now includes transcripts
  and returns a low-confidence **"insufficient data"** result instead of scoring an empty
  prompt.
- **`extract/config.py`** — emits a loud (non-secret) warning when a credential falls
  back to the in-repo baked default (i.e. the env var is unset) so cloud misconfig is
  visible.

### Fixed — feed & operability
- **`scripts/build_overview.py`** — replaced the hardcoded `TODAY = 2026-06-13` with
  `date.today()` (env `PARTNERPULSE_ASOF` override) so overdue/stale logic works
  unattended; **warns on built-but-excluded** partners (surfaced the silently-hidden
  `mission-technology`); zero-data partners now get an **"Insufficient data"** band and
  are excluded from `avgRisk` instead of reading as confident "Healthy".
- **`extract/textutil.py`** (new) — one canonical `slugify`/`normalize`, replacing three
  divergent copies in `build_real_partners.py`, `audit_data.py`, `transcripts.py`.
- **`scripts/audit_data.py`** — new checks: NPS domain credited to >1 partner, free-mail
  in an NPS set, off-corporate-domain respondents, client-name mismatch, and
  built-but-excluded-by-allowlist.

### Fixed — frontend & auth
- **Dead Sync UI removed** — stale `.sync-btn`/`.sync-panel`/`@keyframes sync-spin` CSS
  and `/api/refresh` comments stripped from `index.html` + `styles.css`.
- **Loading + production-aware errors** (`index.html`, `partner.js`) — a loading state
  during Firestore reads; the error handler branches on `PP_AUTH.mode` (friendly
  "couldn't load, retry" in prod instead of local-CLI hints).
- **Mobile** — a header toggle so the Overview ↔ Partner 360 view switch is reachable
  on phones (sidebar was hidden < 760px).
- **Auth UX/security** (`auth.js`) — email-verification no longer dead-ends (sign-in
  mode + resend + "I've verified, reload"); overlay is accessible (`role=dialog`, labels,
  autofocus, Enter-to-submit, `aria-live`); forgot-password no longer leaks account
  existence; client password minimum raised to 12.
- **`storage.rules`** (new, deny-all) wired into `firebase.json`; `firestore.rules`
  comment marks `isItbd()` as the single load-bearing access clause.
- **`firebase-config.js`** — corrected the stale comment referencing a non-existent
  Cloud Function.

### Docs
- `architecture.md` (Graph as a first-class source; `.vtt` via the app-only
  `pull_graph_transcripts.py`, not the superseded connector), `Cloud-Pipeline-SOP.md`
  (rollback runbook, versioning, `pip install google-cloud-secret-manager`),
  `Firebase-Deploy-SOP.md` (deploy = UI/rules only, cloud add-a-partner procedure,
  region `us-central1`), `CLAUDE.md`/`README.md`/`Data-Schema.md`/`LLM-SOP.md`
  (counts reconciled, `storage.rules` + `extract/textutil.py` registered).

### Still outstanding (owner action — not code)
- **Rotate** the reused Halo/TeamGPS/Azure/Graph keys in their source systems +
  publish new Secret Manager versions (the committed `config.py` fallbacks are a
  standing leak until then). Azure **budget alert**, Firebase **App Check** + **MFA**,
  and a Cloud Monitoring **failed-run alert** are console/owner tasks.

---

## [Unreleased] — Pipeline moved to the cloud; nightly auto-sync; sync button removed (2026-06-16)

The data pipeline now runs **fully in the cloud, unattended** — no local machine
in the loop. A **Cloud Run Job** (`partnerpulse-nightly`) runs the whole cycle and
republishes Firestore, triggered by **Cloud Scheduler at 21:00 America/New_York**
(9pm Eastern, DST-aware). Chose Cloud Run Job over Cloud Functions: the cycle is a
5–30 min multi-step batch with a build working dir — a poor fit for Functions.
Full runbook: **`docs/Cloud-Pipeline-SOP.md`**.

### Added
- **`scripts/cloud_sync.py`** — the Job entrypoint: optional GCS state pull →
  the 5 SYNC_STEPS (transcripts → build_all → build_real_partners → reindex →
  overview, continue-on-failure) → `upload_firebase_data.py` (hard) → GCS state
  push. State (`data/` + `Transcripts/`) is persisted in a Cloud Storage bucket
  so the gpt-5.4 cache survives (no run-to-run score drift) and transcripts
  outlive Teams' ~90-day content retention.
- **`scripts/seed_secrets.py`** — loads the pipeline keys (Halo/TeamGPS/Azure/
  Graph) into Secret Manager without printing values; re-run to publish a new
  version after rotation.
- **`Dockerfile`** + **`.dockerignore`** — `python:3.12-slim` image; pip-installs
  `requirements.txt` + `google-cloud-firestore` + `google-cloud-storage`. The
  ignore file keeps `data/`, `Transcripts/`, `.env`, `.git`, and the frontend out
  of the image (`.firebaserc` is kept — the upload script needs it).
- **`docs/Cloud-Pipeline-SOP.md`** — architecture, resource names, one-time
  provisioning commands, operate/runbook.

### Changed
- **Manual "Sync Data" button REMOVED** from `index.html` and `partner.html`. The
  `#sync-btn` markup is gone; `refresh.js` is reduced to rendering the "Last sync"
  freshness label (`#sync-stamp`) from `portfolio.generated_at` (prod: Firestore
  `meta/overview`; local: `data/_index.json`). Auto-sync replaces it; in-app sync
  no longer exists. (The now-unused `.sync-btn`/`.sync-panel` CSS is left in place;
  harmless.)
- **Secrets** lifted into Secret Manager as-is (reused, not rotated — per
  decision 2026-06-16); rotation still owed (SOP "Notes").

### Deploy
- Provision per `docs/Cloud-Pipeline-SOP.md` (Owner `gcloud auth login`), then
  `firebase deploy --only hosting` to ship the button removal.

---

## [Unreleased] — Auth switched from Google to email/password (2026-06-16)

ITBD is on **Microsoft 365, not Google Workspace**, so there is no Google
identity on `@itbd.net` to federate. Replaced the Google sign-in with
**email/password** sign-in in `auth.js` (production path only; DEV/localhost
unchanged).

### Changed
- **`auth.js`** — production overlay is now an email + password form with
  sign-in / create-account / forgot-password, all restricted to `@itbd.net`
  client-side. The access boundary is **email verification**: unverified users
  are held at a "check your inbox" state and signed out (a verification link is
  sent best-effort), and `firestore.rules` already deny reads until
  `email_verified` is true — so access == controls an `@itbd.net` mailbox.
- **`firestore.rules`** — comment only; the rule (`email_verified == true` +
  `@itbd.net` regex) was already correct and is unchanged, so **no rules
  redeploy is required**.
- **`docs/Firebase-Deploy-SOP.md`** — setup/verify steps updated for
  Email/Password (enable the provider, not Google).

### Deploy
- Re-run `firebase deploy --only hosting` (UI change only).
- **Console:** enable **Authentication → Sign-in method → Email/Password**;
  disable the now-unused **Google** provider.

---

## [Unreleased] — Full DES/MDE partner roster from Halo report 364 (2026-06-15)

Expanded the dashboard from the 20-partner CTO-demo subset to the **complete
DES/MDE book of business** — every account ITBD's Dedicated Services manages,
sourced authoritatively from HaloPSA **report 364 "DES RAG Status"** (filter:
`Area.CFMDERAG >= 1`). 36 new partners built and onboarded; dashboard now shows
**77 partners**.

### Added
- **36 new partners** in `scripts/build_real_partners.py` `NEW` (now 68 entries):
  the remaining RAG-managed DES/MDE accounts not previously onboarded. Display
  names are corp-suffix-stripped so the Graph transcript pull's folders
  auto-match; `teamgps_company` is the exact Halo client name; `client_id` pinned
  from a full `/api/Client` enumeration cross-checked against `CFMDERAG`.
  Excluded by request: InTelecom (81, inactive), iStreet Solutions (89, going
  inactive). Deduped: kept TAB Computer Systems 163 (dropped 971), Spidernet 1003
  (dropped 1006).
- **`data/_demo_roster.json`** regenerated to the **77 DES/MDE slugs** (was 20),
  derived by matching built caches to the report-364 Halo id set. Still
  sync-proof and reversible (gotcha 8).

### Changed
- **`extract/halo.py` `get()`** — added retry/backoff for transient Halo failures
  (5xx / 429 / dropped connections), mirroring `pull_graph_transcripts.get`. A
  single 500 on `/Tickets` used to abort a whole multi-partner build.
- **`scripts/build_real_partners.py`** — the per-partner service-ticket fetch is
  now continue-on-failure: a persistent Halo 5xx on one client no longer aborts
  the batch (that partner builds without Halo call-notes, still gets
  transcripts + CSAT/NPS + AI). 4 of the 36 hit this path on this run.
- **Acrisure Cyber Services** repinned from Halo id **937 → 79**. Halo has two
  records; 79 is the real DES-managed one (`CFMDERAG=Green`, `CFProduct=MDE`),
  937 was an empty duplicate. Rebuilt with real health data.

### Data / refresh
- Ran the Graph transcript pull (`--write`): 26 new `.vtt` written, 125 already
  present; older calls past Teams' ~90-day content retention expired (expected).
- Reindexed (`_index.json` → 78 built partners) and rebuilt `_overview.json`
  (77 shown): 26 active SIPs across 23 partners, 287 open actions (19 overdue),
  portfolio NPS 86, CSAT coverage 84%.
- **Audit (`audit_data.py`)**: SIP counting, AI analysis, and feed/index
  integrity all clean. Open WARNs are coverage gaps, not pipeline faults — 3
  empty-CSAT (likely TeamGPS name mismatch: PEI, LATG, Spidernet), 14 stale/absent
  last-call (newly-onboarded partners with no recent Halo note and transcripts
  expired past 90d), 9 unmatched transcript folders (MSP Corp end-team splits,
  Dataprise→PEI, and non-DES orgs).

---

## [Unreleased] — Firebase deployment scaffolding, ALL-Firestore sharded data (2026-06-15)

Scaffolding to take the dashboard live on **Firebase** (Hosting + Firestore),
authenticated and internal-only (`@itbd.net`). Project
`operational-intelligence-ebe23` (Blaze). **Not deployed yet** — backend
services must be created in the console and rules/data pushed; see
`docs/Firebase-Deploy-SOP.md`. Local `python server.py` workflow is **unchanged**
(auth + Firestore auto-disable on localhost — data still read from `data/`).

**All data lives in Firestore, sharded** (chosen for maintainability + scaling:
a single per-partner blob grows unbounded as transcripts/decks accumulate and
would eventually cross Firestore's 1 MiB doc cap; sharding removes that ceiling,
allows writing one new item without rewriting the partner, gives cross-partner
queries, and makes the data browsable doc-by-doc in the console):

```
meta/overview                     portfolio rollups + coverage  (Exec Overview)
partners/<slug>                   summary doc                   (Exec Overview)
partners/<slug>/detail/profile    { meta, client, ai, csat_stats, nps_stats }
partners/<slug>/transcripts|decks|calls|csat|nps|actions/<i>    detail, 1 doc/item
```

Each detail doc carries `_i` = its source-list index; the dashboard restores
order via `orderBy('_i')`. Cloud Storage and the `getData` Cloud Function from
the first scaffolding pass were **dropped** — no longer needed now that the big
blob is gone. (Cloud Functions remain available for the future off-host "Sync
Data" trigger.)

### Added
- **`firebase.json`** — Hosting + Firestore config. Hosting serves the static UI
  from the repo root with an `ignore` list excluding everything non-web
  (`data/**`, `decks/**`, `extract/**`, `scripts/**`, `*.py`, `.env`, …) — **no
  data/ is served statically**. No function rewrites (data is read from Firestore
  directly by the Web SDK).
- **`firestore.rules` / `firestore.indexes.json`** — read on `meta/*` and
  `partners/{slug}/{document=**}` (summary + profile + all subcollections) only
  for verified `@itbd.net` accounts; all client writes denied (pipeline writes
  via Admin SDK). Empty indexes (overview fetches all summary docs, filters
  client-side; see SOP for the paginated-query upgrade past a few hundred partners).
- **`scripts/upload_firebase_data.py`** — publishes the sharded tree from
  `data/_overview.json` + the caches: `meta/overview`, `partners/<slug>` summary,
  `detail/profile`, and the six detail subcollections (doc id = zero-padded
  index, `_i` order field). **Idempotent + reconciled**: per subcollection, docs
  beyond the current count are deleted; partners no longer in the feed are
  removed entirely (summary + profile + subcollections). `--dry-run` prints the
  plan + per-section counts. Project defaults from `.firebaserc`. Hidden partners
  never reach Firestore (the feed already honours the allowlist).
- **`auth.js` + `firebase-config.js`** — shared client gate + Firestore data
  layer, loaded with the Firestore SDK by BOTH `index.html` and `partner.html`.
  Prod: Google sign-in restricted to `@itbd.net`; `loadOverview()` reads
  `meta/overview` + `partners/*`, `loadPartner(slug)` reassembles the profile +
  subcollections into the old blob shape, `lastSyncStamp()` reads
  `meta/overview.generated_at`. **Localhost / unconfigured / no-SDK → DEV mode**:
  no sign-in, everything read straight from `data/` (workflow preserved).
  `firebase-config.js` holds the **public** web config (real values, safe to commit).

### Changed
- **`index.html`** — Overview loads via `window.PP_AUTH.loadOverview()` (Firestore
  in prod, `data/_overview.json` in dev); added the `firebase-firestore-compat`
  SDK tag. **`partner.js`** — detail loads via `window.PP_AUTH.loadPartner(slug)`
  (sharded Firestore in prod, `data/<slug>.json` in dev) — same assembled shape,
  so the render code is untouched. **`partner.html`** — added the Firebase
  app/auth/**firestore** SDK tags + `firebase-config.js` + `auth.js`. **gotcha 7
  still holds** — those tags live in BOTH `index.html` and `partner.html` heads.
- **`refresh.js`** — "Last sync" timestamp via `PP_AUTH.lastSyncStamp()`
  (Firestore in prod, `data/_index.json` in dev). The "Sync Data" button still
  degrades gracefully where the sync API is absent (it is, in prod — the pipeline
  runs off-host for now).

### Toolchain / setup done this session
- Installed Node.js LTS (v24) + `firebase-tools` 15.20.0; `firebase login`;
  `.firebaserc` default set to `operational-intelligence-ebe23`;
  `firebase-config.js` filled from `firebase apps:sdkconfig`.

### Security / pre-deploy TODO (not code)
- **Rotate the live API keys** in `.env` / `extract/config.py` (Halo, TeamGPS,
  Azure, Graph) and move them to Secret Manager before any deploy — README
  warning. Never part of the Hosting deploy (excluded by `ignore`).
- Create in the console: **Auth → Google** + **Firestore** (production mode).
  Then push rules + data + `firebase deploy --only hosting,firestore:rules`.

---

## [1.0.0-beta.9] - 2026-06-14

Pre-CTO-demo fixes from an expert review of the dashboard.

### Changed
- **Docs swept per LLM-SOP** — `CLAUDE.md`, `README.md`, `docs/architecture.md`, and `docs/LLM-SOP.md` updated to reflect `scripts/audit_data.py`, the **demo-roster allowlist** (`data/_demo_roster.json`, CLAUDE gotcha 8 / SOP invariant 10), the **42-partner** roster (10 registry + 32 NEW incl. the 4 demo adds), the restored "Who needs attention" chart, and the deterministic risk-band + trend reconciliation.

### Fixed
- **Risk band is now a single, deterministic source of truth.** The Exec Overview banded by the numeric score (High ≥45 · Watch ≥25 · Healthy) while the Partner 360 drilldown displayed gpt-5.4's free-form `risk_band`, which was mis-calibrated against its own score — e.g. **APM IT (63) showed "Medium" in the drilldown but counted as High-Risk in the exec KPIs.** `partner.js` now derives the band from `risk_score` with the same thresholds (`bandFromScore`, labelled High/Medium/Low) instead of the raw LLM band; `build_overview.py` sets `riskBand = _tier(risk)` deterministically. APM now reads **High** everywhere. (gpt-5.4's `risk_band` is still kept in the per-partner cache, just no longer displayed.)
- **Sentiment trend can no longer contradict the hard signals.** The LLM trend never emits "Declining" and had tagged **Proda (risk 72, Negative tone) as "Improving."** Added `build_overview._reconcile_trend`: a high-risk + Negative account now shows **Declining**, and a high-risk account never shows "Improving" (downgraded to Stable). Proda now reads **Declining**. Call-tone derivation is unchanged (still uses the raw AI trend — it's a hard signal feeding renewal risk); only the *displayed* trend is reconciled. Follow-up noted: replace the LLM trend with a real time-based trend from per-call tone history.

### Added
- **Executive Overview — "Who needs attention" risk-ranking chart restored**, **stacked full-width above the At-risk table** (`.overview-split` is single-column) as the first row below the KPI cards — so the At-risk table spans the full width and all its columns (Partner · Risk · Call tone · Top driver · SIP · Action Driver) show without horizontal scrolling. (Started side-by-side; switched to stacked per review — a 6-column table + chart sharing a row cramped both.) Worst-first horizontal bars (Chart.js, tier-coloured gradients, value labels, ▼ on declining-trend partners — now meaningful after the trend fix), collapsed to the top 10 of the filtered set with a "Show all N" / Collapse toggle. Anchors the Overview so "who's in trouble" reads at a glance. `index.html` only; the At-risk table keeps its existing columns. (Also added the missing `.sr-only` rule — the AIODI rebuild had dropped it, so the chart's screen-reader text fallback was rendering as visible messy text below the chart; it's now properly hidden while still read aloud.)

---

## [1.0.0-beta.8] - 2026-06-13

### Added
- **CTO-demo roster curation (2026-06-14).** Onboarded 4 partners (`Acrisure Cyber Services` 937, `Byte Solutions Inc` 38, `SERVICAD` 154, `OutsourceIT` 928) in `build_real_partners.py` NEW, and added a **demo-roster allowlist**: if `data/_demo_roster.json` (a list of slugs) exists, `build_overview.py` filters the feed — and its portfolio rollups — to just those partners. The dashboard then shows exactly the curated set (currently 20: 16 kept + the 4 adds) without deleting any caches; it is **sync-proof** (a full rebuild can't resurrect hidden partners) and reversible (delete the file to show everyone). `audit_data.py` is allowlist-aware (scopes its partner checks to the roster). Removed from the demo view: MSP Corp, CMIT Solutions Stamford, Ion247, and ~19 others — re-add by editing the allowlist.
- **Durable transcript folder routing.** Populated `PARTNER_ALIASES` in `scripts/pull_graph_transcripts.py` (Amoskeag, Atlantic PC, Granite Networks, Proda, RedHelm, Secure Future Tech) so future Graph pulls route service-call transcripts into the canonical roster folder instead of creating fragmented short-named ones (the recurrence risk noted earlier).
- **New dashboard: "AI-Driven Operational Intelligence"** (renamed from PartnerPulse Executive Overview) — `index.html` rebuilt to the design signed off after the Review BD review cycle. The Executive Overview now carries, in addition to the existing portfolio KPIs:
  - an **Operational & experience signal** KPI row — **Active SIPs** (across N partners), **Open Actions** (with overdue + no-firm-date breakdown), and **Portfolio NPS** (promoters − detractors);
  - a **data-coverage window** under the title (snapshot date · service-review range + call count · CSAT/NPS feedback range + response count);
  - an **At-risk partners** table keeping the live columns (Partner · Risk · Call tone · Top driver) **plus two new columns — `SIP` and `Action Driver`** (open + overdue action counts); rows click through to Partner 360;
  - an **Action backlog** card (open/overdue actions per partner, with owner);
  - **Customer sentiment per partner** now showing **sample size (`n=`), a low-n flag, and a per-partner NPS chip**;
  - **Recurring themes** (concerns/positives) where each theme **expands on click to reveal the contributing partners, each linking through to their Partner 360**.
  - **Confidence honesty:** call tone is muted to **"No calls"** where none were analysed and flagged **"stale"** when the last call is >60 days old.
- **`scripts/build_overview.py` → `data/_overview.json`:** rolls the per-partner caches (`data/_index.json` + `data/<slug>.json`) into the feed the dashboard renders from — SIP totals, open/overdue/no-date action counts, real per-partner + portfolio NPS, CSAT split with sample size, honest call tone, themes, and the coverage window. Added as the **final sync-cycle step** (`server.py`).
- **Data-integrity audit — `scripts/audit_data.py`:** one-pass check across all partners for the failure modes that have bitten us — SIPs recorded but uncounted, missing/failed AI, empty CSAT (TeamGPS name mismatch), stale/absent last-call, transcript folders on disk that match no built partner, and feed/index integrity. Run after any sync to confirm health instead of checking partner-by-partner.
- **Backup of the pre-change dashboard:** `backups/index_pre-AIODI_2026-06-13.html` (byte-identical copy of the previous `index.html`) for rollback.
- **Incremental rebuild — sync now only re-does expensive work for *changed* partners.** Two caches added so a full rebuild (and every Sync) stops re-doing identical work:
  - **AI caching (`extract/ai.py`):** `analyze()` hashes the gpt-5.4 input (`build_context`) into `_input_hash`; when a partner's prior cache carries the same hash, the cached churn result is **reused verbatim — no LLM call**. This both **cuts sync time** and **stops the run-to-run score drift** (unchanged partners keep their scores). Wired through `build_all.py` and `build_real_partners.py`, which read the prior cache's `ai` block and pass it in. `--force-ai` re-runs regardless.
  - **Deck caching (`build_partner.py` + `build_real_partners.py`):** converted deck markdown is reused by the stable attachment id, so `markitdown` (slow, ~20–30 s/deck — a primary cause of the 30-min sync timeout) only runs on genuinely new decks.
  - Net: Halo/TeamGPS are still re-fetched each run (so changes are detected), but the two expensive steps (LLM + deck conversion) are skipped for unchanged partners.
- **At-risk table — "last call N days ago" sub-line** under each partner name (derived from each partner's most recent service-review call in `_overview.json`; shows "no calls" where none were analysed).

### Changed
- **`index.html` is now fully data-driven — there is NO embedded `const partners` array.** Both Executive Overview and Partner 360 render from `data/_overview.json` (the same fetch pattern `partner.html` already uses). This **eliminates the long-standing two-data-layer drift** (old gotcha 1 / SOP invariant 1): the feed is the single source of truth. **Partner 360 and `partner.html`/`partner.js` are functionally unchanged** (Partner 360 keeps Partner · Risk · Trend · CSAT + · Call tone · Renewal risk).
- **Sync cycle (`server.py` `SYNC_STEPS`)** is now `transcripts → registry → real-extras → reindex → overview`. The **`exec-rows` step was removed** (embedded-array refresh, now obsolete) and replaced by **`overview`** (`build_overview.py`). A new **`transcripts` step runs first** — `scripts/pull_graph_transcripts.py --write` pulls call transcripts from Graph into `Transcripts/` so a Sync now refreshes transcripts **alongside** HaloPSA + TeamGPS, then the registry build ingests them. (Caveats inherited from the pull script: skips folders that already hold manual `.docx`, QBRs 403, Teams retains transcript content only ~90 days.) `parse_activity` learns the new "pulling call transcripts" and "rebuilding operational-intelligence feed" phases.
- **`scripts/build_real_partners.py`** still builds the extra partner JSONs, but its `inject_exec` now **skips gracefully** when `index.html` has no embedded array (prints a notice instead of erroring) — the data it writes flows to the dashboard via `_index.json` + `_overview.json`.

### Fixed
- **Displayed sentiment trend reconciled against risk + tone.** gpt-5.4's `sentiment_trend` never emits "Declining" and sometimes tagged a high-risk/Negative account "Improving" (e.g. Proda at risk 72). `build_overview.py` (`_reconcile_trend`) now downgrades the shown trend so it can't read better than risk + tone warrant — Proda → **Declining**, and a High-risk "Improving" → Stable.
- **SIP counts now read the `CFSIPTicketMDE` custom field, not just a type-99 search.** `halo.count_sips` only counted ticket type 99 filed under the partner's own client record, so it reported **0** for SIPs that are a different ticket type or filed elsewhere — e.g. **APM IT** (ticket 761209 is **type 148**, status "Scheduled - Internal" = open) and **RedHelm** (tickets 540945/540941 filed under client **931**, not RedHelm's own id). It now also fetches every ticket id named in the partner's SIP custom field and counts it by status (any type/client). Also added **`resolved`** to the closed-status set (a Resolved SIP is concluded, not active). Result: APM IT → 1 open; RedHelm → 0 open / 2 closed. Affects all partners — run a rebuild.
- **CSAT was empty for several partners due to TeamGPS company-name mismatches.** The `teamgps_company` filter must match TeamGPS's company label exactly. Fixed in `extract/partners.py`: **Alliance InfoSystems → "Alliance InfoSystems LLC"** (69 reviews), **RealTime → "RealTime, LLC"** (20), **Stasmayer → "Stasmayer Inc."** (20). (PEI and Mission Technology return 0 even under their Halo name — they appear to be NPS-only; left as-is pending their exact TeamGPS label.)
- **Six existing partners' transcripts weren't ingesting** because the Graph pull created folders named by the meeting subject (short form) that don't normalize-match the roster name. Renamed `Transcripts/` folders to the roster names so they ingest: `Amoskeag → Amoskeag Network Consulting Group LLC`, `Atlantic PC → Atlantic PC Inc`, `Granite Networks → Granite Networks Inc`, `Proda Technology → Proda Technologies`, `RedHelm → RedHelm - 1Path`, `Secure Future Tech → Secure Future Tech Solutions`. (Fixed Amoskeag showing "no calls".) Note: the pull names folders by subject, so this can recur on future pulls — durable fix is a subject→roster mapping in `pull_graph_transcripts.py` (follow-up).
- **Service-call date now comes from the meeting NOTE, not the ticket's `dateoccurred`.** `extract/build_partner.py` recorded each `historical_calls` date as the ticket's `dateoccurred`, but recurring/bi-weekly service tickets keep an early `dateoccurred` while the actual call note is added later — e.g. Logically ticket **0755301**: `dateoccurred` 2026-05-27 but the call note is dated **2026-06-12**. This pinned "last call" to the ticket-creation date for every partner with recurring service tickets. Now uses the latest meeting-note datetime on the ticket — fixed in **both** build paths (`extract/build_partner.py` for registry partners and `scripts/build_real_partners.py` for the extras). (Verified: Logically last call 2026-05-27 → **2026-06-12**.) **Requires a partner rebuild to take effect for each partner** (a one-time full rebuild applies it across the book).
- **"Last call" now reflects transcripts, not just HaloPSA call-notes.** `build_overview.py` previously derived each partner's last-call date solely from `historical_calls` (Halo), so partners with transcripts but no Halo note (e.g. **Liongard** — 4 transcripts, 0 Halo notes) wrongly showed "no calls", and others showed a stale date. It now takes the **union of Halo call-note dates and ingested transcript dates** (parsed from the `YYYYMMDD` in each transcript title/filename); `calls.count` is the number of unique call dates across both. NOTE this only reflects *ingested* transcripts — a call whose transcript hasn't been pulled (e.g. partners whose folders hold manual `.docx`, which the pull skips by default) still won't appear until pulled.

### Deprecated
- **`scripts/refresh_exec_row.py`** is a no-op against the data-driven dashboard (it detects the absent embedded array and exits cleanly with guidance to run `build_overview.py`). Kept for reference / rollback to the backup.

### Removed
- **`review-bd.html`, `scripts/build_review_bd.py`, `data/_review_bd.json`** — the Review BD preview sandbox, superseded by the live dashboard (`build_review_bd.py` was promoted to `build_overview.py`).

---

## [1.0.0-beta.7] - 2026-06-13

### Added
- **Bulk transcript ingestion via app-only Graph — `scripts/pull_graph_transcripts.py`:** now that IT granted the DESManagement Teams application access policy (beta.6), this pulls partner service-call transcripts straight from Graph with **no attendee constraint** — the limitation that capped the M365-connector flow (Data-Extraction-SOP §1 Option C). It pages the DES calendar's `/events`, keeps partner service/review/business calls (drops interviews/onboarding/internal), dedupes to unique meeting series by join URL, resolves each by the organizer's **object id** (the `Oid` in the join URL — addressing by UPN returns a masking 404), and writes `Transcripts/{Partner}/<subject>-<YYYYMMDD>.vtt` with the standard NOTE header. Safety rails: dry-run by default (`--write` to save), per-date dedup keeping the longest of split recordings, skips existing files, defers folders that already hold manual `.docx` exports (`--include-docx-folders` to override), and retries throttling/connection resets. New SOP path documented as §1 Option D.
- **Thrice-weekly automated pull (operational, not in-repo):** a Windows Task Scheduler job ("PartnerPulse Transcript Pull") runs `pull_graph_transcripts.py --write` **Mon/Wed/Thu 9:00 AM** on Amit's machine, logging to `data/_transcript_pull.log` — chosen cadence keeps calls captured well inside the ~90-day content-retention window. Note it skips the 3 `.docx` folders by default (see Fixed).
- **First full pull (2026-06-13): 148 transcripts written across ~70 partner folders** (existing 28 + ~42 new partners incl. the previously-403'd Granite, F12, Amoskeag, Atlantic PC, Proda). Two real limits found and documented: **(1) Teams retains transcript *content* only ~90 days** — older occurrences still *list* but 404 on `/content`, so Jan–early-Mar 2026 calls were unrecoverable while Apr–Jun pulled cleanly (run the pull monthly); **(2) QBRs 403** — `ITBD x <Partner> : Quarterly Business Review` meetings are organized under a different identity than DES, so the Teams policy doesn't cover them. These are **input `.vtt` files only — the dashboard (embedded array, `_index.json`, exec rows) was deliberately left untouched**; the new partners are not onboarded yet.

### Fixed
- **`scripts/probe_graph_transcripts.py` address-by-object-id + acceptance test now green:** confirmed end-to-end transcript fetch works for DESManagement-organized meetings (17 transcripts, 24,691-char VTT on the Atlantic PC acceptance meeting).
- **MSP Corp folder de-fragmented + deferred-3 reconciled.** The bulk pull had created 5 separate sub-team folders (`MSP Corp (HD Team)/(SOC)/(Accounts Payable)/(CRDS Group)/(MBCCS Group)`) whose `.vtt` duplicated dates already held as manual `.docx` in the single `MSPCorp` folder (MSP Corp is one dashboard partner). Reconciled each pulled `.vtt` against the Word files by sub-team + date (parsing the freeform `.docx` filename dates): **24 of 25 were duplicates, 1 genuinely new** (Accounts Payable 2026-06-12, the latest call post-dating the last manual export) — moved into `MSPCorp`, the 24 dupes + 5 folders removed. Premier & Stasmayer (also `.docx`-deferred): every recoverable (≤90-day) date is already covered by existing files, so nothing to add. Net: `MSPCorp` whole again (74 files); no double-count introduced.
- **Known follow-up:** the scheduled pull (above) keeps skipping the 3 `.docx` folders by default, so new MSP Corp / Premier / Stasmayer calls won't be auto-captured until those partners are migrated off manual `.docx` exports — handle manually for now.

### Changed
- **`docs/IT-Request-Graph-Transcript-Access.md`, `CLAUDE.md`, `docs/Data-Extraction-SOP.md`** updated for the working app-only pull, the MDE/SBD-are-aliases finding, and the revised IT setup script (`$OrganizerAccounts` → DESManagement only).

> **Note (not done by these changes):** `index.html` carries pre-existing uncommitted edits from a prior session (2026-06-12 — re-scored churn text for Netgain/F12/RedHelm-1Path/Proda/Amoskeag, plus a LF→CRLF line-ending flip from a `git add .`). Left untouched here; flagged so it isn't mistaken for transcript-pull output.

---

## [1.0.0-beta.6] - 2026-06-12

### Added
- **✅ Graph transcript access WORKS — acceptance test passed (evening):** IT (Neeraj) ran `scripts/setup_graph_transcript_access.ps1`; the Teams application access policy grant to DESManagement succeeded and `scripts/probe_graph_transcripts.py` went green end-to-end (meeting from join URL → 17 transcripts → 24,691-char VTT fetched) — the app identity now reads transcripts **without the attendee constraint** that limited the M365-connector flow. The script halted granting MDEManagement (`"User does not exist"` — no Teams identity behind that mailbox), but coverage analysis shows all partner service calls are created under the **DESManagement Teams identity** (its object id appears in every join URL, even for events whose organizer email says MDE/SBD) — Amit then confirmed MDE/SBDManagement are **SMTP aliases of the DESManagement mailbox**, not separate users, so the one successful grant is full coverage. Personal-account organizers (sbhatia, tanya.khurana — internal interviews, not partner calls) remain outside the policy by design. The setup script was revised accordingly (`$OrganizerAccounts` → DESManagement only, alias warning added, header revision note) for Neeraj's re-run, which only needs to complete Step 3 (Exchange calendar scoping — still pending, app reads calendars tenant-wide until then) + verification; secret rotation also still recommended. Full retest log in `docs/IT-Request-Graph-Transcript-Access.md`.
- **Graph transcript app registration tested + IT setup script:** IT provisioned the app registration from `docs/IT-Request-Graph-Transcript-Access.md` (client id `c7bc5538-…2983`, app display name "DESManagement@itbd.net"). Connection test 2026-06-12: token + calendar reads on DESManagement work; transcript reads still 403 (Teams application access policy missing), `OnlineMeetings.Read.All` not granted, and Calendars.Read is currently tenant-wide (Exchange policy missing — verified by reading an out-of-scope mailbox). Added `scripts/setup_graph_transcript_access.ps1` — a commented, idempotent one-shot script for IT that adds the missing permission + admin consent, creates/grants the Teams application access policy to the 3 organizer accounts, scopes calendar access via Exchange **RBAC for Applications** (mail-enabled security group → management scope → `Application Calendars.Read` role, then removes the now-redundant tenant-wide Calendars.Read consent), and verifies with `Test-ServicePrincipalAuthorization`. Cmdlet syntax web-verified against Microsoft Learn 2026-06-12 — notably `New-ApplicationAccessPolicy` (the older Exchange scoping) is now flagged "don't create new" by Microsoft, hence the RBAC approach. Credentials live in `.env` (gitignored); `GRAPH_TENANT_ID`/`GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET` documented in `.env.example`. Outcome recorded in the IT-request doc.
- **Milner 2026-06-12 service-call transcript** pulled via the M365 connector (Graph meeting-transcript flow, Data-Extraction-SOP §1 Option C) and ingested: `Transcripts/Milner/Milner _ ITBD Service Call-20260612.vtt` (35m 18s, 8th `.vtt` for Milner, 18 transcripts total). Milner rebuilt end-to-end (`build_all --only Milner` → `--reindex` → exec-row refresh). The first rebuild scored **61 (High)**; same-day re-analyses (full sync, then the duplicate-transcript fix below) re-scored it to **27 (Low)** with reviewVolume 109→114 — gpt-5.4 re-scores shift run to run, and Halo shows RAG Amber / cancel-risk Low, consistent with the lower band. Final state: risk **27 (Low)**, 18 transcripts, both data layers in sync.
- **`scripts/refresh_exec_row.py <slug>|--all`:** re-renders partners' embedded exec-overview rows in `index.html` from their `data/{slug}.json` caches. Registry partners' rows live in the *static* part of the array (outside the BEGIN/END markers), so `build_real_partners.py`'s injector can't update them and would append a duplicate — this script replaces each row by slug wherever it sits. Completes the scripted single-partner refresh path (`build_all --only <Name>` → `build_all --reindex` → `refresh_exec_row.py <slug>`).
- **Sync cycle step 3 of 4 — `exec-rows`:** the manual sync cycle now runs `refresh_exec_row.py --all` between the extras injection and the reindex. **Fixes a standing two-data-layer drift:** a full sync rebuilt every registry partner's `data/*.json` but never touched their static exec-overview rows in `index.html`, so the Executive Overview kept showing stale risk scores (observed live: Milner 61/High embedded vs 31/Low in the rebuilt cache after the 2026-06-12 sync re-analyzed it with the new transcript).
- **"Last sync" timestamp next to the Sync Data button** (both pages): `refresh.js` reads `portfolio.generated_at` from `data/_index.json` (no-cache fetch) and renders e.g. "Last sync: Jun 12, 1:23 PM" — survives server restarts and reflects CLI builds too; hidden silently on static hosting without `data/`.
- **`refresh_exec_row.py --remove <slug>`:** scripted offboarding — deletes a partner's embedded exec-overview row (used for the CW Now correction below).
- **`scripts/probe_graph_transcripts.py`:** the Graph app-registration acceptance test (token → resolve meeting from join URL → transcript fetch) promoted from a throwaway probe into a proper script — credentials now read from the `GRAPH_*` vars in `.env` (the throwaway had the client secret hardcoded and sat in `data/`, where `.py` files weren't gitignored). Referenced from the IT-request doc as the post-remediation verification step.

### Fixed
- **Graph transcript probe addressed organizers by UPN and masked the real error:** retest of the app registration (2026-06-12, after IT granted `OnlineMeetings.Read.All` — token now carries all four app roles) showed `scripts/probe_graph_transcripts.py` reporting an empty `404 UnknownError`, while the actual failure is `403 "No application access policy found for this app"` (Teams application access policy, item 3 of the IT request, still missing; Exchange calendar scoping, item 4, also still tenant-wide). Graph's app-only `/users/{id}/onlineMeetings` endpoints must address the organizer by **object id**, not UPN. The probe now parses the organizer's object id from the join URL's `Oid` context parameter (no extra permission needed), prints the token's app roles, and exits non-zero on failure; its comment also mis-attributed the acceptance meeting's organizer (Atlantic PC 2026-05-22 is organized by DESManagement, not MDEManagement — the Oid in the join URL is DESManagement's). Retest outcome recorded in `docs/IT-Request-Graph-Transcript-Access.md`.
- **Service Decks tab empty for all 28 extras-path partners:** `scripts/build_real_partners.py` hardcoded `"decks": []` — a leftover shortcut from when it onboarded only 8 partners — so every partner built by it (28 of the 38) had an empty Service Decks tab while the 10 registry partners showed theirs. The script now runs the same deck path as `extract/build_partner.py` (PDF/PPTX attachments on review tickets → MarkItDown → `decks[]` + `sources.decks`); verified on F12 (5 May monthly-review PPTXs converted, Service Decks tab populated). Like transcripts, deck conversion degrades to a warning when `markitdown` is missing. All extras rebuilt with the new path + reindex so the decks show everywhere.
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
