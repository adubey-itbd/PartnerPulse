# LLM SOP — Documentation Maintenance (PartnerPulse)

> **Audience:** any LLM/agent making a change to this repo. **Pass this file (or its
> contents) with every turn.** After completing ANY code, data-pipeline, UI, or
> structural change, you MUST walk the checklist below before declaring the work done.
> This SOP applies to itself: if your change invalidates anything written here
> (docs added/moved/renamed, new update rules, new gotchas), update this file too.

---

## 1. Documentation registry

Every doc in this repo, what it covers, and when a change obligates an update:

| Doc | Covers | Update when… |
|---|---|---|
| `CLAUDE.md` (repo root) | LLM working context: commands, repo layout, critical gotchas, pointers | Commands change, files move, a new gotcha is discovered, a doc is added/renamed |
| `README.md` | Human quick start, manual usage, "How it works" file tree, roadmap | Setup/commands change, files move, components are added/removed |
| `docs/architecture.md` | System design: pipeline, cache schema, tradeoffs, data sources, data-integrity notes, demo-vs-real composition | Pipeline steps / schema keys / file layout / frontend data flow / partner composition change |
| `docs/Data-Schema.md` | **Authoritative end-to-end source→pipeline→store→consumer map**: data sources, local cache + feed schema, Firestore sharded layout, GCS state, field provenance, operating model | A data source, JSON/feed key, Firestore collection/doc shape, or storage location changes |
| `docs/Firebase-Deploy-SOP.md` | Hosted deployment: Firebase Hosting + Firestore (sharded), email/password `@itbd.net` auth, `firestore.rules`, the `upload_firebase_data.py` publish, deploy steps | Auth method, Firestore layout/rules, hosting/deploy steps, or `auth.js`/`firebase-config.js` change |
| `docs/Cloud-Pipeline-SOP.md` | Cloud Run Job + Cloud Scheduler nightly pipeline: `cloud_sync.py`, Dockerfile image, Secret Manager, GCS state bucket, resource names, provisioning + operate runbook | The job/schedule/secrets/bucket/image or any provisioning step changes |
| `docs/changelog.md` | Keep-a-Changelog history, semver `1.0.0-beta.N` | **Every user-visible or behavioural change** — add to today's `[Unreleased]`/newest entry or create a new `beta.N+1` dated entry |
| `docs/Data-Extraction-SOP.md` | The per-partner extraction procedure (transcripts, CSAT, NPS, client metadata, ticket notes, SIP counts, execution workflow) | An extraction step is added/removed/reordered, or an endpoint/filter pattern changes |
| `docs/HaloPSA-API-SOP.md` | Halo REST reference: auth, quirks, addenda of verified findings, endpoint catalogue, lookup decodes | A new Halo API behaviour/quirk is **verified** — append a dated addendum section; never silently rewrite older findings (mark them superseded) |
| `docs/TeamGPS-Open-API-SOP.md` | TeamGPS Open API reference: auth, pagination, endpoints | A new TeamGPS behaviour/endpoint is verified (same addendum style) |
| `docs/IT-Request-Graph-Transcript-Access.md` | Pending IT request: Graph app registration for transcript ingestion | The request is granted/denied/changed — record the outcome and the app id, or mark it withdrawn |
| `docs/demo-architecture-baseline.md` | Copy-paste baseline (prompt + grounded content) for generating an exec system-architecture diagram | The architecture/pipeline changes materially, or the demo framing changes |
| `docs/LLM-SOP.md` (this file) | Doc registry + maintenance procedure | Docs are added/moved/renamed; update rules or repo conventions change |
| `docs/archive/` | Frozen artifacts (saved session logs) | Never edited — only add to it |

Not documentation, but doc-adjacent — keep in sync when relevant:
* `.env.example` (new secret/env var introduced) and `.gitignore` (new generated-file pattern).
* **A new secret/env var also means:** add it to `scripts/seed_secrets.py` `SECRETS` and to the Cloud Run Job's `--set-secrets` (see `Cloud-Pipeline-SOP.md`). (The AI layer no longer needs a secret: as of 2026-06-18 churn analysis is Claude via the Claude Agent SDK, billed to the operator's Claude subscription through the local `claude` OAuth login — there is NO API key, no `azure-openai-key` secret, and `extract/ai.py` strips `ANTHROPIC_API_KEY` on import. The model is set by the `CLAUDE_MODEL` env var; do NOT set `ANTHROPIC_API_KEY`.)
* `firebase.json` / `.firebaserc` / `firestore.rules` / `firestore.indexes.json`, `firebase-config.js`, `auth.js` (Firebase deploy surface — keep `Firebase-Deploy-SOP.md` true).
* `storage.rules` (GCS state-bucket access policy for the pipeline — keep `Cloud-Pipeline-SOP.md` true).
* `Dockerfile` / `.dockerignore` / `.gcloudignore` (pipeline image — keep `Cloud-Pipeline-SOP.md` true).
* `extract/textutil.py` (canonical `slugify` / `normalize` name-normalization helpers shared by `extract/transcripts.py`, `scripts/audit_data.py`, et al.) — if you change slug/normalize behaviour, gotcha 3 / consistency rule 3 and `Transcripts/` matching (rule 8) must stay true.

