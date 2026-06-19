#!/usr/bin/env python
"""Audit the CSAT Reconciliation data for EVERY partner.

Recomputes, from the authoritative sources (HaloPSA sent tickets + the per-partner
data/<slug>.json TeamGPS csat_comments), the same sent / received / CSAT numbers
build_csat_recon.py produces, and cross-checks them. It imports the builder's own
helpers (_ticket_month, _window_keys, _clean_name, TODAY) so the audit can never
silently diverge from the build logic.

Flags, per partner:
  * DRIFT          — the published data/_csat_recon.json row disagrees with a fresh
                     recompute (e.g. the feed was built against stale caches).
  * RECV_GT_SENT   — a month with received > sent (should be impossible).
  * RATED_GT_RECV  — rated responses exceed distinct answered tickets in a month
                     (a survey got multiple TeamGPS responses — informational).
  * MONTH_SHIFT    — a month's matched responses were mostly SUBMITTED in a different
                     calendar month than the survey month they're attributed to. This
                     is by design (reconciliation attributes a response to the month of
                     the survey it answers, not the month it was submitted), but it is
                     exactly what makes a month read "55% RR" while TeamGPS — which keys
                     off submission date — shows "no CSAT this month". Surfaced so the
                     number can be explained, not silently trusted.
  * NO_CLIENT      — partner has no Halo client_id (transcript-only); sent is always 0.
  * HALO_FAIL      — Halo failed for this partner this run (transient; rerun).

Run AFTER build_csat_recon.py, from the repo root (it hits Halo once per partner —
do NOT run it concurrently with a build, or Halo rate-limits both):
    python scripts/audit_csat_recon.py

Writes data/_csat_audit.json (full per-partner detail) and prints a summary. Exits
non-zero if any DRIFT / RECV_GT_SENT is found (the actionable problems).
"""
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
DATA = os.path.join(ROOT, "data")

import build_csat_recon as R  # noqa: E402  (reuse the builder's exact logic)
from build_csat_recon import (halo, _ticket_month, _window_keys, _parse_iso_date,  # noqa: E402
                               _responded, _claimed_tickets, _TICKET_REASSIGN)

# Clients whose CSAT tickets are reassigned across Halo records (build_csat_recon
# attributes their received globally, cross-blob). This per-partner audit can't mirror
# that, so it skips DRIFT for them and flags REASSIGNED instead (informational).
_REASSIGN_CLIENTS = {c for pair in _TICKET_REASSIGN for c in (pair[0],)} | set(_TICKET_REASSIGN.values())


def recompute(blob, client_id):
    """Return (cells, sent_ids, resp_submit_month) for one partner, mirroring
    build_csat_recon, plus the submission month of each matched response."""
    months = _window_keys()
    keys = [m["key"] for m in months]
    win = set(keys)
    cells = {k: {"sent": 0, "received": 0, "pos": 0, "rated": 0} for k in keys}
    sent_ids = {}
    if client_id:
        for t in _claimed_tickets(client_id, halo.fetch_csat_tickets):
            ym = _ticket_month(t.get("summary"), t.get("dateoccurred"))
            if not ym:
                continue
            key = f"{ym[0]}-{ym[1]:02d}"
            if key in win:
                cells[key]["sent"] += 1
                sent_ids[str(t.get("id"))] = key
    answered = {k: set() for k in keys}
    submit_months = defaultdict(Counter)   # survey-month -> Counter(response submit month)
    for c in blob.get("csat_comments", []) or []:
        if not _responded(c):
            continue
        tid = str(c.get("ticket_id") or "")
        key = sent_ids.get(tid)
        if not key:
            continue
        answered[key].add(tid)
        rt = str(c.get("rating") or "").capitalize()
        if rt in ("Positive", "Neutral", "Negative"):
            cells[key]["rated"] += 1
            if rt == "Positive":
                cells[key]["pos"] += 1
        d = _parse_iso_date(c.get("date"))
        submit_months[key][d.strftime("%Y-%m") if d else "?"] += 1
    for k in keys:
        cells[k]["received"] = len(answered[k])
    return keys, cells, submit_months


