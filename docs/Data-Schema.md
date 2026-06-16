# Data Schema & Data-Flow — PartnerPulse / Operational Intelligence

**The authoritative map of where every piece of data comes from, how it is
processed, and where it is stored — end to end.** Read this with
`docs/architecture.md` (system design), `docs/Firebase-Deploy-SOP.md` (the hosted
deployment) and `docs/Cloud-Pipeline-SOP.md` (the nightly job).

Last reworked **2026-06-16**, when the pipeline moved to a scheduled Cloud Run
Job and the dashboard moved to Firebase Hosting + Cloud Firestore.

---

## 0. One-screen flow

```
 SOURCES (upstream truth)        PIPELINE (nightly, Cloud Run Job)         STORES                         CONSUMERS
 ─────────────────────────       ─────────────────────────────────        ──────────────────────────     ─────────────────
 HaloPSA REST  ───────────┐      scripts/cloud_sync.py:                    GCS state bucket               browser (Firebase
 TeamGPS Open API ────────┤        1. pull state ← GCS                     gs://…-pipeline-state          Hosting, @itbd.net
 MS Graph (Teams) ────────┼────▶   2. pull_graph_transcripts  ──▶          (data/ + Transcripts/,           email/pw sign-in)
 local decks/.docx ───────┤        3. extract.build_all (gpt-5.4)          incl. gpt-5.4 cache)               │  reads via
 Azure OpenAI gpt-5.4 ────┘        4. build_real_partners                       ▲      │                       │  auth.js
                                   5. build_all --reindex                       │ persist                     ▼
                                   6. build_overview  ──▶ data/*.json  ─────────┘      └──▶ Cloud Firestore ──▶ Exec Overview
                                   7. upload_firebase_data  ─────────────────────────────▶ (sharded docs)      + Partner 360
                                   8. push state → GCS
```

Three different "stores" hold the same data at three stages:

| Store | Role | Lifetime / source of truth |
|---|---|---|
| **External APIs** (Halo / TeamGPS / Graph) | Upstream operational systems | The real source of truth for the raw facts; queried read-only. |
| **`data/*.json` + GCS state bucket** | Pipeline working cache (incl. the gpt-5.4 cache) | Intermediate. The bucket is the durable copy between nightly runs; local `data/` is just a dev convenience. |
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
| **Azure OpenAI — gpt-5.4** (`*.cognitiveservices.azure.com`) | `extract/ai.py` | `AZURE_OPENAI_KEY` | The churn analysis: risk score/band, confidence, sentiment, drivers, remediation, extracted action items. |

All secrets live in **Secret Manager** in the cloud (loaded by
`scripts/seed_secrets.py`) and in `.env` / `extract/config.py` fallbacks for local
runs. **No external/web data** is used — churn risk is inferred entirely from
internal signals (see `architecture.md` §7).

---

## 2. Pipeline (how it's processed)

The nightly **Cloud Run Job** runs `scripts/cloud_sync.py`, which executes the
same cycle the local "Sync Data" button used to (that button was removed
2026-06-16):

1. **Pull state** from `gs://…-pipeline-state` → `data/` + `Transcripts/` (so the gpt-5.4 cache and transcript history are present).
2. `pull_graph_transcripts.py --write` — fresh `.vtt` from Graph.
3. `extract.build_all` — per partner: Halo + TeamGPS fetch, doc/transcript parse, **gpt-5.4** churn analysis → `data/{slug}.json`. **Incremental**: the AI is cached by an input hash and skipped when inputs are unchanged (no score drift); decks cached by attachment id.
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
      "topDriver", "themes",                  // themes ← gpt-5.4 drivers[]
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
```

**Access (`firestore.rules`):** read allowed only for a **verified `@itbd.net`**
account (`email_verified == true` + domain regex); **all client writes denied**.
The pipeline writes via the Admin SDK / attached service account, which bypasses
rules. `firestore.indexes.json` is empty — the overview fetches all summary docs
and filters client-side (fine to a few hundred partners; past that, switch
`loadOverview()` to a server-side `orderBy('churnRisk').limit()` query + composite
index).

---

## 6. GCS state bucket (pipeline persistence)

`gs://operational-intelligence-ebe23-pipeline-state` holds `data/` and
`Transcripts/` between nightly runs. **Why it exists:** the build is incremental
(gpt-5.4 cached by input hash → stable scores) and Teams drops transcript content
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
| `churnRisk`, `riskBand`, `confidence`, `topDriver`, `themes`, `sentimentTrend` (raw), `remediation`, `ai.action_items` | **Azure gpt-5.4** (`extract/ai.py`) over the compiled context |
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
