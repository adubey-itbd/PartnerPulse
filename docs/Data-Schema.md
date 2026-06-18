# Data Schema & Data-Flow — PartnerPulse / Operational Intelligence

**The authoritative map of where every piece of data comes from, how it is
processed, and where it is stored — end to end.** Read this with
`docs/architecture.md` (system design), `docs/Firebase-Deploy-SOP.md` (the hosted
deployment) and `docs/Cloud-Pipeline-SOP.md` (the now-retired nightly job).

Last reworked **2026-06-16**, when the pipeline moved to a scheduled Cloud Run
Job and the dashboard moved to Firebase Hosting + Cloud Firestore.

**Addendum 2026-06-18:** the AI churn layer was swapped from Azure Foundry
gpt-5.4 to **Claude via the Claude Agent SDK**, billed to the operator's **Claude
subscription** (local OAuth login, NO API key). Because subscription auth is for
individual interactive use, the **build now runs MANUALLY on a laptop** and the
nightly Cloud Run Job is **retired** (to be disabled by an operator) — the cloud
footprint is **Hosting + Firestore serving only**. References below are updated in
place.

---

## 0. One-screen flow

```
 SOURCES (upstream truth)        PIPELINE (MANUAL, run on a laptop)        STORES                         CONSUMERS
 ─────────────────────────       ─────────────────────────────────        ──────────────────────────     ─────────────────
 HaloPSA REST  ───────────┐      local build cycle:                       local data/ + Transcripts/    browser (Firebase
 TeamGPS Open API ────────┤        (pull_graph_transcripts) ──▶           (incl. the Claude AI cache)     Hosting, @itbd.net
 MS Graph (Teams) ────────┼────▶   1. extract.build_all (Claude SDK)            │                          email/pw sign-in)
 local decks/.docx ───────┤        2. build_real_partners                       │                            │  reads via
 Claude Agent SDK ────────┘        3. build_all --reindex                        │                            │  auth.js
 (subscription, no API key)        4. build_overview ──▶ data/*.json  ───────────┘                            ▼
                                   5. upload_firebase_data ─────────────────────────────▶ Cloud Firestore ──▶ Exec Overview
                                                                                          (sharded docs)       + Partner 360
```

Three different "stores" hold the same data at three stages:

| Store | Role | Lifetime / source of truth |
|---|---|---|
| **External APIs** (Halo / TeamGPS / Graph) | Upstream operational systems | The real source of truth for the raw facts; queried read-only. |
| **`data/*.json` (local)** | Pipeline working cache (incl. the Claude AI cache) | Intermediate. Built on the operator's laptop; persisted there between manual runs so the AI cache + transcript history stay warm. |
| **Cloud Firestore** | What the dashboard actually reads in production | **Source of truth for *serving*.** A point-in-time snapshot, republished manually after each local build via `upload_firebase_data.py`. |

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
| **Claude — `claude-sonnet-4-6`** (via the Claude Agent SDK) | `extract/ai.py` | Claude **subscription** OAuth login (`claude setup-token` / `claude login`; `claude` CLI on PATH) — **NO API key** (ai.py strips `ANTHROPIC_API_KEY`) | The churn analysis: risk score/band, confidence, sentiment, drivers, remediation, extracted action items. Model overridable via `CLAUDE_MODEL` (`extract/config.py`). |

Halo/TeamGPS/Graph secrets live in `.env` / `extract/config.py` fallbacks for
local runs (and in **Secret Manager** for any cloud use — but **the Claude AI step
has no cloud secret**: subscription billing uses the local OAuth login, and the
former `azure-openai-key` Secret Manager entry was removed). **No external/web
data** is used — churn risk is inferred entirely from internal signals (see
`architecture.md` §7).

---

## 2. Pipeline (how it's processed)

The build is run **MANUALLY on a laptop** (changed 2026-06-18 with the move to
Claude subscription billing — the Agent SDK cannot legitimately bill a personal
subscription from unattended cloud automation, so the nightly Cloud Run Job is
retired). The operator runs:

1. (optional) `pull_graph_transcripts.py --write` — fresh `.vtt` from Graph.
2. `extract.build_all` — per partner: Halo + TeamGPS fetch, doc/transcript parse, **Claude** (`claude-sonnet-4-6`, via the Agent SDK on the subscription) churn analysis → `data/{slug}.json`. **Incremental**: the AI is cached by an input hash and skipped when inputs are unchanged (no score drift); decks cached by attachment id. (`extract.build_all` also runs `build_real_partners` + `--reindex` internally; the explicit steps below mirror the documented cycle.)
3. `scripts/build_real_partners.py` — the DES/MDE roster beyond the registry.
4. `extract.build_all --reindex` — `data/_index.json` (slim rows + portfolio aggregates).
5. `scripts/build_overview.py` — `data/_overview.json`, the dashboard feed (honours the `_demo_roster.json` allowlist).
6. `scripts/upload_firebase_data.py` — publish the sharded Firestore tree.

