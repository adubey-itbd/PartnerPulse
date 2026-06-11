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
| `docs/changelog.md` | Keep-a-Changelog history, semver `1.0.0-beta.N` | **Every user-visible or behavioural change** — add to today's `[Unreleased]`/newest entry or create a new `beta.N+1` dated entry |
| `docs/Data-Extraction-SOP.md` | The per-partner extraction procedure (transcripts, CSAT, NPS, client metadata, ticket notes, SIP counts, execution workflow) | An extraction step is added/removed/reordered, or an endpoint/filter pattern changes |
| `docs/HaloPSA-API-SOP.md` | Halo REST reference: auth, quirks, addenda of verified findings, endpoint catalogue, lookup decodes | A new Halo API behaviour/quirk is **verified** — append a dated addendum section; never silently rewrite older findings (mark them superseded) |
| `docs/TeamGPS-Open-API-SOP.md` | TeamGPS Open API reference: auth, pagination, endpoints | A new TeamGPS behaviour/endpoint is verified (same addendum style) |
| `docs/LLM-SOP.md` (this file) | Doc registry + maintenance procedure | Docs are added/moved/renamed; update rules or repo conventions change |
| `docs/archive/` | Frozen artifacts (saved session logs) | Never edited — only add to it |

Not documentation, but doc-adjacent: `.env.example` (update when a new secret/env var
is introduced) and `.gitignore` (update when a new generated-file pattern appears).

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

1. **Two frontend data layers.** `index.html` has an **embedded** `const partners`
   array (Executive Overview + Partner 360); `partner.html`/`partner.js` **fetch**
   `data/{slug}.json` at runtime. Any partner-set change must hit both, via the
   injection scripts — never hand-edit one side only.
2. **Injection anchors are load-bearing strings.** `scripts/build_real_partners.py`
   splices between `// ---- BEGIN/END real partners ... ----` markers;
   `scripts/gen_demo_partners.py` splices after the last real partner's
   `lastCall: "…", callsAnalyzed: N },` line in `index.html`. Editing those lines in
   `index.html` breaks the scripts — update both together.
3. **Slug ≠ slugified display name** for several real partners ("MSP Corp" →
   `mspcorp`, "RealTime, LLC" → `realtime-it`, "Alliance InfoSystems LLC" →
   `alliance-infosystems`, "Stasmayer Inc." → `stasmayer`). Exec-overview objects
   carry an explicit `slug:` field; never derive links from display names.
4. **`DEMO_COUNT` in `scripts/gen_demo_partners.py` must stay 40** unless the user
   asks otherwise — the script deletes and regenerates all `demo: true` files, so a
   smaller value silently shrinks the dashboard.
5. **Generated files live in `data/` and are gitignored** (`*.json`, `*.log`, `*.js`,
   `decks/`). Scripts must not write generated artifacts to the repo root.
6. **Scripts live in `scripts/` and sys.path-shim the repo root** so
   `from extract import …` works from any cwd. New operational scripts follow the
   same pattern; library code goes in `extract/`.
7. **API-SOP addendum discipline:** new verified API findings are appended as dated
   addendum sections ("Addendum — <topic> (YYYY-MM-DD session)") that explicitly
   supersede earlier statements rather than rewriting them.

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
