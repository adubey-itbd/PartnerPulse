# Data Schema & Data-Flow — PartnerPulse / Operational Intelligence

**The authoritative map of where every piece of data comes from, how it is
processed, and where it is stored — end to end.** Read this with
`docs/architecture.md` (system design), `docs/Firebase-Deploy-SOP.md` (the hosted
deployment) and `docs/Cloud-Pipeline-SOP.md` (the nightly job).

Last reworked **2026-06-16**, when the pipeline moved to a scheduled Cloud Run
Job and the dashboard moved to Firebase Hosting + Cloud Firestore. Updated
**2026-06-18**: the AI engine is now **Grok `grok-4-1-fast-reasoning`** via an
Azure AI Foundry OpenAI-compatible endpoint (`AI_BASE_URL`/`AI_API_KEY`/`AI_MODEL`;
cloud secret `ai-api-key`), replacing Azure-OpenAI gpt-5.4.

---

## 0. One-screen flow

```
 SOURCES (upstream truth)        PIPELINE (nightly, Cloud Run Job)         STORES                         CONSUMERS
 ─────────────────────────       ─────────────────────────────────        ──────────────────────────     ─────────────────
 HaloPSA REST  ───────────┐      scripts/cloud_sync.py:                    GCS state bucket               browser (Firebase
 TeamGPS Open API ────────┤        1. pull state ← GCS                     gs://…-pipeline-state          Hosting, @itbd.net
 MS Graph (Teams) ────────┼────▶   2. pull_graph_transcripts  ──▶          (data/ + Transcripts/,           email/pw sign-in)
 local decks/.docx ───────┤        3. extract.build_all (Grok)             incl. Grok AI cache)               │  reads via
 Grok via Azure Foundry ──┘        4. build_real_partners                       ▲      │                       │  auth.js
                                   5. build_all --reindex                       │ persist                     ▼
                                   6. build_overview  ──▶ data/*.json  ─────────┘      └──▶ Cloud Firestore ──▶ Exec Overview
                                   7. upload_firebase_data  ─────────────────────────────▶ (sharded docs)      + Partner 360
                                   8. push state → GCS
```

Three different "stores" hold the same data at three stages:

| Store | Role | Lifetime / source of truth |
|---|---|---|
| **External APIs** (Halo / TeamGPS / Graph) | Upstream operational systems | The real source of truth for the raw facts; queried read-only. |
| **`data/*.json` + GCS state bucket** | Pipeline working cache (incl. the Grok AI cache) | Intermediate. The bucket is the durable copy between nightly runs; local `data/` is just a dev convenience. |
| **Cloud Firestore** | What the dashboard actually reads in production | **Source of truth for *serving*.** A point-in-time snapshot republished every night. |

Local dev still reads `data/*.json` directly (no Firestore, no auth) — `auth.js`
auto-detects localhost. Production reads Firestore only.

---

## 1. Data sources (where it comes from)

| Source | Module | Auth (secret) | What it provides |
|---|---|---|---|
| **HaloPSA** REST (`itbd.halopsa.com/api`) | `extract/halo.py` | OAuth2 client-credentials (`HALO_CLIENT_ID`, `HALO_CLIENT_SECRET`) | Client metadata + custom RAG/risk fields (`CFMDERAG`, `CFCancelationRisk`, `CFHealthReason`, `CFNextStep`), service-review tickets & meeting-note Actions, deck/PDF attachments, SIP (type-99) ticket counts. |
| **TeamGPS Open API** (`api.team-gps.net/open-api/v1`) | `extract/teamgps.py` | static `TEAMGPS_API_KEY` | CSAT responses (per company) and NPS responses (per email domain). |
| **Microsoft Graph** (Teams meeting transcripts) | `scripts/pull_graph_transcripts.py` | app-only OAuth (`GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`) | `.vtt` call transcripts → `Transcripts/{Partner}/`. Teams keeps content ~90 days. |
| **Local documents** | `extract/transcripts.py` (markitdown) | none | `.docx` Teams exports + deck `.pptx`/`.pdf` → Markdown text. |
| **Grok `grok-4-1-fast-reasoning`** via Azure AI Foundry (OpenAI-compatible endpoint, `https://daku.services.ai.azure.com/openai/v1/`) | `extract/ai.py` | `AI_BASE_URL` + `AI_API_KEY` (+ `AI_MODEL`); cloud secret `ai-api-key` | The churn analysis: risk score/band, confidence, sentiment, drivers, remediation, extracted action items. |

