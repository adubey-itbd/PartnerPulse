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
  4. Last call stale / absent       — newest Halo-note OR transcript date missing / >60d
  5. Transcripts on disk not ingested — a Transcripts/<folder> that matches no built
                                      partner (folder-name mismatch or not onboarded)
  6. Feed integrity                 — _overview.json covers every indexed partner
  7. NPS quality                    — a corporate domain credited to >1 partner, free-mail
                                      respondents, or respondents off the corporate domain
  8. Client-name mismatch           — indexed/display name vs the cached client name diverge
                                      (the Acrisure 937->79 wrong-record class)
  9. Built but excluded             — a real partner with a cache hidden by _demo_roster.json
"""
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA = os.path.join(ROOT, "data")
TRANSCRIPTS = os.path.join(ROOT, "Transcripts")
TODAY = date(2026, 6, 13)
# Match build_overview's stale-call threshold (60 days) so the audit flags exactly
# the partners the dashboard would treat as stale.
STALE_DAYS = 60

from extract.textutil import normalize as _slug

try:
    from extract.halo import fuzzy_name_match as _fuzzy_name_match
except (ImportError, AttributeError):
    _fuzzy_name_match = None

# Public free-mail providers: an NPS respondent on one of these is NOT a corporate
# contact, so the response is almost certainly mis-credited to a partner.
FREEMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com",
    "outlook.com", "live.com", "msn.com", "aol.com", "icloud.com", "me.com",
    "mac.com", "protonmail.com", "proton.me", "gmx.com", "mail.com",
    "zoho.com", "yandex.com", "comcast.net", "verizon.net", "att.net",
}


def _domain(email):
    e = (email or "").strip().lower()
    return e.split("@", 1)[1] if "@" in e else ""


def _names_match(a, b):
    """True if two client names plausibly refer to the same company. Uses
    halo.fuzzy_name_match when available (package C); else a normalize-substring
    fallback so the check still runs if that export has not landed."""
    if _fuzzy_name_match is not None:
        try:
            return bool(_fuzzy_name_match(a, b))
        except Exception:
            pass
    na, nb = _slug(a), _slug(b)
    if not na or not nb:
        return True   # nothing to compare -> don't flag
    return na == nb or na in nb or nb in na


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
    findings = {1: [], 2: [], 3: [], 4: [], 5: [], 6: [], 7: [], 8: [], 9: []}

    # NPS-quality bookkeeping: which partners each respondent domain was credited
    # to (a corporate domain shared by >1 partner means someone's NPS leaked in).
    domain_partners = {}

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

        # 7. NPS quality: free-mail respondents + a corporate-domain split.
        nps = d.get("nps_comments") or []
        nps_domains = Counter(_domain(r.get("respondent_email") or r.get("respondent"))
                              for r in nps)
        nps_domains.pop("", None)
        for dom in nps_domains:
            domain_partners.setdefault(dom, set()).add(name)
        free = {dom: n for dom, n in nps_domains.items() if dom in FREEMAIL}
        if free:
            findings[7].append(f"{name}: free-mail NPS respondents "
                               + ", ".join(f"{dom} x{n}" for dom, n in sorted(free.items())))
        # Corporate domain = the most common non-free-mail respondent domain.
        corp = [(dom, n) for dom, n in nps_domains.most_common() if dom not in FREEMAIL]
        if corp:
            corp_dom = corp[0][0]
            stray = sorted(dom for dom in nps_domains
                           if dom != corp_dom and dom not in FREEMAIL)
            if stray:
                findings[7].append(f"{name}: NPS respondents off the corporate domain "
                                   f"{corp_dom!r}: {', '.join(stray)}")

        # 8. client-name mismatch: indexed/display name vs the cached client name.
        cache_name = c.get("name") or ""
        if cache_name and not _names_match(name, cache_name):
            findings[8].append(f"{name}: index name vs cached client name {cache_name!r} do not match")

    # 7 (cross-partner): a single corporate domain credited to more than one partner.
    for dom, owners in sorted(domain_partners.items()):
        if len(owners) > 1 and dom not in FREEMAIL:
            findings[7].append(f"domain {dom} credited to {len(owners)} partners: "
                               + ", ".join(sorted(owners)))

    # 9. built but hidden by the allowlist: a real partner with a cache that the
    # demo roster excludes (e.g. mission-technology) — silently dropped from the feed.
    if allow is not None:
        for row in partners:
            slug = row["slug"]
            if slug in allow:
                continue
            if os.path.exists(os.path.join(DATA, f"{slug}.json")):
                findings[9].append(f"{row.get('name') or slug} ({slug}): built but excluded by _demo_roster.json")

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
        3: "CSAT empty (possible TeamGPS name mismatch)", 4: f"Last call stale (>{STALE_DAYS}d) or absent",
        5: "Transcripts on disk not ingested (unmatched folder)", 6: "Feed / index integrity",
        7: "NPS quality (free-mail / shared / off-domain respondents)",
        8: "Client-name mismatch (index vs cached client name)",
        9: "Built but excluded by demo-roster allowlist",
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
