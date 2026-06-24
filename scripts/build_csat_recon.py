#!/usr/bin/env python
"""Build data/_csat_recon.json — the feed for the CSAT Reconciliation view.

The dashboard's third view (index.html, below Partner 360) reconciles, per
DES/MDE partner and per month, the monthly CSAT surveys ITBD *sent* against the
responses *received*:

  - SENT     = HaloPSA tickets of type 36/163/164 (the "DES CSAT Monthly" team);
               one ticket == one survey sent. The survey month is parsed from the
               ticket summary ("...For The Month of May"); the year from
               dateoccurred. See extract/halo.fetch_csat_tickets.
  - RECEIVED = TeamGPS CSAT responses (the per-partner data/<slug>.json
               csat_comments), joined to a sent ticket by ticket_id == Halo
               ticket id, and attributed to that sent ticket's month so sent and
               received line up in the same column.
  - Response rate    = received / sent.
  - Responded w/o match = in-window responses whose ticket_id matches no in-window
               sent ticket (e.g. a survey sent before the window, or a non-DES one).

Each row also carries the partner's Account Manager (client.accountmanagertech_name),
Regional Manager (client.regmanagertech_name), Site (client custom field
CFAccountSite) and Product (MDE) (custom field CFProductMDE — Self-Managed /
Co-Managed) so the view can re-group the same numbers by those dimensions
client-side.

The partner set mirrors the dashboard exactly: it is read from data/_overview.json
(already demo-allowlist filtered), and each partner's client_id + responses come
from its data/<slug>.json cache. Halo is hit per partner for the sent tickets +
client detail (AM/RM/Site). Window = Jan of the current year through the current
month (override "today" with PARTNERPULSE_ASOF=YYYY-MM-DD, same as build_overview).

Run AFTER build_overview.py, from the repo root:
    python scripts/build_csat_recon.py

Writes only data/_csat_recon.json — it never edits index.html. Published to
Firestore (meta/csatRecon) by scripts/upload_firebase_data.py.
"""
import json
import os
import re
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA = os.path.join(ROOT, "data")

from extract import halo  # noqa: E402

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTH_NUM = {m.lower(): i + 1 for i, m in enumerate(_MONTHS)}
_MONTH_NUM.update({
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
})
_MONTH_RE = re.compile(r"month of\s+([a-z]+)", re.I)


def _responded(c):
    """True if a CSAT row is a real response, not just a sent-but-unanswered survey.
    The TeamGPS /csat endpoint also returns sent surveys; an unanswered one has
    is_responded=false (empty rating/comment, null submitted_date) and must NOT count
    as 'received' (it would inflate the response rate and yield no CSAT). Prefer the
    is_responded flag; fall back to rating/date presence for caches built before that
    field was captured (see extract/teamgps.get_csat)."""
    r = c.get("is_responded")
    if isinstance(r, bool):
        return r
    return bool(str(c.get("rating") or "").strip()) or bool(c.get("date"))


def _clean_name(v):
    """A real person-name string, or None — Halo occasionally leaks a numeric id
    (or the -1 'unset' sentinel) in place of a manager name."""
    s = str(v or "").strip()
    return s if s and not re.fullmatch(r"-?\d+", s) else None