def main():
    feed_path = os.path.join(DATA, "_csat_recon.json")
    feed_rows = {}
    if os.path.exists(feed_path):
        feed = json.load(open(feed_path, encoding="utf-8"))
        feed_rows = {r["slug"]: r for r in feed.get("rows", [])}

    overview = json.load(open(os.path.join(DATA, "_overview.json"), encoding="utf-8"))
    report, flagged = [], Counter()

    for p in overview.get("partners", []):
        slug, name = p.get("slug"), p.get("name") or p.get("slug")
        blob_path = os.path.join(DATA, f"{slug}.json")
        if not slug or not os.path.exists(blob_path):
            continue
        blob = json.load(open(blob_path, encoding="utf-8"))
        client_id = (blob.get("client") or {}).get("id")
        flags = []
        if not client_id:
            flags.append("NO_CLIENT")
        try:
            keys, cells, submit_months = recompute(blob, client_id)
        except Exception as exc:
            flags.append("HALO_FAIL")
            report.append({"slug": slug, "name": name, "flags": flags, "error": str(exc)})
            for f in flags:
                flagged[f] += 1
            continue

        # invariants + month-shift
        month_detail = {}
        for k in keys:
            c = cells[k]
            if c["received"] > c["sent"]:
                flags.append(f"RECV_GT_SENT:{k}")
            if c["rated"] > c["received"]:
                flags.append(f"RATED_GT_RECV:{k}")
            if c["received"] > 0:
                sm = submit_months[k]
                in_month = sm.get(k, 0)
                if in_month * 2 < sum(sm.values()):   # majority submitted in another month
                    top = sm.most_common(1)[0]
                    flags.append(f"MONTH_SHIFT:{k}->{top[0]}")
                month_detail[k] = {**c, "submitMonths": dict(sm)}

        # drift vs published feed — skip clients whose tickets are reassigned cross-blob
        # (the builder attributes their received globally; this per-partner recompute can't).
        fr = feed_rows.get(slug)
        if client_id in _REASSIGN_CLIENTS:
            flags.append("REASSIGNED")
        elif fr:
            for k in keys:
                fc = (fr.get("months") or {}).get(k) or {}
                rc = cells[k]
                for fld in ("sent", "received", "pos", "rated"):
                    if int(fc.get(fld, 0)) != rc[fld]:
                        flags.append(f"DRIFT:{k}.{fld} feed={fc.get(fld,0)} real={rc[fld]}")

        rec_total = {f: sum(cells[k][f] for k in keys) for f in ("sent", "received", "pos", "rated")}
        if flags:
            for f in flags:
                flagged[f.split(":")[0]] += 1
        report.append({"slug": slug, "name": name, "flags": flags,
                       "recomputed_total": rec_total, "months": month_detail})

    out = {"as_of": R.TODAY.isoformat(), "partners": report,
           "flagCounts": dict(flagged)}
    json.dump(out, open(os.path.join(DATA, "_csat_audit.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    # ---- console summary ----
    actionable = ("DRIFT", "RECV_GT_SENT", "HALO_FAIL")
    print(f"\n=== CSAT recon audit ({len(report)} partners, as of {R.TODAY}) ===")
    print("flag counts:", dict(flagged) or "none")
    bad = [r for r in report if any(f.split(":")[0] in actionable for f in r["flags"])]
    shift = [r for r in report if any(f.startswith("MONTH_SHIFT") for f in r["flags"])]
    if bad:
        print(f"\n-- ACTIONABLE ({len(bad)}): drift / impossible / halo-fail --")
        for r in bad:
            print(f"  {r['name']} ({r['slug']}): {', '.join(r['flags'])}")
    if shift:
        print(f"\n-- MONTH_SHIFT ({len(shift)} partners): responses attributed to the "
              f"survey month but mostly submitted later (by design; explains TeamGPS "
              f"submission-date views) --")
        for r in shift[:40]:
            sh = [f for f in r["flags"] if f.startswith("MONTH_SHIFT")]
            print(f"  {r['name']} ({r['slug']}): {', '.join(sh)}")
    print(f"\nWrote {os.path.join(DATA, '_csat_audit.json')}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
