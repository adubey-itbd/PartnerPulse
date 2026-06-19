#!/usr/bin/env python
"""Build data/_overview.json — the data feed for the AI-Driven Operational Intelligence
dashboard (index.html).

index.html is fully data-driven: both the Executive Overview and Partner 360 views render
from data/_overview.json — there is no embedded partner array. This script rolls the
per-partner caches up into the fields those views need:

  - SIP open/closed + ticket, and portfolio Active-SIP totals
  - open / overdue / no-firm-date action-item counts (+ portfolio Open-Actions rollup)
  - real per-partner NPS (promoters − detractors) and portfolio NPS + CSAT coverage
  - CSAT split with sample size + low-n flag, negative share
  - call tone with an honesty flag (toneConfident=false ⇒ render "No calls"), last-call
    date + days-since + a >60-day "stale" flag
  - the Grok driver factors as `themes`, and the top driver text
  - a coverage window (service-review and feedback date ranges + snapshot date)

Everything is derived from the same caches partner.html uses (data/_index.json +
data/<slug>.json). It is the LAST step of the sync cycle (server.py SYNC_STEPS) and can
be re-run standalone after any data change:  python scripts/build_overview.py

This writes only the generated data/_overview.json — it never edits index.html.
"""
import json
import os
import re
import sys
from datetime import date, datetime

# Repo-root shim so the script runs from anywhere (matches the other scripts/).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# "Today" for overdue / stale / asOf logic. Defaults to the host clock (date.today())
# so unattended nightly runs stay correct; override with PARTNERPULSE_ASOF=YYYY-MM-DD
# (e.g. to pin against the future-dated sample data, or to reproduce a past run).
STALE_DAYS = 60          # a service-review call older than this is flagged stale
LOW_SAMPLE = 10          # CSAT/NPS responses below this get a low-confidence badge


def _parse_iso_date(s):
    """Return a date from an ISO date or datetime string, else None."""
    if not s or not isinstance(s, str):
        return None
    head = s.strip()[:10]
    try:
        return datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_today():
    override = (os.environ.get("PARTNERPULSE_ASOF") or "").strip()
    if override:
        parsed = _parse_iso_date(override)
        if parsed is not None:
            return parsed
        print(f"WARNING: ignoring invalid PARTNERPULSE_ASOF={override!r} "
              "(expected YYYY-MM-DD); using today's date")
    return date.today()


# "Today" for overdue / stale / asOf logic. Defaults to the host clock (date.today())
# so unattended nightly runs stay correct; override with PARTNERPULSE_ASOF=YYYY-MM-DD
# (e.g. to pin against the future-dated sample data, or to reproduce a past run).
TODAY = _resolve_today()


def _transcript_date(t):
    """Best-effort call date for a transcript. Titles/filenames embed the meeting date
    as YYYYMMDD (e.g. 'Logically ITBD Service Call-20260403_145929UTC') — the reliable
    source. Returns a date or None."""
    for key in ("title", "filename", "date"):
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", str(t.get(key) or ""))
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
            except ValueError:
                pass
    return None


def _tier(risk):
    return "High" if risk >= 45 else "Watch" if risk >= 25 else "Healthy"


def _derive_call_tone(trend, neg_share, risk, calls):
    """Same shape as index.html deriveCallTone, but honest about evidence.

    Returns (tone, confident). When there are no calls the tone is 'No calls' and
    callers should render it muted rather than as a confident verdict.
    """
    if calls <= 0:
        return "No calls", False
    if trend == "Declining" or neg_share >= 15 or risk >= 70:
        return "Negative", True
    if risk < 25 and neg_share <= 5 and trend != "Declining":
        return "Positive", True
    return "Mixed", True


def _reconcile_trend(ai_trend, risk, tone):
    """The Grok sentiment_trend can contradict the hard signals — it never emits
    "Declining" and sometimes tags a high-risk/negative account "Improving" (e.g.
    Proda 72/Negative). Reconcile so the displayed trend can never read better than
    risk + tone warrant."""
    if risk >= 45 and tone == "Negative":
        return "Declining"
    if risk >= 45 and ai_trend == "Improving":
        return "Stable"
    return ai_trend or "Stable"