All secrets live in **Secret Manager** in the cloud (loaded by
`scripts/seed_secrets.py`) and in `.env` / `extract/config.py` fallbacks for local
runs. **No external/web data** is used — churn risk is inferred entirely from
internal signals (see `architecture.md` §7).

---

## 2. Pipeline (how it's processed)

The nightly **Cloud Run Job** runs `scripts/cloud_sync.py`, which executes the
same cycle the local "Sync Data" button used to (that button was removed
2026-06-16):

1. **Pull state** from `gs://…-pipeline-state` → `data/` + `Transcripts/` (so the Grok AI cache and transcript history are present).
2. `pull_graph_transcripts.py --write` — fresh `.vtt` from Graph.
3. `extract.build_all` — per partner: Halo + TeamGPS fetch, doc/transcript parse, **Grok** churn analysis → `data/{slug}.json`. **Incremental**: the AI is cached by an input hash and skipped when inputs are unchanged (no score drift); decks cached by attachment id.
4. `scripts/build_real_partners.py` — the DES/MDE roster beyond the registry.
5. `extract.build_all --reindex` — `data/_index.json` (slim rows + portfolio aggregates).
6. `scripts/build_overview.py` — `data/_overview.json`, the dashboard feed (honours the `_demo_roster.json` allowlist).
7. `scripts/upload_firebase_data.py` — publish the sharded Firestore tree.
8. **Push state** back to GCS.

Steps 2–6 are continue-on-failure; 1/7/8 are hard (fail the run). See
`docs/Cloud-Pipeline-SOP.md` for the infra.

---

## 3. Local cache schema (`data/`, gitignored)

> Generated artifacts only — never hand-edited, never committed. Mirrored into the
> GCS state bucket between runs.

- **`data/{slug}.json`** — the full per-partner payload. Top-level keys: `meta`,
  `client`, `csat_stats`, `csat_comments`, `nps_stats`, `nps_comments`,
  `historical_calls`, `sips` (one object per SIP ticket — `{ticket_id, subject, status,
  status_label, status_class, started, latest, updates[], summary, latest_status}` — from
  `halo.analyze_sips`; the `updates` are the SIP ticket's progress write-ups incl. PRIVATE
  notes, `summary`/`latest_status` are the AI journey summary (`ai.summarize_sips`, active SIPs
  only). Feeds the AI context + the Partner-360 SIP Progress card),
  `action_items` (always `[]`; real items live in `ai.action_items`),
  `decks`, `transcripts`, `ai`. (Field-level detail in `architecture.md` §3.)
- **`data/_index.json`** — `{ partners: [slim row…], portfolio: {…aggregates…} }`,
  written by `build_all`. `portfolio.generated_at` is the freshness stamp.
- **`data/_overview.json`** — the **dashboard feed** (see §4), built by
  `build_overview.py` from `_index.json` + every `{slug}.json`.
- **`data/_demo_roster.json`** — allowlist of slugs; filters the feed + rollups to a
  curated subset (currently the full DES/MDE roster). Sync-proof, reversible.
- **`data/decks/`** — downloaded deck PDFs/PPTX + converted `.md` (cached by attachment id).

---

## 4. The dashboard feed (`data/_overview.json` → Firestore)

This is the shape the Exec Overview renders and the shape published to Firestore.

