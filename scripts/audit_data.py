#!/usr/bin/env python
"""Data-integrity audit for the AI-Driven Operational Intelligence dashboard.

Reads the generated caches (data/*.json), the portfolio index (data/_index.json),
the dashboard feed (data/_overview.json) and the Transcripts/ folders, and flags the
data-accuracy problems that have bitten us — so they can be caught in one pass instead
of partner-by-partner. NO API calls; runs in a second.

    python scripts/audit_data.py

Checks (per partner unless noted):
  1. SIP recorded but not counted   — client.sip_ticket names a ticket but open+closed==0
  2. AI analysis missing/failed     — no ai block, risk_score None, _error, or 0 drivers
  3. CSAT empty                     — 0 CSAT comments on a real Halo client (likely a
                                      TeamGPS company-name mismatch)
  4. Last call stale / absent       — newest Halo-note OR transcript date missing / >45d
  5. Transcripts on disk not ingested — a Transcripts/<folder> that matches no built
                                      partner (folder-name mismatch or not onboarded)
  6. Feed integrity                 — _overview.json covers every indexed partner
"""
import json
import os
import re
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TRANSCRIPTS = os.path.join(ROOT, "Transcripts")
TODAY = date(2026, 6, 13)
STALE_DAYS = 45


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _date_from(*strings):
    for s in strings:
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", str(s or ""))
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        m = re.match(r"\s*(20\d{2})-(\d{2})-(\d{2})", str(s or ""))
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    return None


def main():
    idx_path = os.path.join(DATA, "_index.json")
    if not os.path.exists(idx_path):
        sys.exit("no data/_index.json — build first")
    idx = json.load(open(idx_path, encoding="utf-8"))
    partners = idx.get("partners", [])
    findings = {1: [], 2: [], 3: [], 4: [], 5: [], 6: []}

    # If a demo-roster allowlist is active, scope the partner-level checks to it
    # (the hidden partners' caches still exist but aren't shown, so don't audit them).
    allow = None
    roster_path = os.path.join(DATA, "_demo_roster.json")
    if os.path.exists(roster_path):
        allow = set(json.load(open(roster_path, encoding="utf-8")))

    known_slugs = set()
    for row in partners:
        slug = row["slug"]
        known_slugs.add(_slug(row.get("name")))   # full roster — so hidden partners' folders don't false-flag check 5
        known_slugs.add(_slug(slug))
        if allow is not None and slug not in allow:
            continue
        path = os.path.join(DATA, f"{slug}.json")
        if not os.path.exists(path):
            findings[6].append(f"{row.get('name')}: indexed but no data/{slug}.json")
            continue
        d = json.load(open(path, encoding="utf-8"))
        c = d.get("client", {}) or {}
        ai = d.get("ai") or {}
        name = row.get("name") or slug

        # 1. SIP recorded but not counted
        sip_field = str(c.get("sip_ticket") or "")
        if re.search(r"\d{4,}", sip_field) and (c.get("sip_open", 0) or 0) + (c.get("sip_closed", 0) or 0) == 0:
            findings[1].append(f"{name}: sip_ticket={sip_field!r} but counts 0/0")

        # 2. AI health
        if not ai or ai.get("risk_score") is None or ai.get("_error") or not (ai.get("drivers") or []):
            findings[2].append(f"{name}: risk_score={ai.get('risk_score')} drivers={len(ai.get('drivers') or [])}"
                               + (f" err={ai.get('_error')}" if ai.get("_error") else ""))

        # 3. CSAT empty on a real client
        if c.get("id") and len(d.get("csat_comments") or []) == 0:
            findings[3].append(f"{name}: 0 CSAT comments (teamgps name mismatch?)")

        # 4. last call
        hc = [_date_from(x.get("date")) for x in (d.get("historical_calls") or [])]
        tr = [_date_from(t.get("title"), t.get("filename"), t.get("date")) for t in (d.get("transcripts") or [])]
        alldates = sorted(x for x in hc + tr if x)
        if not alldates:
            findings[4].append(f"{name}: no call date (Halo notes + transcripts both empty)")
        elif (TODAY - alldates[-1]).days > STALE_DAYS:
            findings[4].append(f"{name}: last call {alldates[-1].isoformat()} ({(TODAY - alldates[-1]).days}d ago)")

    # 5. transcript folders not matched to any built partner
    if os.path.isdir(TRANSCRIPTS):
        for folder in sorted(os.listdir(TRANSCRIPTS)):
            fpath = os.path.join(TRANSCRIPTS, folder)
            if not os.path.isdir(fpath):
                continue
            files = [f for f in os.listdir(fpath) if f.lower().endswith((".vtt", ".docx"))]
            if files and _slug(folder) not in known_slugs:
                findings[5].append(f"{folder}/ ({len(files)} files) — matches no built partner")

    # 6. feed integrity
    ov_path = os.path.join(DATA, "_overview.json")
    if not os.path.exists(ov_path):
        findings[6].append("data/_overview.json missing — run scripts/build_overview.py")
    else:
        ov = json.load(open(ov_path, encoding="utf-8"))
        ov_slugs = {p["slug"] for p in ov.get("partners", [])}
        expected = allow if allow is not None else {row["slug"] for row in partners}
        for slug in expected:
            if slug not in ov_slugs:
                findings[6].append(f"{slug}: expected on dashboard but missing from _overview.json")
        extra = ov_slugs - expected
        if extra:
            findings[6].append(f"feed shows partners not in the demo roster: {sorted(extra)}")

    titles = {
        1: "SIP recorded but not counted", 2: "AI analysis missing/failed",
        3: "CSAT empty (possible TeamGPS name mismatch)", 4: "Last call stale (>45d) or absent",
        5: "Transcripts on disk not ingested (unmatched folder)", 6: "Feed / index integrity",
    }
    scope = f"{len(allow)} demo-roster partners" if allow is not None else f"{len(partners)} partners"
    print(f"\n===== DATA AUDIT — {scope}, as of {TODAY} =====")
    total = 0
    for k in sorted(findings):
        items = findings[k]
        total += len(items)
        mark = "OK  " if not items else "WARN"
        print(f"\n[{mark}] {k}. {titles[k]} — {len(items)}")
        for it in items:
            print(f"        - {it}")
    print(f"\n===== {total} findings total =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
