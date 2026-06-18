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
Regional Manager (client.regmanagertech_name) and Site (client custom field
CFAccountSite) so the view can re-group the same numbers by those dimensions
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
    early January). Falls back to dateoccurred's own month when the summary has
    no parseable month."""
    od = _parse_iso_date(occurred)
    m = _MONTH_RE.search(summary or "")
    mnum = _MONTH_NUM.get(m.group(1).lower()) if m else None
    if not od:
        return None
    if not mnum:
        return od.year, od.month
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


def main():
    overview_path = os.path.join(DATA, "_overview.json")
    if not os.path.exists(overview_path):
        sys.exit(f"missing {overview_path} - run scripts/build_overview.py first")
    with open(overview_path, encoding="utf-8") as fh:
        overview = json.load(fh)

    months = _window_keys()
    month_keys = [m["key"] for m in months]
    win_keys = set(month_keys)

    rows = []
    # ticket_id (str) -> month_key, for every in-window sent ticket across the book
    # (used to flag responses that match no sent survey).
    sent_index = {}
    total_sent = total_received = 0

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

        am = rm = site = None
        sent_tickets = []
        if client_id:
            # Two independent Halo calls — a failure in one must not void the other.
            # Some Halo fields come back as ints/ids, so coerce before stripping.
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
            except Exception as exc:
                print(f"  WARN: Halo client detail failed for {slug} ({client_id}): {exc}",
                      file=sys.stderr)
            try:
                sent_tickets = halo.fetch_csat_tickets(client_id)
            except Exception as exc:  # one partner's Halo blip must not abort the build
                print(f"  WARN: Halo CSAT tickets failed for {slug} ({client_id}): {exc}",
                      file=sys.stderr)

        # ---- SENT: window + bucket by month; index ids for the received join ----
        # Per cell: sent, received (distinct answered tickets), and the rating tally
        # of the matched responses (pos / rated) for the CSAT satisfaction score.
        cells = {k: {"sent": 0, "received": 0, "pos": 0, "rated": 0} for k in month_keys}
        partner_sent_ids = {}     # str(ticket_id) -> month_key
        for t in sent_tickets:
            ym = _ticket_month(t.get("summary"), t.get("dateoccurred"))
            if not ym:
                continue
            key = f"{ym[0]}-{ym[1]:02d}"
            if key not in win_keys:
                continue
            cells[key]["sent"] += 1
            tid = str(t.get("id"))
            partner_sent_ids[tid] = key
            sent_index[tid] = key

        # ---- RECEIVED: a sent survey is "received" once it gets ANY response.
        #      Count DISTINCT answered tickets (a single survey occasionally has >1
        #      TeamGPS response record), so received <= sent and the rate <= 100%. ----
        answered = {k: set() for k in month_keys}
        for c in blob.get("csat_comments", []) or []:
            tid = str(c.get("ticket_id") or "")
            key = partner_sent_ids.get(tid)
            if not key:
                continue
            answered[key].add(tid)
            rt = str(c.get("rating") or "").capitalize()
            if rt in ("Positive", "Neutral", "Negative"):
                cells[key]["rated"] += 1
                if rt == "Positive":
                    cells[key]["pos"] += 1
        for k in month_keys:
            cells[k]["received"] = len(answered[k])

        p_sent = sum(c["sent"] for c in cells.values())
        p_recv = sum(c["received"] for c in cells.values())
        p_pos = sum(c["pos"] for c in cells.values())
        p_rated = sum(c["rated"] for c in cells.values())
        total_sent += p_sent
        total_received += p_recv

        rows.append({
            "partner": name,
            "slug": slug,
            "accountManager": am or "Unassigned",
            "regionalManager": rm or "Unassigned",
            "site": site or "—",
            "months": cells,
            "total": {"sent": p_sent, "received": p_recv, "pos": p_pos, "rated": p_rated},
        })

    # ---- Responded-without-sent-match (portfolio): in-window responses whose
    #      ticket_id matches no in-window sent survey across the whole book. ----
    responded_no_match = 0
    for p in overview.get("partners", []):
        slug = p.get("slug")
        blob_path = os.path.join(DATA, f"{slug}.json")
        if not slug or not os.path.exists(blob_path):
            continue
        with open(blob_path, encoding="utf-8") as fh:
            blob = json.load(fh)
        for c in blob.get("csat_comments", []) or []:
            tid = str(c.get("ticket_id") or "")
            if tid in sent_index:
                continue
            d = _parse_iso_date(c.get("date"))
            if d and d.year == TODAY.year and d.month <= TODAY.month:
                responded_no_match += 1

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
