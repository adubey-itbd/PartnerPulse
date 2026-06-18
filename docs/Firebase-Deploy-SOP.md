# Firebase Deployment SOP — PartnerPulse

How to take the dashboard live on **Firebase**, authenticated and internal-only
(`@itbd.net`). Project: **`operational-intelligence-ebe23`** (Blaze plan).

**All dashboard data lives in Cloud Firestore, sharded** — there is no big
per-partner blob and no Cloud Storage. The browser reads Firestore directly via
the Web SDK, secured by `firestore.rules`.

```
meta/overview                     portfolio rollups + coverage   (Exec Overview)
partners/<slug>                   per-partner summary doc        (Exec Overview)
partners/<slug>/detail/profile    { meta, client, ai, csat_stats, nps_stats }
partners/<slug>/transcripts/<i>   one doc per call transcript
partners/<slug>/decks/<i>         one doc per converted deck
partners/<slug>/calls/<i>         one doc per service-review note (historical_calls)
partners/<slug>/csat/<i>          one doc per CSAT comment
partners/<slug>/nps/<i>           one doc per NPS response
partners/<slug>/actions/<i>       one doc per action item
```

Why sharded: a single partner's blob grows every time a transcript/deck is added
and would eventually cross Firestore's **1 MiB doc cap**; sharding removes that
ceiling, lets the pipeline write one new item without rewriting the partner,
enables cross-partner queries ("all overdue actions", "all detractors"), and
makes the data browsable doc-by-doc in the console. Each detail doc carries `_i`
(its source-list index) so the UI restores order via `orderBy('_i')`.

> Local development is unaffected: `python server.py` serves everything from the
> `data/*.json` caches with no auth. `auth.js` auto-detects localhost (or an
> unconfigured `firebase-config.js`) and runs in DEV mode — `loadOverview()` /
> `loadPartner()` read the local JSON instead of Firestore.

## Architecture

```
browser ──(email/password sign-in, verified @itbd.net)──▶ Firebase Hosting (static UI: html/js/css)
   │
   └─ data:  Firestore Web SDK ──▶ Cloud Firestore
                                   meta/overview, partners/<slug>(+subcollections)
                                   (firestore.rules: read if verified @itbd.net;
                                    dashboard client writes denied)

public feedback form (feedback.html, NO sign-in) ──▶ Firestore `feedback` (create-only, validated)

pipeline (local laptop) ──▶ scripts/upload_firebase_data.py ──▶ Firestore (Admin SDK, bypasses rules)
```

The build pipeline (HaloPSA + TeamGPS + Graph + Claude churn analysis) runs **locally
on a laptop** and the operator publishes the result to Firestore with
`scripts/upload_firebase_data.py` (Admin SDK). **Changed 2026-06-18:** the AI step is
now Claude via the **Claude Agent SDK**, billed to the operator's Claude subscription
through the local Claude Code OAuth login (no API key) — subscription auth is for
interactive use, so the **nightly Cloud Run Job is retired** for data refresh and the
build runs manually (see `docs/Cloud-Pipeline-SOP.md`). The cloud footprint is now
**Hosting + Firestore serving only**. There is **no in-app "Sync Data" button** — it
was removed 2026-06-16; `refresh.js` only renders the "Last sync" stamp. `firebase
deploy` ships the **UI and rules only** — never data.

## Files

| File | Role |
|------|------|
| `firebase.json` | Hosting + Firestore config (no functions, no storage) |
| `.firebaserc` | project alias → `operational-intelligence-ebe23` |
| `firestore.rules` | read `meta/*` + `partners/{slug}/**` if verified `@itbd.net`; dashboard writes denied; public `feedback` create-only (validated) |
| `firestore.indexes.json` | empty (overview fetches all summary docs, filters client-side) |
| `firebase-config.js` | **public** web SDK config (filled) |
| `auth.js` | client gate + Firestore data layer (`loadOverview` / `loadPartner` / `lastSyncStamp`); DEV-mode on localhost |
| `feedback.html` | **public** (ungated) feedback form; loads firebase-config + firestore SDK (NOT `auth.js`), writes the `feedback` collection |
| `scripts/upload_firebase_data.py` | publish the sharded Firestore tree from the caches |

## One-time setup

0. **Rotate the live API keys** (Halo, TeamGPS, Graph) in `.env` /
   `extract/config.py`; move to Secret Manager. (Excluded from the deploy, but
   they were committed — rotate anyway.) The AI layer no longer uses an Azure key —
   it is Claude via the Agent SDK on the local Claude Code OAuth login, no API key.
1. Toolchain (done this session): `firebase-tools` installed, `firebase login`,
   `.firebaserc` set, `firebase-config.js` filled.
2. In the console (Blaze):
   - **Authentication → Sign-in method → Email/Password** — enable. (ITBD is on
     Microsoft 365, not Google Workspace, so Google federation is not used.)
     Authorized domains already include `*.web.app` / `*.firebaseapp.com`.
     The domain is restricted client-side in `auth.js`; the real gate is email
     verification (`firestore.rules` require `email_verified`).
   - **Firestore Database** — *Create database*, **production mode**, in
     **`us-central1`** (the region production actually uses — it matches the
     Cloud Run Job and the GCS state bucket; the choice is **permanent**).
3. Push the security rules:
   ```powershell
   firebase deploy --only firestore:rules
   ```

## Deploying the UI / rules (`firebase deploy`)

**`firebase deploy` ships only the static UI and the Firestore rules — never
data.** Use it after a change to `index.html` / `partner.html` / `partner.js` /
`refresh.js` / `auth.js` / `firebase-config.js` / `styles.css` / `vendor/`, or to
`firestore.rules` / `firestore.indexes.json`.

