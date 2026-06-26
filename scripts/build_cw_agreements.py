#!/usr/bin/env python
"""Build data/_cw_agreements.json — the feed for the Renewal Risk view.

Source: a STATIC ConnectWise agreement export dropped in the repo root as
`CW Agreements*.xlsx` (e.g. "CW Agreements June 2026.xlsx"). One row = one
agreement (engineer). Columns used: D Company Name (partner), F Amount,
G Billing Cycle, H Date Start, I Date End (renewal), B Agreement Type.

This view REPLACES the old HaloPSA-contract renewal facts: CW agreement end-dates
are the source of truth for renewal dates + MRR (Halo still drives churn / RAG /
tone / CSAT / NPS / SIP everywhere else). Business rules (signed off 2026-06-26):

  - INCLUDE Agreement Type in {Co-Managed, Self Managed, MSP Dedicated Engineer};
    drop IMS, Team GPS (all), Project, Managed IT, Support By Design Complete.
  - MRR (col F) normalized to monthly: Monthly = Amount, Annual = Amount/12,
    One Time / blank billing = 0 (not recurring). Summed per partner. ARR = MRR*12.
  - Match Company -> a DASHBOARD partner only (never create new partners): exact
    normalized name + the signed-off alias map (_ALIAS). Non-dashboard companies
    are ignored.
  - At Risk = an agreement renewing within 90 days AND the partner is unhealthy
    (churn >= 45 OR RAG Red OR confident-Negative call tone OR Declining trend).
    Watch = renewing <= 90d (healthy) OR renewing 91-180d (unhealthy). Else On Track.
    Partner tier = worst agreement tier. MRR-at-risk = sum of At-Risk agreement MRR.
  - Blank end-dates are KEPT and flagged (excluded from quarterly + at-risk timing).

Reads data/_overview.json (partner set + churn/tone/trend) and the per-partner
data/<slug>.json caches (client.rag). Window "today" overridable with
PARTNERPULSE_ASOF=YYYY-MM-DD (same as build_overview / build_csat_recon).

Run AFTER build_overview.py, from the repo root:
    python scripts/build_cw_agreements.py

Writes only data/_cw_agreements.json. Published to Firestore (meta/cwAgreements)
by scripts/upload_firebase_data.py.
"""
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

try:
    import openpyxl
except ImportError:
    sys.exit("openpyxl is required: pip install openpyxl")

_INCLUDE_TYPES = {"Co-Managed", "Self Managed", "MSP Dedicated Engineer"}
_AT_RISK_DAYS = 90
_WATCH_DAYS = 180

# Signed-off alias map: CW Company Name -> dashboard partner display name. Covers
# naming-convention mismatches the normalized exact match misses (2026-06-26).
_ALIAS = {
    "Dataprise": "PEI (Dataprise)",
    "Redhelm": "RedHelm -1Path",
    "ETech 7 Inc": "Etech7",
    "Spidernet Technical Consulting": "Spidernet Consulting",
    "Vitis Technologies (ProSource)": "Vitis Tech",
    "Omega Systems Consultants Inc": "Omega Systems Corp",
}

# Column indices (0-based) in the export.
_C_TYPE, _C_COMPANY, _C_AMOUNT, _C_BILLING, _C_START, _C_END, _C_NAME, _C_EMP = 1, 3, 5, 6, 7, 8, 2, 12


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _resolve_today():
    override = (os.environ.get("PARTNERPULSE_ASOF") or "").strip()
    if override:
        try:
            return datetime.strptime(override[:10], "%Y-%m-%d").date()
        except ValueError:
            print(f"WARNING: ignoring invalid PARTNERPULSE_ASOF={override!r}; using today")
    return date.today()


TODAY = _resolve_today()


def _mrr(amount, billing):
    a = amount if isinstance(amount, (int, float)) else 0.0
    b = (billing or "").strip().lower()
    if b == "monthly":
        return float(a)
    if b == "annual":
        return float(a) / 12.0
    return 0.0  # One Time / blank -> not recurring


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _quarter_key(d):
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _timing_factor(days_next):
    """0..1 renewal-proximity weight. ~0 when nothing is renewing soon, so the score
    is 'only meaningful when a renewal is upcoming' (signed off 2026-06-26)."""
    if days_next is None or days_next < 0:
        return 0.0
    if days_next <= 30:
        return 1.0
    if days_next <= 60:
        return 0.85
    if days_next <= 90:
        return 0.70
    if days_next <= 180:
        return 0.45
    if days_next <= 365:
        return 0.20
    return 0.05