```jsonc
{
  "generated_at": "2026-06-16T08:34:31",     // freshness stamp
  "as_of": "2026-06-13",
  "excludedCount", "excludedSlugs",          // partners hidden by the demo-roster allowlist (gotcha 8)
  "inactiveCount", "inactiveSlugs",          // partners dropped because Halo client.inactive is true (auto-excluded from feed + rollups)
  "coverage": { "asOf", "callsStart", "callsEnd", "callsCount",
                "feedbackStart", "feedbackEnd", "feedbackCount" },
  "portfolio": { "tracked", "avgRisk", "highRisk", "activeSIPs",
                 "partnersWithSIP", "openActions", "overdueActions",
                 "openNoDate", "renewalsAtRisk", "portfolioNPS",
                 "csatCoverage", "npsResponses" },
  "partners": [ {
      "name", "slug",                         // name = live Halo client.name (source of truth); slug ≠ slugify(name) — use it verbatim
      "churnRisk", "riskBand",                // riskBand derived from score (_tier), not LLM
      "accountManager", "sentimentTrend",     // sentimentTrend reconciled (_reconcile_trend)
      "topDriver", "themes",                  // themes ← Grok drivers[]
      "csat", "nps", "sip", "actions", "calls",
      "callTone", "toneConfident"             // toneConfident=false ⇒ UI shows "No calls"
  } ]
}
```

---

## 4b. The CSAT Reconciliation feed (`data/_csat_recon.json` → Firestore)