def build_partner(slug, idx_row):
    path = os.path.join(DATA, f"{slug}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)

    client = d.get("client", {}) or {}
    ai = d.get("ai", {}) or {}

    # ---- CSAT: counts, positive share, and rated coverage ----
    cs = d.get("csat_stats", {}) or {}
    pos, neu, neg = cs.get("Positive", 0), cs.get("Neutral", 0), cs.get("Negative", 0)
    unrated = cs.get("Unrated", 0)
    rated = pos + neu + neg
    total_csat = rated + unrated
    pos_pct = round(pos / rated * 100) if rated else 0
    neg_share = round(neg / rated * 100) if rated else 0
    rated_pct = round(rated / total_csat * 100) if total_csat else 0

    # ---- NPS: real score = %promoters - %detractors ----
    nps = d.get("nps_stats", {}) or {}
    prom, pas, det = nps.get("Promoter", 0), nps.get("Passive", 0), nps.get("Detractor", 0)
    nps_resp = prom + pas + det
    nps_score = round((prom - det) / nps_resp * 100) if nps_resp else None

    # ---- SIPs ----
    sip_open = client.get("sip_open", 0) or 0
    sip_closed = client.get("sip_closed", 0) or 0
    sip_ticket = client.get("sip_ticket") or ""

    # ---- Action items: open / overdue / open-without-firm-date ----
    actions = ai.get("action_items") or d.get("action_items") or []
    open_n = overdue_n = open_nodate_n = completed_n = 0
    for a in actions:
        status = (a.get("status") or "").strip()
        if status == "Completed":
            completed_n += 1
            continue
        open_n += 1
        due = _parse_iso_date(a.get("due"))
        if due is None:
            open_nodate_n += 1
        elif due < TODAY:
            overdue_n += 1

    # ---- Calls: last call date, days since, staleness ----
    # "Last call" must reflect BOTH HaloPSA call-notes AND ingested transcripts — some
    # partners have transcripts but no Halo note (e.g. Liongard), and vice-versa. Take the
    # union of dates; count = unique call dates across both sources.
    calls = d.get("historical_calls") or []
    transcripts = d.get("transcripts") or []
    hc_dates = [dt for dt in (_parse_iso_date(c.get("date")) for c in calls) if dt]
    tr_dates = [dt for dt in (_transcript_date(t) for t in transcripts) if dt]
    call_dates = sorted(set(hc_dates) | set(tr_dates))
    calls_count = len(call_dates)
    last_call = call_dates[-1].isoformat() if call_dates else None
    days_since = (TODAY - call_dates[-1]).days if call_dates else None
    stale = bool(days_since is not None and days_since > STALE_DAYS)

    # Coverage window inputs (aggregated in main()): service-review call dates drive the
    # "service reviews" window; CSAT comment dates drive the "feedback" window. NPS is
    # excluded from the headline window because a handful of responses trail back to 2021.
    csat_dates = [dt for dt in (_parse_iso_date(c.get("date")) for c in (d.get("csat_comments") or [])) if dt]
    fb_count = len(d.get("csat_comments") or []) + len(d.get("nps_comments") or [])
    cov = {
        "callMin": min(call_dates) if call_dates else None,
        "callMax": max(call_dates) if call_dates else None,
        "csatMin": min(csat_dates) if csat_dates else None,
        "csatMax": max(csat_dates) if csat_dates else None,
        "callsN": calls_count, "fbN": fb_count,
    }

    # account_manager is occasionally a numeric team/client id rather than a name —
    # treat anything that isn't a real name string as Unassigned.
    am = client.get("account_manager")
    if not (isinstance(am, str) and am.strip()):
        am = idx_row.get("account_manager")
    if not (isinstance(am, str) and am.strip() and not am.strip().isdigit()):
        am = "Unassigned"

    # ---- Insufficient-data guard ----
    # A partner with no CSAT, no NPS, no calls and no transcripts has nothing behind its
    # score — reporting it as a confident "Healthy" is misleading. Flag it so the dashboard
    # can render an "Insufficient data" band, and exclude it from the avgRisk rollup.
    has_data = bool(rated or nps_resp or calls_count or transcripts)
    insufficient_data = not has_data

    risk = ai.get("risk_score", idx_row.get("risk_score", 0)) or 0
    ai_trend = ai.get("sentiment_trend") or idx_row.get("sentiment_trend") or "Stable"
    # Tone keeps using the raw AI trend (it's a hard signal feeding renewal risk);
    # the *displayed* trend is then reconciled against risk + tone below.
    tone, tone_confident = _derive_call_tone(ai_trend, neg_share, risk, calls_count)
    trend = _reconcile_trend(ai_trend, risk, tone)
    drivers = ai.get("drivers") or []
    top_driver = drivers[0].get("factor") if drivers else (idx_row.get("summary") or "")
    # themes == the Grok driver factors, first 4 — identical to index.html's embedded
    # array, so the Voice-of-partner section renders the same content as the live dashboard.
    themes = [dr.get("factor") for dr in drivers if dr.get("factor")][:4]

    return {
        # Halo Client Name is the single source of truth for the displayed account
        # name across all views (a Halo rename propagates automatically); fall back to
        # the index/roster label only when the cache has no client name.
        "name": client.get("name") or idx_row.get("name") or slug,
        "slug": slug,
        "churnRisk": risk,
        # deterministic single source of truth (was: LLM risk_band, mis-calibrated vs the
        # score). Zero-evidence partners get "Insufficient data" instead of a confident band.
        "riskBand": "Insufficient data" if insufficient_data else _tier(risk),
        "insufficientData": insufficient_data,
        "accountManager": am,
        "sentimentTrend": trend,
        "topDriver": top_driver,
        "themes": themes,
        "csat": {
            "positivePct": pos_pct, "positive": pos, "neutral": neu, "negative": neg,
            "unrated": unrated, "rated": rated, "total": total_csat,
            "ratedPct": rated_pct, "negShare": neg_share,
            "lowSample": rated < LOW_SAMPLE,
        },
        "nps": {
            "promoters": prom, "passives": pas, "detractors": det,
            "responses": nps_resp, "score": nps_score, "lowSample": nps_resp < LOW_SAMPLE,
        },
        "sip": {"open": sip_open, "closed": sip_closed, "ticket": sip_ticket},
        "actions": {
            "open": open_n, "overdue": overdue_n, "openNoDate": open_nodate_n,
            "completed": completed_n, "total": len(actions),
        },
        "calls": {
            "count": calls_count, "lastCall": last_call,
            "daysSince": days_since, "stale": stale,
        },
        "callTone": tone, "toneConfident": tone_confident,
        "_cov": cov,
    }


def main():
    with open(os.path.join(DATA, "_index.json"), encoding="utf-8") as fh:
        idx = json.load(fh)

    partners = []
    for row in idx.get("partners", []):
        p = build_partner(row["slug"], row)
        if p:
            partners.append(p)
    partners.sort(key=lambda p: p["churnRisk"], reverse=True)

    # ---- Optional demo-roster allowlist ----
    # If data/_demo_roster.json exists (a JSON list of slugs), the feed is filtered to
    # just those partners — so the dashboard shows a curated set without deleting any
    # caches. Sync-proof (a full rebuild can't resurrect hidden partners) and reversible
    # (delete the file to show everyone). Portfolio rollups below reflect the filtered set.
    roster_path = os.path.join(DATA, "_demo_roster.json")
    excluded_slugs = []
    if os.path.exists(roster_path):
        with open(roster_path, encoding="utf-8") as fh:
            allow = set(json.load(fh))
        before = len(partners)
        # Built partners the roster silently hides — surface them so genuinely real
        # partners (e.g. mission-technology) aren't dropped from the feed unnoticed.
        excluded = [p for p in partners if p["slug"] not in allow]
        excluded_slugs = sorted(p["slug"] for p in excluded)
        partners = [p for p in partners if p["slug"] in allow]
        missing = sorted(allow - {p["slug"] for p in partners})
        print(f"Demo roster active: {len(partners)} of {before} partners shown"
              + (f" (NOT FOUND: {missing})" if missing else ""))
        if excluded_slugs:
            print(f"WARNING: demo roster EXCLUDES {len(excluded_slugs)} built partner(s) "
                  f"from the feed: {excluded_slugs}")

    # ---- Coverage window: pull the private _cov off each partner and aggregate ----
    covs = [p.pop("_cov") for p in partners]
    def _mn(key):
        vals = [c[key] for c in covs if c[key]]
        return min(vals).isoformat() if vals else None
    def _mx(key):
        vals = [c[key] for c in covs if c[key]]
        return max(vals).isoformat() if vals else None
    coverage = {
        "asOf": TODAY.isoformat(),
        "callsStart": _mn("callMin"), "callsEnd": _mx("callMax"),
        "callsCount": sum(c["callsN"] for c in covs),
        "feedbackStart": _mn("csatMin"), "feedbackEnd": _mx("csatMax"),
        "feedbackCount": sum(c["fbN"] for c in covs),
    }

    n = len(partners)
    # ---- Portfolio rollups ----
    # avgRisk only averages partners that actually have evidence — a fleet of zero-data
    # "Healthy 0" scores would otherwise drag the portfolio average down dishonestly.
    scored = [p for p in partners if not p.get("insufficientData")]
    insufficient_n = n - len(scored)
    avg_risk = round(sum(p["churnRisk"] for p in scored) / len(scored)) if scored else 0
    high_risk = sum(1 for p in partners if p["churnRisk"] >= 45)
    active_sips = sum(p["sip"]["open"] for p in partners)
    partners_with_sip = sum(1 for p in partners if p["sip"]["open"] > 0)
    open_actions = sum(p["actions"]["open"] for p in partners)
    overdue_actions = sum(p["actions"]["overdue"] for p in partners)
    open_nodate = sum(p["actions"]["openNoDate"] for p in partners)

    # Aggregate NPS across the whole book (sum the raw response buckets).
    sum_prom = sum(p["nps"]["promoters"] for p in partners)
    sum_det = sum(p["nps"]["detractors"] for p in partners)
    sum_nps_resp = sum(p["nps"]["responses"] for p in partners)
    portfolio_nps = round((sum_prom - sum_det) / sum_nps_resp * 100) if sum_nps_resp else None

    # CSAT coverage = rated responses / all responses (proxy for response quality).
    sum_rated = sum(p["csat"]["rated"] for p in partners)
    sum_total = sum(p["csat"]["total"] for p in partners)
    csat_coverage = round(sum_rated / sum_total * 100) if sum_total else 0

    def _renewal_risk(p):
        score = (2 if p["churnRisk"] >= 45 else 1 if p["churnRisk"] >= 25 else 0)
        score += (2 if p["callTone"] == "Negative" else 1 if p["callTone"] == "Mixed" else 0)
        return "High" if score >= 2 else "Medium" if score == 1 else "Low"

    renewals_at_risk = sum(1 for p in partners if _renewal_risk(p) == "High")

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": TODAY.isoformat(),
        "excludedCount": len(excluded_slugs),
        "excludedSlugs": excluded_slugs,
        "coverage": coverage,
        "portfolio": {
            "tracked": n, "scored": len(scored), "insufficientData": insufficient_n,
            "avgRisk": avg_risk, "highRisk": high_risk,
            "activeSIPs": active_sips, "partnersWithSIP": partners_with_sip,
            "openActions": open_actions, "overdueActions": overdue_actions,
            "openNoDate": open_nodate, "renewalsAtRisk": renewals_at_risk,
            "portfolioNPS": portfolio_nps, "csatCoverage": csat_coverage,
            "npsResponses": sum_nps_resp,
        },
        "partners": partners,
    }
    out_path = os.path.join(DATA, "_overview.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}: {n} partners "
          f"({len(scored)} scored, {insufficient_n} insufficient-data), "
          f"asOf {TODAY.isoformat()}, "
          f"{active_sips} active SIPs across {partners_with_sip} partners, "
          f"{open_actions} open actions ({overdue_actions} overdue), "
          f"portfolio NPS {portfolio_nps}, CSAT coverage {csat_coverage}%")


if __name__ == "__main__":
    sys.exit(main())