## 1b. Enforcement — pre-commit hook

This SOP is **mechanically enforced** by `hooks/pre-commit` (activated via
`git config core.hooksPath hooks`, which `setup.ps1` sets automatically):

* Any commit staging code/config (anything outside `docs/`, `README.md`,
  `CLAUDE.md`) **without** `docs/changelog.md` staged is **blocked**.
* Doc-only commits pass. When the changelog IS staged, the hook prints a reminder
  to sweep the rest of the registry — it cannot verify the *content* of doc
  updates, only their presence. The semantic check (step 2 below) is on you.
* Human-only escape hatch: `SKIP_DOCS_CHECK=1 git commit …`. LLMs must NOT use it
  (nor `--no-verify`) — fix the docs instead.
* If you change the hook's rules or location, update this section, `CLAUDE.md`,
  and `setup.ps1` together.

## 2. Procedure (run after every change)

1. **Identify what changed:** code, schema, pipeline step, file location, command,
   UI behaviour, partner composition, or a newly verified API quirk.
2. **Sweep the registry table** above top-to-bottom and update every doc whose
   "Update when…" condition is met. Most changes touch `docs/changelog.md` plus
   one or two others.
3. **Grep for stale references** to anything you renamed, moved, or deleted:
   ```
   grep -rn "<old name>" README.md CLAUDE.md docs/*.md
   ```
   Fix every hit (except inside `docs/archive/`).
4. **Check this SOP:** does the registry above still describe reality? If you added,
   moved, or renamed a doc — or changed a convention — edit this file in the same turn.
5. **Verify claims you wrote:** docs must describe what the code DOES, not what was
   intended. If you state a path, command, schema key, or anchor string in a doc,
   confirm it exists in the code as written.

## 3. Repo-specific consistency rules (must stay true in code AND docs)

These invariants are easy to break silently; if your change touches one, both the
code and every doc that states it must move together:

1. **Single frontend data source (changed 2026-06-13, beta.8).** `index.html` is
   data-driven — both Executive Overview and Partner 360 `fetch` `data/_overview.json`
   (built by `scripts/build_overview.py`). There is **no embedded `const partners`
   array**; `partner.html`/`partner.js` still fetch `data/{slug}.json`. A partner-set or
   data change must reach the dashboard through the feed: `build_real_partners.py`
   (writes JSONs) → `extract.build_all --reindex` (`_index.json`) → `build_overview.py`
   (`_overview.json`). Never hand-edit generated JSON.
2. **No embedded-array injection anymore.** The `// ---- BEGIN/END real partners ----`
   markers and the array they wrapped are gone from `index.html`.
   `build_real_partners.py`'s `inject_exec` and `refresh_exec_row.py` detect their
   absence and no-op. Do not reintroduce an embedded array or those markers.
3. **Slug ≠ slugified display name** for several real partners ("MSP Corp" →
   `mspcorp`, "RealTime, LLC" → `realtime-it`, "Alliance InfoSystems LLC" →
   `alliance-infosystems`, "Stasmayer Inc." → `stasmayer`). Exec-overview objects
   carry an explicit `slug:` field; never derive links from display names.
4. **All data is real — never reintroduce synthetic/demo partners.** The demo
   seeder and all `demo: true` data were deliberately wiped on 2026-06-11.
5. **Generated files live in `data/` and the whole directory is gitignored**
   (`/data/` — nothing under it is ever tracked). Scripts must not write generated
   artifacts to the repo root, and nothing hand-written (scripts, secrets) belongs
   in `data/` — operational scripts go in `scripts/`.
6. **Scripts live in `scripts/` and sys.path-shim the repo root** so
   `from extract import …` works from any cwd. New operational scripts follow the
   same pattern; library code goes in `extract/`.
7. **API-SOP addendum discipline:** new verified API findings are appended as dated
   addendum sections ("Addendum — <topic> (YYYY-MM-DD session)") that explicitly
   supersede earlier statements rather than rewriting them.
8. **`Transcripts/` conventions (git-tracked input data):** one folder per partner,
   whose name must normalize-match the partner's display name — `slugify(folder)` ==
   `slugify(registry name or NEW display name)` — or the files are silently ignored
   (a warning fires in `build_real_partners.py` for orphan folders). Files are
   `.docx` (manual Teams exports) or `.vtt` (Graph pulls); every `.vtt` starts with
   `WEBVTT` + `NOTE title:` / `NOTE date:` / `NOTE duration:` lines (keys matched
   case-insensitively). Keep transcript content verbatim — never summarize or edit it.