def _parse_iso_date(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_today():
    override = (os.environ.get("PARTNERPULSE_ASOF") or "").strip()
    if override:
        parsed = _parse_iso_date(override)
        if parsed is not None:
            return parsed
        print(f"WARNING: ignoring invalid PARTNERPULSE_ASOF={override!r}; using today")
    return date.today()


TODAY = _resolve_today()


def _ticket_month(summary: str, occurred):
    """(year, month_num) a sent survey ticket belongs to.

    Month comes from the summary ("...Month of May"); year from dateoccurred,
    corrected for the Dec->Jan wrap (a "Month of December" survey is raised in
    early January).

    A batch is raised (~day 23) with bare "Monthly Feedback for <name>" summaries
    and the "For The Month of <X>" text is stamped on later, so the CURRENT month's
    fresh batch is still month-less. We therefore fall back to the raise month ONLY
    for the current month; a month-less ticket in a settled prior month is a
    straggler/duplicate that Halo's "Month of …" report excludes, and counting it
    would inflate that month's sent total (e.g. Logically May read 30 vs Halo's 27)."""
    od = _parse_iso_date(occurred)
    m = _MONTH_RE.search(summary or "")
    mnum = _MONTH_NUM.get(m.group(1).lower()) if m else None
    if not od:
        return None
    if not mnum:
        if (od.year, od.month) == (TODAY.year, TODAY.month):
            return od.year, od.month
        return None
    year = od.year
    # The survey is raised in or shortly after its subject month; a big positive
    # gap means it wrapped a year boundary (Dec subject raised in Jan).
    if mnum - od.month > 6:
        year -= 1
    elif od.month - mnum > 6:
        year += 1
    return year, mnum


def _window_keys():
    """Ordered month columns: Jan of the current year .. current month."""
    return [{"key": f"{TODAY.year}-{mn:02d}", "label": f"{_MONTHS[mn-1]} {TODAY.year}"}
            for mn in range(1, TODAY.month + 1)]


# Survey tickets ITBD files under the "wrong" Halo client, reassigned by site/type.
# PEI's NDA monthly-engineer CSAT (ticket type 163, "DES Monthly Engineer CSAT - NDA")
# is raised under the shared "Dataprise" client (57) but belongs to PEI (137, the NDA
# account). Key: (source_client_id, ticket_type_id) -> target_client_id.
_TICKET_REASSIGN = {(57, 163): 137}


def _claimed_tickets(client_id, fetch):
    """Sent CSAT tickets this client OWNS after applying _TICKET_REASSIGN: drop tickets
    reassigned away to another client, and add tickets reassigned in from another. `fetch`
    is a memoised halo.fetch_csat_tickets so a shared source client isn't pulled twice."""
    out = [t for t in fetch(client_id)
           if _TICKET_REASSIGN.get((client_id, t.get("tickettype_id")), client_id) == client_id]
    for (src, typ), tgt in _TICKET_REASSIGN.items():
        if tgt == client_id and src != client_id:
            out += [t for t in fetch(src) if t.get("tickettype_id") == typ]
    return out


def main():
    overview_path = os.path.join(DATA, "_overview.json")
    if not os.path.exists(overview_path):
        sys.exit(f"missing {overview_path} - run scripts/build_overview.py first")
    with open(overview_path, encoding="utf-8") as fh:
        overview = json.load(fh)

    months = _window_keys()
    month_keys = [m["key"] for m in months]
    win_keys = set(month_keys)

    # Memoised Halo sent-ticket fetch — a reassignment source (e.g. client 57) is
    # otherwise pulled once per partner that claims tickets from it.
    _ticket_cache = {}
    def _fetch(cid):
        if cid not in _ticket_cache:
            try:
                _ticket_cache[cid] = halo.fetch_csat_tickets(cid)
            except Exception as exc:  # one client's Halo blip must not abort the build
                print(f"  WARN: Halo CSAT tickets failed for client {cid}: {exc}", file=sys.stderr)
                _ticket_cache[cid] = []
        return _ticket_cache[cid]

    # ---- Pass 1: per partner — AM/RM/Site + SENT cells; build a global ticket-OWNER
    #      map (ticket_id -> (slug, month_key)) applying _TICKET_REASSIGN. ----
    partners_meta = []          # ordered: {slug, name, am, rm, site, cells}
    owner = {}                  # str(ticket_id) -> (slug, month_key), in-window only
    for p in overview.get("partners", []):
        slug = p.get("slug")
        name = p.get("name") or slug
        blob_path = os.path.join(DATA, f"{slug}.json")
        if not slug or not os.path.exists(blob_path):
            continue
        with open(blob_path, encoding="utf-8") as fh:
            blob = json.load(fh)
        client = blob.get("client", {}) or {}
        client_id = client.get("id")

        am = rm = site = product = None
        cells = {k: {"sent": 0, "received": 0, "pos": 0, "rated": 0} for k in month_keys}
        if client_id:
            try:
                detail = halo.get_client(client_id)
                cf = halo.parse_custom_fields(detail)
                am = _clean_name(detail.get("accountmanagertech_name"))
                rm = _clean_name(detail.get("regmanagertech_name"))
                # CFAccountSite is "NDA"/"CDG"/"DL"/"PH"; an unset field comes back as
                # the sentinel -1 (and AM/RM ids occasionally leak in) — drop anything
                # that isn't a real alphabetic site code.
                site_raw = str(cf.get("CFAccountSite") or "").strip()
                site = site_raw if site_raw and not re.fullmatch(r"-?\d+", site_raw) else None
                # CFProductMDE is "Self-Managed"/"Co-Managed" (RAG tab "ProductMDE");
                # same sentinel/leak guard — keep only a real text label.
                product_raw = str(cf.get("CFProductMDE") or "").strip()
                product = product_raw if product_raw and not re.fullmatch(r"-?\d+", product_raw) else None
            except Exception as exc:
                print(f"  WARN: Halo client detail failed for {slug} ({client_id}): {exc}",
                      file=sys.stderr)
            for t in _claimed_tickets(client_id, _fetch):
                ym = _ticket_month(t.get("summary"), t.get("dateoccurred"))
                if not ym:
                    continue
                key = f"{ym[0]}-{ym[1]:02d}"
                if key not in win_keys:
                    continue
                cells[key]["sent"] += 1
                owner[str(t.get("id"))] = (slug, key)
        partners_meta.append({"slug": slug, "name": name, "am": am, "rm": rm,
                              "site": site, "product": product, "cells": cells})

    # ---- Pass 2: RECEIVED (global). Attribute each response to whoever OWNS its sent
    #      ticket (per `owner`) — regardless of which partner's blob carries it — so a
    #      reassigned survey's response lands on the right partner. Count DISTINCT
    #      answered tickets per cell (a survey may have >1 response) so received <= sent;
    #      tally pos/rated for CSAT%. Dedup responses by id across blobs. ----
    by_slug = {m["slug"]: m for m in partners_meta}
    answered = {}               # (slug, month_key) -> set(ticket_id)
    seen_resp = set()
    responded_no_match = 0
    for p in overview.get("partners", []):
        slug = p.get("slug")
        blob_path = os.path.join(DATA, f"{slug}.json")
        if not slug or not os.path.exists(blob_path):
            continue
        with open(blob_path, encoding="utf-8") as fh:
            blob = json.load(fh)
        for c in blob.get("csat_comments", []) or []:
            if not _responded(c):        # skip sent-but-unanswered surveys
                continue
            rid = c.get("id")
            if rid in seen_resp:         # same response can appear in >1 blob (shared company)
                continue
            seen_resp.add(rid)
            tid = str(c.get("ticket_id") or "")
            own = owner.get(tid)
            if not own:
                d = _parse_iso_date(c.get("date"))
                if d and d.year == TODAY.year and d.month <= TODAY.month:
                    responded_no_match += 1
                continue
            o_slug, key = own
            answered.setdefault((o_slug, key), set()).add(tid)
            cell = by_slug[o_slug]["cells"][key]
            rt = str(c.get("rating") or "").capitalize()
            if rt in ("Positive", "Neutral", "Negative"):
                cell["rated"] += 1
                if rt == "Positive":
                    cell["pos"] += 1
    for (o_slug, key), tids in answered.items():
        by_slug[o_slug]["cells"][key]["received"] = len(tids)

    # ---- Build rows + portfolio totals ----
    rows = []
    total_sent = total_received = 0
    for m in partners_meta:
        cells = m["cells"]
        p_sent = sum(c["sent"] for c in cells.values())
        p_recv = sum(c["received"] for c in cells.values())
        p_pos = sum(c["pos"] for c in cells.values())
        p_rated = sum(c["rated"] for c in cells.values())
        total_sent += p_sent
        total_received += p_recv
        rows.append({
            "partner": m["name"],
            "slug": m["slug"],
            "accountManager": m["am"] or "Unassigned",
            "regionalManager": m["rm"] or "Unassigned",
            "site": m["site"] or "—",
            "product": m["product"] or "—",
            "months": cells,
            "total": {"sent": p_sent, "received": p_recv, "pos": p_pos, "rated": p_rated},
        })

    by_month = []
    for k, m in zip(month_keys, months):
        s = sum(r["months"][k]["sent"] for r in rows)
        rcv = sum(r["months"][k]["received"] for r in rows)
        pos = sum(r["months"][k]["pos"] for r in rows)
        rated = sum(r["months"][k]["rated"] for r in rows)
        by_month.append({
            "key": k, "label": m["label"], "sent": s, "received": rcv,
            "pos": pos, "rated": rated,
            "rate": round(rcv / s * 100, 1) if s else None,           # response rate
            "csat": round(pos / rated * 100, 1) if rated else None,   # satisfaction %
        })

    partners_with_sent = sum(1 for r in rows if r["total"]["sent"] > 0)
    total_pos = sum(r["total"]["pos"] for r in rows)
    total_rated = sum(r["total"]["rated"] for r in rows)
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": TODAY.isoformat(),
        "ticketTypes": sorted(halo.CSAT_TICKET_TYPE_IDS),
        "period": {"start": month_keys[0], "end": month_keys[-1], "months": months},
        "totals": {
            "partners": len(rows),
            "partnersWithSent": partners_with_sent,
            "sent": total_sent,
            "received": total_received,
            "responseRate": round(total_received / total_sent * 100, 1) if total_sent else None,
            "positive": total_pos,
            "rated": total_rated,
            "csatPct": round(total_pos / total_rated * 100, 1) if total_rated else None,
            "respondedNoMatch": responded_no_match,
        },
        "byMonth": by_month,
        "rows": rows,
    }
    out_path = os.path.join(DATA, "_csat_recon.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    rate = out["totals"]["responseRate"]
    csatpct = out["totals"]["csatPct"]
    print(f"Wrote {out_path}: {len(rows)} partners, {total_sent} sent, "
          f"{total_received} received ({rate}% response rate), "
          f"CSAT {csatpct}% positive ({total_pos}/{total_rated}), "
          f"{responded_no_match} responded w/o sent match, "
          f"window {month_keys[0]}..{month_keys[-1]}")


if __name__ == "__main__":
    sys.exit(main())