def _health_factor(health):
    """0..1 account-health weight: base = churn/100, floored to 0.75 on any hard
    negative signal (RAG Red / confident-Negative tone / Declining trend)."""
    h = (health.get("churnRisk") or 0) / 100.0
    hard = (str(health.get("rag") or "").strip().lower() == "red"
            or (health.get("callTone") == "Negative" and health.get("toneConfident"))
            or health.get("sentimentTrend") == "Declining")
    if hard:
        h = max(h, 0.75)
    return max(0.0, min(1.0, h))


# "Why at risk" reason engine — only signals we can compute today (signed off 2026-06-26).
# GP/margin (no cost data), ticket-trend (not ingested) and manual flags are intentionally
# absent; QBR uses a last-engagement proxy until it becomes a Halo ticket; escalation = SIP.
_NO_ENGAGE_DAYS = 90
_LOW_CSAT_PCT = 80


def _risk_reasons(row):
    """Ordered list of {code,label,severity} explaining a partner's renewal risk.
    severity: high | med | action (a recommended next step)."""
    h, out = row["health"], []
    d = row.get("daysToNextRenewal")
    if d is not None and d <= _AT_RISK_DAYS:
        out.append({"code": "renewal", "label": f"Renewal in {d} days", "severity": "high" if d <= 30 else "med"})
    if str(h.get("rag") or "").strip().lower() == "red":
        out.append({"code": "rag", "label": "Account RAG is Red", "severity": "high"})
    if (h.get("churnRisk") or 0) >= 45:
        out.append({"code": "churn", "label": f"High churn risk ({h.get('churnRisk')})", "severity": "high"})
    if h.get("sentimentTrend") == "Declining":
        out.append({"code": "trend", "label": "Sentiment trend declining", "severity": "med"})
    if h.get("callTone") == "Negative" and h.get("toneConfident"):
        out.append({"code": "tone", "label": "Negative call tone", "severity": "med"})
    if (h.get("csatRated") or 0) >= 3 and h.get("csatPos") is not None and h["csatPos"] < _LOW_CSAT_PCT:
        out.append({"code": "csat", "label": f"Low CSAT ({h['csatPos']}% positive)", "severity": "med"})
    ds = h.get("daysSinceCall")
    if ds is None or ds > _NO_ENGAGE_DAYS:
        out.append({"code": "engagement",
                    "label": "No QBR/engagement in 90+ days" if ds is None else f"No engagement in {ds} days",
                    "severity": "med"})
    if row["riskTier"] == "At Risk" and (h.get("sipOpen") or 0) == 0:
        out.append({"code": "no_sip", "label": "No open SIP — recommend opening one", "severity": "action"})
    return out


def _recommendation(row):
    """A concrete next step (or None) for an at-risk/watch partner — derived from the
    same signals as the reasons, ordered most-urgent first."""
    if row["riskTier"] == "On Track" and row["atRiskCount"] == 0:
        return None
    h, d, recs = row["health"], row.get("daysToNextRenewal"), []
    if row["riskTier"] == "At Risk" and (h.get("sipOpen") or 0) == 0:
        recs.append("Open a SIP and assign an owner")
    if d is not None and d <= 30:
        recs.append("Confirm renewal with the partner before the end date")
    if str(h.get("rag") or "").strip().lower() == "red" or (h.get("churnRisk") or 0) >= 70:
        recs.append("Escalate to an exec sponsor for a save-play")
    ds = h.get("daysSinceCall")
    if ds is None or ds > _NO_ENGAGE_DAYS:
        recs.append("Schedule a QBR / check-in")
    if not recs:
        recs.append("Schedule a renewal review")
    return "; ".join(recs[:2])


def _find_source():
    hits = sorted(glob.glob(os.path.join(ROOT, "CW Agreements*.xlsx")))
    if not hits:
        sys.exit("no 'CW Agreements*.xlsx' found in repo root")
    return hits[-1]  # latest by name