9. **The partner roster lives in two places only:** `extract/partners.py` PARTNERS
   (the 10 registry partners, full build incl. decks) and
   `scripts/build_real_partners.py` NEW (everything else — 72 entries,
   the full DES/MDE roster from Halo report 364 `Area.CFMDERAG >= 1`; 70 as of
   2026-06-15, + CPCORP Inc & Stratti on 2026-06-16).
   Adding a partner = a NEW entry (resolve the Halo client id first; `client_id=None` for
   transcript-only partners with no Halo record) + run the script + `extract.build_all
   --reindex` + `scripts/build_overview.py`. Never add partners by editing `index.html`
   or `data/` by hand (rule 1).
10. **Demo-roster allowlist:** `data/_demo_roster.json` (if present, gitignored) filters
   the dashboard feed to a curated subset of slugs (`build_overview.py`) — sync-proof and
   reversible. It hides, never deletes; remove the file to show all built partners. Keep
   it in sync with reality (a slug that no longer builds will be flagged by
   `scripts/audit_data.py`).
11. **Two runtimes, one data shape (changed 2026-06-16).** Pages never read storage
   directly — they call `window.PP_AUTH.loadOverview()` / `loadPartner(slug)` /
   `lastSyncStamp()` (`auth.js`). LOCAL dev reads `data/*.json` (no auth); PRODUCTION
   reads **Cloud Firestore** (verified `@itbd.net` email/password). Both return the SAME
   shapes (the `_overview.json` feed and the `{slug}.json` blob). If you change a feed or
   blob key, update BOTH the producers (`build_overview.py` / `build_partner.py`) and the
   Firestore publisher (`upload_firebase_data.py` `_PROFILE_KEYS` / `_SECTIONS`) — and
   `Data-Schema.md`. **Firestore is the production source of truth for serving**; it is
   republished every night, never hand-edited.
12. **Firebase SDK + auth tags live in BOTH HTML heads (gotcha 7 extension).** The
   firebase-app/auth/firestore compat `<script>`s + `firebase-config.js` + `auth.js` are
   in `index.html` AND `partner.html`. Add to both or prod auth breaks on one page.
13. **Refresh is now a MANUAL local cycle (changed 2026-06-18); the nightly Cloud Run Job
   is retired.** The AI step is Claude via the Claude Agent SDK billed to the operator's
   Claude subscription, and subscription auth is for individual interactive use — it cannot
   legitimately bill from unattended cloud automation. So the cycle runs manually on a laptop:
   `python -m extract.build_all` → `python scripts/build_overview.py` →
   `python scripts/upload_firebase_data.py`. The nightly `partnerpulse-nightly` Cloud Run Job
   / Cloud Scheduler trigger (`scripts/cloud_sync.py`) is retired and should be disabled by an
   operator (`gcloud scheduler jobs pause …` / delete the Job) — that operator action is NOT
   performed by code changes, so do not claim it is deleted, only that it is retired. The cloud
   footprint is now Firebase Hosting + Cloud Firestore SERVING only. If the manual cycle's steps
   change, update `server.py` `SYNC_STEPS` (local), `cloud_sync.py` (if it is ever revived), and
   `Cloud-Pipeline-SOP.md` together.
14. **The public `feedback` collection is the ONLY client-writable Firestore path
   (added 2026-06-17).** `feedback.html` is intentionally **ungated** — it loads
   `firebase-config.js` + the firestore SDK but **NOT `auth.js`**, and writes auto-id docs
   to `feedback`. `firestore.rules` allows **create-only**, validated by `isValidFeedback()`
   (required `message` ≤5000, `submitted_at == request.time`, optional fields type/size-
   capped, `hasOnly` key lock); no client reads/updates/deletes. Everything else stays
   deny-all. If you change the form's field set, update `isValidFeedback()`'s key list and
   `Data-Schema.md` together; never add `auth.js` to `feedback.html` (it would break the
   shareable, no-sign-in flow). Statements that "all client writes are denied" must read
   "dashboard client writes are denied" — keep `firestore.rules`, `architecture.md`,
   `Data-Schema.md`, and `Firebase-Deploy-SOP.md` consistent.

## 4. Changelog conventions

* Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) with
  `### Added / Changed / Fixed / Removed` subsections; newest entry on top.
* Versioning: `1.0.0-beta.N` — bump `N` for each distinct dated batch of work; reuse
  the same entry for further same-day changes.
* Write entries for the reader of the dashboard/repo, not a git diff: say what
  changed and why it matters, name the files in backticks.

## 5. Definition of done

A change is complete only when: the code works, `docs/changelog.md` has the entry,
every registry doc whose condition fired is updated, no stale references remain
(step 2.3), and this SOP still describes the repo accurately.