```powershell
# Ship the UI (and rules/indexes if they changed)
firebase deploy --only hosting
firebase deploy --only firestore:rules     # only when firestore.rules changed
firebase deploy --only firestore:indexes   # only when firestore.indexes.json changed
```

Use `firebase hosting:channel:deploy preview` for a throwaway preview URL.

## Refreshing the data (NOT a deploy)

Data is **not** part of `firebase deploy`. **Changed 2026-06-18:** the data is now
refreshed by a **manual local build** rather than the nightly Cloud Run Job (which is
retired — the Claude Agent SDK bills the operator's subscription and can't legitimately
run unattended in the cloud; see `docs/Cloud-Pipeline-SOP.md`). Run the full cycle on a
laptop, then publish to Firestore — signed-in users see the new data on next load:

```powershell
python -m extract.build_all                       # pull + Claude churn analysis (local, subscription-billed)
python scripts/build_overview.py                  # rebuild the dashboard feed
pip install google-cloud-firestore                # once
gcloud auth application-default login             # once
python scripts/upload_firebase_data.py --dry-run  # review the plan + counts
python scripts/upload_firebase_data.py            # publish (idempotent, reconciled)
```

(While the `partnerpulse-nightly` Cloud Run Job still exists it should be paused —
e.g. `gcloud scheduler jobs pause …` — and is no longer the data-refresh path.)

## Verify

- Signed out → sign-in overlay; a non-`@itbd.net` email is rejected client-side,
  and an unverified `@itbd.net` account is held at "verify your email" (and
  blocked by the rules) until the verification link is clicked.
- Signed in as a verified `@itbd.net` → Overview (`meta/overview` + `partners/*`) and
  Partner 360 (`partners/<slug>` + subcollections) load.
- Firestore console → `partners/<slug>/csat/0000` etc. populated by a manual
  `upload_firebase_data.py` run.
- `https://<site>/data/<anything>.json` → **404** (data isn't hosted statically).

## Add a partner (cloud)

A partner reaches production through the (now manual, local) pipeline + Firestore,
never by a deploy or a hand-edit:

1. Add the partner in **code**: a `NEW` entry in `scripts/build_real_partners.py`
   (resolve the Halo client id first; `client_id=None` for a transcript-only
   partner with no Halo record) — or, for a registry partner, `extract/partners.py`.
2. If a curated roster is in force, add the partner's **slug** to the allowlist
   `data/_demo_roster.json` (otherwise the feed filters it out — gotcha 8).
3. Run the **manual local build cycle** (`build_real_partners` → `build_all
   --reindex` → `build_overview` → `upload_firebase_data`) on a laptop; the last step
   publishes the new partner to Firestore (see "Refreshing the data" above).

## Rollback

- **UI / rules:** redeploy a previous revision. `firebase hosting:rollback` reverts
  Hosting to the prior release; for rules, re-deploy the previous `firestore.rules`
  from git (`git checkout <good-sha> -- firestore.rules` → `firebase deploy --only
  firestore:rules`).
- **Data:** Firestore holds only the latest published snapshot, so recover the
  *inputs* and re-publish. The GCS **state bucket has Object Versioning enabled**, so
  a prior `data/`/`Transcripts/` snapshot can be restored
  (`gcloud storage cp --recursive gs://operational-intelligence-ebe23-pipeline-state
  …` of an earlier generation, or `gcloud storage ls -a` to list versions), then run
  `python scripts/upload_firebase_data.py` to republish that snapshot. (With the
  pipeline now manual/local, the laptop's own `data/`/`Transcripts/` is usually the
  recovery source.) See `docs/Cloud-Pipeline-SOP.md` for the full state-bucket runbook.

## Gotchas

- **gotcha 7 still applies** — Firebase app/auth/firestore SDK tags + `auth.js` +
  `firebase-config.js` are in BOTH `index.html` and `partner.html` heads.
- **Data refresh = a manual local build + `upload_firebase_data.py` (the nightly Job
  is retired, 2026-06-18), not a redeploy.** `firebase deploy` ships UI/rules only;
  Firestore content changes live for signed-in users on next load.
- **Don't move data into the Hosting `public` set** — keep all data in Firestore
  behind the rules. (`firebase.json` already ignores `data/`, `extract/`, `scripts/`,
  `Transcripts/`, `docs/`, and every `*.py`/`*.md`.)
- **Scaling note:** the overview fetches *all* summary docs and filters
  client-side — fine to a few hundred partners (~1.5 KB each). Past that, switch
  `loadOverview()` to a Firestore `orderBy('churnRisk','desc').limit(...)` query
  with server-side filters (data model already supports it; add the composite
  indexes to `firestore.indexes.json` then).
- **Per-partner read count:** opening a partner reads its profile + all
  subcollection docs (a heavy partner like `mspcorp` ≈ 200 reads). Comfortably
  inside the free 50K reads/day for internal use; if it ever matters, lazy-load
  each subcollection only when its tab is opened.

## Outstanding follow-ups

Security/ops hardening not yet done — track and close these:

- **Firebase App Check** is not enabled. Adding it (reCAPTCHA/attestation) would
  stop the Web SDK config (public by design) from being reused outside the app to
  read Firestore within an authenticated `@itbd.net` session.
- **Multi-factor auth (MFA)** is not enforced on the email/password sign-in. The
  current gate is domain + email verification only; enabling MFA in the Identity
  Platform is the next step for an internal exec tool.
- **AI spend** is now on the operator's **Claude subscription** (Claude Agent SDK, no
  API key) — no Azure/OpenAI budget alert applies. The former Azure-OpenAI budget
  follow-up is obsolete as of 2026-06-18.
- **API-key rotation** (§0) is still owed — the keys were reused into Secret
  Manager as-is on 2026-06-16, not rotated.