def main():
    overview_path = os.path.join(DATA, "_overview.json")
    if not os.path.exists(overview_path):
        sys.exit(f"missing {overview_path} - run scripts/build_overview.py first")
    with open(overview_path, encoding="utf-8") as fh:
        overview = json.load(fh)

    # Dashboard partner index + health. rag is not on the overview row, so pull it
    # from each partner's blob (client.rag).
    by_norm = {}
    for p in overview.get("partners", []):
        rag = None
        blob_path = os.path.join(DATA, f"{p.get('slug')}.json")
        if os.path.exists(blob_path):
            try:
                with open(blob_path, encoding="utf-8") as fh:
                    rag = (json.load(fh).get("client", {}) or {}).get("rag")
            except Exception:
                pass
        csat = p.get("csat") or {}
        calls = p.get("calls") or {}
        sipd = p.get("sip") or {}
        by_norm[_norm(p.get("name"))] = {
            "name": p.get("name"), "slug": p.get("slug"),
            "churnRisk": p.get("churnRisk"), "callTone": p.get("callTone"),
            "toneConfident": p.get("toneConfident"), "sentimentTrend": p.get("sentimentTrend"),
            "rag": rag,
            "csatPos": csat.get("positivePct"), "csatRated": csat.get("rated") or 0,
            "csatLowSample": bool(csat.get("lowSample")),
            "daysSinceCall": calls.get("daysSince"), "sipOpen": sipd.get("open") or 0,
        }
    alias_norm = {_norm(k): v for k, v in _ALIAS.items()}

    def _match(company):
        n = _norm(company)
        if n in by_norm:
            return by_norm[n]
        if n in alias_norm:
            return by_norm.get(_norm(alias_norm[n]))
        return None

    def _unhealthy(h):
        if (h.get("churnRisk") or 0) >= 45:
            return True
        if str(h.get("rag") or "").strip().lower() == "red":
            return True
        if h.get("callTone") == "Negative" and h.get("toneConfident"):
            return True
        if h.get("sentimentTrend") == "Declining":
            return True
        return False

    def _agr_tier(days_out, unhealthy):
        if days_out is None:
            return "On Track"          # blank end-date: no timing -> flagged separately
        if days_out <= _AT_RISK_DAYS and unhealthy:
            return "At Risk"
        if days_out <= _AT_RISK_DAYS:
            return "Watch"             # renewing soon but healthy
        if days_out <= _WATCH_DAYS and unhealthy:
            return "Watch"
        return "On Track"

    src = _find_source()
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    ws = wb.worksheets[0]

    parts = {}              # slug -> partner record
    ignored_companies = set()
    excluded_type = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[_C_COMPANY] is None:
            continue
        typ = (row[_C_TYPE] or "").strip()
        if typ not in _INCLUDE_TYPES:
            excluded_type += 1
            continue
        h = _match(row[_C_COMPANY])
        if not h:
            ignored_companies.add(str(row[_C_COMPANY]).strip())
            continue
        slug = h["slug"]
        end = _as_date(row[_C_END])
        days_out = (end - TODAY).days if end else None
        unhealthy = _unhealthy(h)
        tier = _agr_tier(days_out, unhealthy)
        mrr = _mrr(row[_C_AMOUNT], row[_C_BILLING])
        agr = {
            "name": str(row[_C_NAME] or "").strip(),
            "engineer": str(row[_C_EMP] or "").strip(),
            "type": typ,
            "mrr": round(mrr, 2),
            "billing": (row[_C_BILLING] or "").strip(),
            "start": _as_date(row[_C_START]).isoformat() if _as_date(row[_C_START]) else None,
            "end": end.isoformat() if end else None,
            "daysOut": days_out,
            "tier": tier,
            "blankEnd": end is None,
        }
        rec = parts.setdefault(slug, {
            "partner": h["name"], "slug": slug,
            "health": {"churnRisk": h["churnRisk"], "rag": h["rag"],
                       "callTone": h["callTone"], "toneConfident": h["toneConfident"],
                       "sentimentTrend": h["sentimentTrend"], "unhealthy": unhealthy,
                       "csatPos": h["csatPos"], "csatRated": h["csatRated"],
                       "daysSinceCall": h["daysSinceCall"], "sipOpen": h["sipOpen"]},
            "agreements": [],
        })
        rec["agreements"].append(agr)

    # ---- Per-partner rollups ----
    _TIER_RANK = {"At Risk": 3, "Watch": 2, "On Track": 1}
    rows = []
    for rec in parts.values():
        ags = rec["agreements"]
        ends = [a["end"] for a in ags if a["end"]]
        mrr = sum(a["mrr"] for a in ags)
        at_risk = [a for a in ags if a["tier"] == "At Risk"]
        worst = max((a["tier"] for a in ags), key=lambda t: _TIER_RANK[t], default="On Track")
        ags.sort(key=lambda a: (a["end"] or "9999-12-31"))
        ups = [a["daysOut"] for a in ags if a["daysOut"] is not None and a["daysOut"] >= 0]
        rows.append({
            **rec,
            "agreementCount": len(ags),
            "mrr": round(mrr, 2),
            "arr": round(mrr * 12, 2),
            "earliestRenewal": min(ends) if ends else None,
            "latestRenewal": max(ends) if ends else None,
            "daysToNextRenewal": min(ups) if ups else None,
            "blankEndCount": sum(1 for a in ags if a["blankEnd"]),
            "atRiskCount": len(at_risk),
            "mrrAtRisk": round(sum(a["mrr"] for a in at_risk), 2),
            "riskTier": worst,
        })

    # ---- Renewal Risk score (0-100, sits ALONGSIDE the Grok churn score): a weighted
    #      blend of renewal timing (40%) + account health (40%) + MRR exposure (20%).
    #      Exposure is the partner's MRR relative to the largest partner (0..1). ----
    max_mrr = max((r["mrr"] for r in rows), default=0) or 1.0
    for r in rows:
        T = _timing_factor(r["daysToNextRenewal"])
        H = _health_factor(r["health"])
        E = min(1.0, r["mrr"] / max_mrr)
        score = round(100 * (0.40 * T + 0.40 * H + 0.20 * E))
        r["renewalRiskScore"] = score
        r["renewalRiskBand"] = "High" if score >= 66 else "Medium" if score >= 33 else "Low"
        r["riskReasons"] = _risk_reasons(r)
        r["recommendation"] = _recommendation(r)
    rows.sort(key=lambda r: (_TIER_RANK[r["riskTier"]], r["mrrAtRisk"], r["mrr"]), reverse=True)

    # ---- Quarterly forecast (by end-date calendar quarter; blanks excluded) ----
    q = {}
    for r in rows:
        for a in r["agreements"]:
            if not a["end"]:
                continue
            d = datetime.strptime(a["end"], "%Y-%m-%d").date()
            key = _quarter_key(d)
            cell = q.setdefault(key, {"key": key, "agreements": 0, "mrr": 0.0, "partners": set()})
            cell["agreements"] += 1
            cell["mrr"] += a["mrr"]
            cell["partners"].add(r["slug"])
    by_quarter = []
    for key in sorted(q):
        c = q[key]
        yr, qn = key.split("-Q")
        by_quarter.append({"key": key, "label": f"Q{qn} {yr}", "agreements": c["agreements"],
                           "mrr": round(c["mrr"], 2), "partners": len(c["partners"])})

    total_mrr = sum(r["mrr"] for r in rows)

    def _mrr_within(days):
        return round(sum(a["mrr"] for r in rows for a in r["agreements"]
                         if a["daysOut"] is not None and 0 <= a["daysOut"] <= days), 2)
    renew30, renew60, renew90 = _mrr_within(30), _mrr_within(60), _mrr_within(90)

    # ---- Portfolio "Renewal insights" (deterministic facts + a 'why it matters' line) ----
    def _near90(r):
        return round(sum(a["mrr"] for a in r["agreements"]
                         if a["daysOut"] is not None and 0 <= a["daysOut"] <= 90), 2)

    def _cnt90(r):
        return sum(1 for a in r["agreements"] if a["daysOut"] is not None and 0 <= a["daysOut"] <= 90)

    _money = lambda n: "$" + format(round(n), ",")
    insights = []
    by_near = sorted(rows, key=_near90, reverse=True)
    top_exp = [r for r in by_near if _near90(r) > 0][:3]
    if top_exp:
        insights.append({
            "code": "exposure", "severity": "high",
            "title": f"{_money(renew90)}/mo renews in the next 90 days",
            "detail": "Top exposure: " + ", ".join(f"{r['partner']} ({_money(_near90(r))})" for r in top_exp),
            "why": "These contracts are the nearest revenue to lock — prioritise renewal conversations now.",
        })
    at_risk_rows = [r for r in rows if r["atRiskCount"] > 0]
    if at_risk_rows:
        insights.append({
            "code": "atrisk", "severity": "high",
            "title": f"{_money(sum(r['mrrAtRisk'] for r in at_risk_rows))}/mo at risk across {len(at_risk_rows)} partner(s)",
            "detail": "Worst: " + ", ".join(f"{r['partner']} ({_money(r['mrrAtRisk'])})" for r in
                                             sorted(at_risk_rows, key=lambda r: r['mrrAtRisk'], reverse=True)[:3]),
            "why": "Near-term renewals on unhealthy accounts — the revenue most likely to churn without intervention.",
        })
    top5 = sorted(rows, key=lambda r: r["mrr"], reverse=True)[:5]
    top5_share = round(sum(r["mrr"] for r in top5) / total_mrr * 100) if total_mrr else 0
    over10 = [r for r in rows if total_mrr and r["mrr"] / total_mrr >= 0.10]
    insights.append({
        "code": "concentration", "severity": "med" if top5_share >= 35 else "info",
        "title": f"Top-5 partners = {top5_share}% of MRR",
        "detail": (", ".join(f"{r['partner']} ({_money(r['mrr'])})" for r in top5)
                   + (f" · {len(over10)} partner(s) over 10%" if over10 else "")),
        "why": "Revenue concentration: losing a top account has outsized impact — keep these closest.",
    })
    clusters = [r for r in by_near if _cnt90(r) >= 3][:3]
    if clusters:
        insights.append({
            "code": "cluster", "severity": "med",
            "title": "Partners with several agreements renewing together",
            "detail": ", ".join(f"{r['partner']} ({_cnt90(r)} agreements, {_money(_near90(r))})" for r in clusters),
            "why": "Multiple agreements renewing at once concentrate both risk and the renewal workload on one date.",
        })
    hv = [r for r in rows if r["mrr"] >= 20000
          and (r["health"].get("daysSinceCall") is None or r["health"]["daysSinceCall"] > _NO_ENGAGE_DAYS)]
    if hv:
        insights.append({
            "code": "engagement", "severity": "med",
            "title": f"{len(hv)} high-value partner(s) with no recent engagement",
            "detail": ", ".join(f"{r['partner']} ({_money(r['mrr'])})" for r in
                                sorted(hv, key=lambda r: r["mrr"], reverse=True)[:4]),
            "why": "Large MRR with no QBR/call in 90+ days — silent accounts renew worse; schedule a check-in.",
        })
    actions = sorted(at_risk_rows, key=lambda r: r["mrrAtRisk"], reverse=True)[:5]
    if actions:
        insights.append({
            "code": "actions", "severity": "action",
            "title": "Recommended priority actions",
            "detail": "; ".join(
                f"{r['partner']} — " + ("open a SIP" if (r['health'].get('sipOpen') or 0) == 0 else "renewal review")
                + f" ({_money(r['mrrAtRisk'])} at risk)" for r in actions),
            "why": "Highest-dollar at-risk renewals first; a missing SIP is the first concrete step.",
        })

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": TODAY.isoformat(),
        "source": os.path.basename(src),
        "includedTypes": sorted(_INCLUDE_TYPES),
        "atRisk": {"windowDays": _AT_RISK_DAYS,
                   "definition": "renewing <=90d AND (churn>=45 OR RAG Red OR confident-Negative tone OR Declining trend)"},
        "totals": {
            "partners": len(rows),
            "agreements": sum(r["agreementCount"] for r in rows),
            "mrr": round(total_mrr, 2),
            "arr": round(total_mrr * 12, 2),
            "partnersAtRisk": sum(1 for r in rows if r["atRiskCount"] > 0),
            "agreementsAtRisk": sum(r["atRiskCount"] for r in rows),
            "mrrAtRisk": round(sum(r["mrrAtRisk"] for r in rows), 2),
            "mrrRenew30": renew30, "mrrRenew60": renew60, "mrrRenew90": renew90,
            "blankEndCount": sum(r["blankEndCount"] for r in rows),
            "ignoredCompanies": len(ignored_companies),
            "excludedTypeRows": excluded_type,
        },
        "byQuarter": by_quarter,
        "insights": insights,
        "rows": rows,
    }
    out_path = os.path.join(DATA, "_cw_agreements.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    t = out["totals"]
    print(f"Wrote {out_path}: {t['partners']} partners, {t['agreements']} agreements, "
          f"${t['mrr']:,.0f}/mo MRR (${t['arr']:,.0f} ARR); "
          f"AT RISK {t['agreementsAtRisk']} agreements / {t['partnersAtRisk']} partners / "
          f"${t['mrrAtRisk']:,.0f}/mo; {t['blankEndCount']} blank end-dates; "
          f"{t['ignoredCompanies']} non-dashboard companies ignored; source {out['source']!r}")


if __name__ == "__main__":
    sys.exit(main())