Built by `scripts/build_csat_recon.py` AFTER `build_overview.py` (it reads the
overview's partner set, already demo-allowlist filtered). Powers the CSAT
Reconciliation view in `index.html`. **Source→field provenance:**

| Field | Source |
|---|---|
| CSAT **sent** (per month) | HaloPSA tickets, `tickettype_id ∈ {36,163,164}` ("DES CSAT Monthly"), one ticket = one sent. Month parsed from the ticket summary ("…For The Month of May"); year from `dateoccurred` (`extract/halo.fetch_csat_tickets`). The summary month is authoritative; a month-less ticket (a batch is raised bare and stamped with the month later) counts only when raised in the **current** month — so a settled month matches Halo's "Month of …" report and isn't inflated by unstamped stragglers (`_ticket_month`). |
| CSAT **received** (per month) | TeamGPS responses (the `data/{slug}.json` `csat_comments`) where **`is_responded`** is true — the `/csat` endpoint also returns *sent-but-unanswered* surveys (empty rating, null date), which must NOT count. Joined to a sent ticket by `ticket_id` and attributed to that sent ticket's month (distinct answered tickets, so received ≤ sent). |
| CSAT **% positive** (per month) | Of the matched responses, `positive ÷ rated` (rated = Positive+Neutral+Negative ratings on `csat_comments`). The satisfaction score, distinct from the response rate. |
| Account Manager / Regional Manager | Halo client `accountmanagertech_name` / `regmanagertech_name`. |
| Site | Halo client custom field `CFAccountSite` (NDA/CDG/DL/PH; the `-1` sentinel and stray numeric ids → "—"). |
| Product (MDE) | Halo client custom field `CFProductMDE` (Self-Managed / Co-Managed; same sentinel/numeric guard → "—"). |
| Partner roster | `data/_overview.json` partners (= Halo `CFMDERAG ≥ 1`, demo-allowlist applied). |

```jsonc
{
  "generated_at", "as_of",
  "ticketTypes": [36, 163, 164],
  "period": { "start": "2026-01", "end": "2026-06",
              "months": [ { "key": "2026-01", "label": "Jan 2026" }, … ] },
  "totals": { "partners", "partnersWithSent", "sent", "received",
              "responseRate",          // received ÷ sent, %
              "positive", "rated", "csatPct",   // CSAT satisfaction: positive ÷ rated, %
              "respondedNoMatch" },    // in-window responses whose ticket_id matches no in-window sent survey
  "byMonth": [ { "key", "label", "sent", "received", "pos", "rated",
                 "rate",   // response rate %
                 "csat" } ],           // CSAT % positive
  "rows": [ {
      "partner", "slug", "accountManager", "regionalManager", "site", "product",
      "months": { "2026-01": { "sent", "received", "pos", "rated" }, … },
      "total":  { "sent", "received", "pos", "rated" }
  } ]
}
```

Window = Jan of the current year → current month (`PARTNERPULSE_ASOF=YYYY-MM-DD`
override, same as `build_overview.py`). The view re-groups `rows` by
Partner/AM/RM/Site and re-buckets months→quarters client-side. Read via
`window.PP_AUTH.loadCsatRecon()` (Firestore `meta/csatRecon` in prod,
`data/_csat_recon.json` on localhost).

---

## 5. Cloud Firestore (where it's stored for serving)

Published by `scripts/upload_firebase_data.py`. **Sharded** so no single doc
approaches Firestore's 1 MiB cap and the UI can lazy-read pieces. Each detail doc
carries `_i` (its source-list index) so order is restored via `orderBy('_i')`.
Doc ids are zero-padded indices, making the upload idempotent (it deletes
trailing docs and removes partners no longer in the feed).

```
meta/overview                     ← { generated_at, as_of, coverage, portfolio }     (from _overview.json)
meta/csatRecon                    ← the whole _csat_recon.json feed (single doc)     → CSAT Reconciliation view
partners/{slug}                   ← the per-partner SUMMARY object (the feed's partners[] entry) → Exec Overview
partners/{slug}/detail/profile    ← { meta, client, ai, csat_stats, nps_stats }      (from {slug}.json)
partners/{slug}/transcripts/{i}   ← one doc per transcript        (blob.transcripts)
partners/{slug}/decks/{i}         ← one doc per converted deck     (blob.decks)
partners/{slug}/calls/{i}         ← one doc per service-review     (blob.historical_calls)
partners/{slug}/sip/{i}           ← one doc per SIP ticket (status + notes) (blob.sips)
partners/{slug}/csat/{i}          ← one doc per CSAT comment       (blob.csat_comments)
partners/{slug}/nps/{i}           ← one doc per NPS response       (blob.nps_comments)
partners/{slug}/actions/{i}       ← one doc per action item        (blob.action_items)
feedback/{auto-id}                 ← one doc per public feedback submission (from feedback.html)
login_audit/{auto-id}              ← one doc per sign-in session            (from auth.js recordLogin)
login_audit_summary/{uid}          ← per-user rollup: count + last_login    (from auth.js recordLogin)
```

The `feedback` collection is **not** part of the pipeline feed — it is written
directly by the browser from the public `feedback.html` form (auto-id docs).
Shape: `{ message, category, page, user_agent, submitted_at (server time),
name?, email?, company?, rating? (1–5) }`. Reviewed in the Firebase console (no
in-app reader).

The `login_audit` / `login_audit_summary` collections are likewise **not** part
of the pipeline feed — they are written directly by the browser (`auth.js`
`recordLogin`, once per browser-tab session). `login_audit/{auto-id}` shape:
`{ email, uid, ts (server time), page, user_agent }` (immutable). `login_audit_summary/{uid}`
shape: `{ email, count (FieldValue.increment), last_login (server time) }`.
Reviewed in the Firebase console (no in-app reader).

**Access (`firestore.rules`):** read allowed only for a **verified, allowlisted**
account (`email_verified == true` + `email in [...]` — a **named 6-person allowlist**,
not the whole `@itbd.net` domain, since 2026-06-22; mirrored in `auth.js` `ALLOWED_EMAILS`);
**dashboard client writes denied**.
The pipeline writes via the Admin SDK / attached service account, which bypasses
rules. **Exception — the public `feedback` collection:** unauthenticated **CREATE
only**, validated by `isValidFeedback()` (required `message` ≤5000 chars,
`submitted_at == request.time`, optional fields type/size-capped, key set locked
via `hasOnly`); no client reads/updates/deletes. **Exception — sign-in audit
(`login_audit` / `login_audit_summary`):** create/append-only by a **verified
`@itbd.net`** user writing **only their own** `uid`/`email` (`isItbd()` + identity
match + `ts`/`last_login == request.time` + `count` monotonic `== prev + 1` on
update + `hasOnly` key locks); no client reads/deletes. `firestore.indexes.json` is empty — the overview fetches all summary docs
and filters client-side (fine to a few hundred partners; past that, switch
`loadOverview()` to a server-side `orderBy('churnRisk').limit()` query + composite
index).

---

## 6. GCS state bucket (pipeline persistence)

`gs://operational-intelligence-ebe23-pipeline-state` holds `data/` and
`Transcripts/` between nightly runs. **Why it exists:** the build is incremental
(Grok cached by input hash → stable scores) and Teams drops transcript content
after ~90 days; persisting state keeps the cache warm and the transcript history
intact. The Cloud Run Job's service account has `roles/storage.objectAdmin` on it.
Not web-exposed.

---

## 7. Frontend consumption (`auth.js`)

`auth.js` is the single data-access layer for both pages; it abstracts dev vs prod:

| | LOCAL DEV (localhost / unconfigured / no SDK) | PRODUCTION (Firebase Hosting) |
|---|---|---|
| Auth | none | email/password, verified `@itbd.net` |
| `loadOverview()` | `fetch data/_overview.json` | `meta/overview` + all `partners/*` summary docs, reassembled into the feed shape |
| `loadPartner(slug)` | `fetch data/{slug}.json` | `partners/{slug}` + `detail/profile` + every subcollection, reassembled into the blob shape |
| `lastSyncStamp()` | `data/_index.json` `portfolio.generated_at` | `meta/overview.generated_at` |

So `index.html` / `partner.js` are storage-agnostic — they call `PP_AUTH.*` and
get the same shapes regardless of where the data lives.

---

## 8. Field provenance (quick reference)

| Dashboard field | Origin |
|---|---|
| `churnRisk`, `riskBand`, `confidence`, `topDriver`, `themes`, `sentimentTrend` (raw), `remediation`, `ai.action_items`, `ai._model` (= `grok-4-1-fast-reasoning`) | **Grok `grok-4-1-fast-reasoning`** via Azure AI Foundry (`extract/ai.py`) over the compiled context |
| `riskBand` (shown), `sentimentTrend` (shown) | **Derived deterministically** in `build_overview.py` (`_tier`, `_reconcile_trend`) — not the LLM's free-form values |
| `csat`, `csatCoverage`, CSAT comments/stats | **TeamGPS** CSAT |
| `nps`, `portfolioNPS`, `npsResponses`, NPS comments/stats | **TeamGPS** NPS |
| `sip`, `activeSIPs`, `partnersWithSIP`, `client.sip_*` | **HaloPSA** type-99 tickets (`halo.analyze_sips` → counts) |
| `sips` (Partner-360 SIP Progress card + AI context) | **HaloPSA** SIP tickets grouped w/ status + progress notes incl. PRIVATE notes (`halo.analyze_sips`; the Actions LIST hides private notes, so they're fetched per-action by id). Per-SIP `summary`/`latest_status` = **Grok** (`ai.summarize_sips`). |
| `actions`, `openActions`, `overdueActions`, `openNoDate` | **HaloPSA** meeting-note Actions + AI-extracted items |
| `accountManager`, `client.rag/cancel_risk/health_reason/next_step` | **HaloPSA** client metadata + custom RAG fields |
| `client.inactive` | **HaloPSA** client `inactive` flag. When true, `build_overview.py` drops the partner from the feed + rollups (→ `inactiveSlugs`); `upload_firebase_data.py` then prunes its Firestore docs. Sync-proof & reversible. |
| `calls`, `callTone`, `toneConfident`, `historical_calls`, `coverage.calls*` | **HaloPSA** meeting notes + **Graph** transcript dates |
| `transcripts` | **MS Graph** `.vtt` + local `.docx` (markitdown) |
| `decks` | **HaloPSA** attachments → markitdown |
| `coverage.feedback*` | **TeamGPS** CSAT/NPS date span |

---

## 9. Going forward (operating model)

- **Refresh cadence:** automatic, nightly **21:00 America/New_York** (Cloud
  Scheduler → Cloud Run Job). No manual button; no local machine in the loop.
- **Source of truth for serving** is **Firestore**; it is overwritten each night
  from a fresh build. To force a refresh off-cycle:
  `gcloud run jobs execute partnerpulse-nightly --region=us-central1`.
- **`firebase deploy` ships UI/rules only** — data changes flow through the Job +
  `upload_firebase_data.py`, not a redeploy.
- **Adding/removing a partner** still happens in code (`extract/partners.py` or
  `scripts/build_real_partners.py` NEW) + the allowlist — the nightly job then
  propagates it to Firestore. Never hand-edit `data/` or Firestore docs.
- **Secrets** are in Secret Manager (rotation still owed — see
  `Firebase-Deploy-SOP.md` §0 and `Cloud-Pipeline-SOP.md` "Notes").