The condensed manual cycle is: `python -m extract.build_all` → `python
scripts/build_overview.py` → `python scripts/upload_firebase_data.py`. Switching
the AI model invalidates the per-partner cache (it keys on `_model`), so the first
post-swap build re-scores every partner cleanly. The cloud footprint is now
**Hosting + Firestore serving only**; `docs/Cloud-Pipeline-SOP.md` covers the
(retired) Job infra.

---

## 3. Local cache schema (`data/`, gitignored)

> Generated artifacts only — never hand-edited, never committed. Persisted on the
> operator's laptop between manual runs (so the Claude AI cache + transcript
> history stay warm). The `ai` block records `_model` (now `claude-sonnet-4-6`),
> `_input_hash`, and `_schema_version` (2) for incremental caching.

- **`data/{slug}.json`** — the full per-partner payload. Top-level keys: `meta`,
  `client`, `csat_stats`, `csat_comments`, `nps_stats`, `nps_comments`,
  `historical_calls`, `action_items` (always `[]`; real items live in `ai.action_items`),
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
  "coverage": { "asOf", "callsStart", "callsEnd", "callsCount",
                "feedbackStart", "feedbackEnd", "feedbackCount" },
  "portfolio": { "tracked", "avgRisk", "highRisk", "activeSIPs",
                 "partnersWithSIP", "openActions", "overdueActions",
                 "openNoDate", "renewalsAtRisk", "portfolioNPS",
                 "csatCoverage", "npsResponses" },
  "partners": [ {
      "name", "slug",                         // slug ≠ slugify(name) — use it verbatim
      "churnRisk", "riskBand",                // riskBand derived from score (_tier), not LLM
      "accountManager", "sentimentTrend",     // sentimentTrend reconciled (_reconcile_trend)
      "topDriver", "themes",                  // themes ← Claude drivers[]
      "csat", "nps", "sip", "actions", "calls",
      "callTone", "toneConfident"             // toneConfident=false ⇒ UI shows "No calls"
  } ]
}
```

---

## 5. Cloud Firestore (where it's stored for serving)

Published by `scripts/upload_firebase_data.py`. **Sharded** so no single doc
approaches Firestore's 1 MiB cap and the UI can lazy-read pieces. Each detail doc
carries `_i` (its source-list index) so order is restored via `orderBy('_i')`.
Doc ids are zero-padded indices, making the upload idempotent (it deletes
trailing docs and removes partners no longer in the feed).

```
meta/overview                     ← { generated_at, as_of, coverage, portfolio }     (from _overview.json)
partners/{slug}                   ← the per-partner SUMMARY object (the feed's partners[] entry) → Exec Overview
partners/{slug}/detail/profile    ← { meta, client, ai, csat_stats, nps_stats }      (from {slug}.json)
partners/{slug}/transcripts/{i}   ← one doc per transcript        (blob.transcripts)
partners/{slug}/decks/{i}         ← one doc per converted deck     (blob.decks)
partners/{slug}/calls/{i}         ← one doc per service-review     (blob.historical_calls)
partners/{slug}/csat/{i}          ← one doc per CSAT comment       (blob.csat_comments)
partners/{slug}/nps/{i}           ← one doc per NPS response       (blob.nps_comments)
partners/{slug}/actions/{i}       ← one doc per action item        (blob.action_items)
feedback/{auto-id}                 ← one doc per public feedback submission (from feedback.html)
```

The `feedback` collection is **not** part of the pipeline feed — it is written
directly by the browser from the public `feedback.html` form (auto-id docs).
Shape: `{ message, category, page, user_agent, submitted_at (server time),
name?, email?, company?, rating? (1–5) }`. Reviewed in the Firebase console (no
in-app reader).

**Access (`firestore.rules`):** read allowed only for a **verified `@itbd.net`**
account (`email_verified == true` + domain regex); **dashboard client writes denied**.
The pipeline writes via the Admin SDK / attached service account, which bypasses
rules. **Exception — the public `feedback` collection:** unauthenticated **CREATE
only**, validated by `isValidFeedback()` (required `message` ≤5000 chars,
`submitted_at == request.time`, optional fields type/size-capped, key set locked
via `hasOnly`); no client reads/updates/deletes. `firestore.indexes.json` is empty — the overview fetches all summary docs
and filters client-side (fine to a few hundred partners; past that, switch
`loadOverview()` to a server-side `orderBy('churnRisk').limit()` query + composite
index).

---

## 6. Pipeline persistence (local `data/` + Transcripts)

**Changed 2026-06-18:** with the build now run manually on a laptop, pipeline
state lives in the operator's local `data/` + `Transcripts/`. **Why it matters:**
the build is incremental (Claude analysis cached by input hash → stable scores)
and Teams drops transcript content after ~90 days, so keeping the local cache warm
and the transcript history intact avoids re-scoring drift and lost calls — back up
the laptop's `data/`/`Transcripts/` accordingly.

The legacy GCS state bucket
(`gs://operational-intelligence-ebe23-pipeline-state`) persisted `data/` +
`Transcripts/` between the nightly Cloud Run Job's runs; with that Job retired it
is no longer in the active path (left in place pending operator cleanup — see
`docs/Cloud-Pipeline-SOP.md`). Not web-exposed.

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
| `churnRisk`, `riskBand`, `confidence`, `topDriver`, `themes`, `sentimentTrend` (raw), `remediation`, `ai.action_items` | **Claude `claude-sonnet-4-6`** via the Agent SDK (`extract/ai.py`, subscription-billed) over the compiled context; recorded as `ai._model` |
| `riskBand` (shown), `sentimentTrend` (shown) | **Derived deterministically** in `build_overview.py` (`_tier`, `_reconcile_trend`) — not the LLM's free-form values |
| `csat`, `csatCoverage`, CSAT comments/stats | **TeamGPS** CSAT |
| `nps`, `portfolioNPS`, `npsResponses`, NPS comments/stats | **TeamGPS** NPS |
| `sip`, `activeSIPs`, `partnersWithSIP`, `client.sip_*` | **HaloPSA** type-99 tickets (`halo.count_sips`) |
| `actions`, `openActions`, `overdueActions`, `openNoDate` | **HaloPSA** meeting-note Actions + AI-extracted items |
| `accountManager`, `client.rag/cancel_risk/health_reason/next_step` | **HaloPSA** client metadata + custom RAG fields |
| `calls`, `callTone`, `toneConfident`, `historical_calls`, `coverage.calls*` | **HaloPSA** meeting notes + **Graph** transcript dates |
| `transcripts` | **MS Graph** `.vtt` + local `.docx` (markitdown) |
| `decks` | **HaloPSA** attachments → markitdown |
| `coverage.feedback*` | **TeamGPS** CSAT/NPS date span |

---

## 9. Going forward (operating model)

- **Refresh cadence (changed 2026-06-18):** **MANUAL**, run on a laptop, because
  the Claude Agent SDK bills the operator's interactive subscription and cannot
  legitimately run unattended. The nightly Cloud Run Job + Cloud Scheduler trigger
  (`partnerpulse-nightly`, 21:00 America/New_York) are **retired and should be
  disabled by an operator** (e.g. `gcloud scheduler jobs pause …` / delete the
  Job) — this change does not itself disable them. Manual cycle:
  `python -m extract.build_all` → `python scripts/build_overview.py` →
  `python scripts/upload_firebase_data.py`.
- **Source of truth for serving** is still **Firestore**; it is overwritten by the
  manual `upload_firebase_data.py` step after each local build. The cloud footprint
  is now **Hosting + Firestore serving only** — no AI or pipeline runs in the cloud.
- **`firebase deploy` ships UI/rules only** — data changes flow through a local
  build + `upload_firebase_data.py`, not a redeploy.
- **Adding/removing a partner** still happens in code (`extract/partners.py` or
  `scripts/build_real_partners.py` NEW) + the allowlist — then a manual build +
  upload propagates it to Firestore. Never hand-edit `data/` or Firestore docs.
- **AI auth:** the Claude subscription is reached via the local Claude Code OAuth
  login (`claude setup-token` / `claude login`); there is **NO API key** and no
  cloud secret for AI (`ai.py` strips `ANTHROPIC_API_KEY`; the `azure-openai-key`
  Secret Manager entry was removed). Halo/TeamGPS/Graph secrets remain in Secret
  Manager (rotation still owed — see `Firebase-Deploy-SOP.md` §0 and
  `Cloud-Pipeline-SOP.md` "Notes").
