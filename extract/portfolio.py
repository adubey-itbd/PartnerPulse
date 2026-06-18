"""Portfolio-level aggregates for the Executive Overview charts.

All derived from data already present in the per-partner caches (CSAT/NPS with
timestamps + the Grok `drivers[]`). No new extraction, no ticket/SLA signals.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone


# --- date helpers ------------------------------------------------------------
def _parse(ts):
    if not ts:
        return None
    s = str(ts).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        try:
            d = datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


# --- 1. Risk distribution (donut) -------------------------------------------
def risk_distribution(all_data):
    """Count partners by tier from their AI risk band.
    High = Critical/High, Watch = Medium, Healthy = Low."""
    dist = {"High": 0, "Watch": 0, "Healthy": 0}
    for d in all_data:
        band = ((d.get("ai") or {}).get("risk_band") or "").lower()
        if band in ("critical", "high"):
            dist["High"] += 1
        elif band == "medium":
            dist["Watch"] += 1
        elif band == "low":
            dist["Healthy"] += 1
    return dist


# --- 2. Weekly CSAT / NPS sentiment trend (line) ----------------------------
def sentiment_trend(all_data, weeks=12):
    """Real weekly trend across all partners from CSAT/NPS submission dates:
    weekly % positive CSAT and weekly average NPS score."""
    csat = []   # (datetime, rating)
    nps = []    # (datetime, score)
    for d in all_data:
        for r in d.get("csat_comments", []):
            dt = _parse(r.get("date"))
            if dt:
                csat.append((dt, (r.get("rating") or "")))
        for r in d.get("nps_comments", []):
            dt = _parse(r.get("date"))
            if dt and r.get("score") is not None:
                nps.append((dt, r.get("score")))

    all_dates = [dt for dt, _ in csat] + [dt for dt, _ in nps]
    if not all_dates:
        return []
    end = max(all_dates)
    # Align end to the start of next day, then walk back in 7-day buckets.
    end = end.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    buckets = []
    for i in range(weeks):
        b_end = end - timedelta(days=7 * (weeks - 1 - i))
        b_start = b_end - timedelta(days=7)
        pos = neu = neg = 0
        for dt, rating in csat:
            if b_start <= dt < b_end:
                if rating == "Positive":
                    pos += 1
                elif rating == "Neutral":
                    neu += 1
                elif rating == "Negative":
                    neg += 1
        csat_total = pos + neu + neg
        nps_scores = [s for dt, s in nps if b_start <= dt < b_end]
        buckets.append({
            "label": b_start.strftime("%b %d"),
            "csat_positive_pct": round(pos / csat_total * 100, 1) if csat_total else None,
            "csat_total": csat_total,
            "nps_avg": round(sum(nps_scores) / len(nps_scores), 2) if nps_scores else None,
            "nps_count": len(nps_scores),
        })
    return buckets


# --- 3. Feedback mix by source (stacked bar) --------------------------------
def feedback_mix(all_data):
    """Real sentiment counts for the two sources we actually score: CSAT and NPS."""
    csat = {"Positive": 0, "Neutral": 0, "Negative": 0}
    nps = {"Promoter": 0, "Passive": 0, "Detractor": 0}
    for d in all_data:
        cs = d.get("csat_stats", {})
        for k in csat:
            csat[k] += cs.get(k, 0)
        ns = d.get("nps_stats", {})
        for k in nps:
            nps[k] += ns.get(k, 0)
    return {"csat": csat, "nps": nps}


# --- 4. Top churn drivers (horizontal bars) ---------------------------------
# Theme buckets keyed by substrings found in the AI `drivers[].factor`/`evidence`
# text. Order matters — more specific themes first (first match wins).
_THEMES = [
    ("Open / aging action items", ["action item", "aging", "slipped", "slip", "unresolved",
                                    "not closed", "not finalized", "awaiting", "still not", "overdue"]),
    ("Renewal & contract risk", ["renewal", "contract", "cancellation", "cancel", "scope reduction",
                                 "business pressure", "resource alignment", "churn signal"]),
    ("Reporting & KPI alignment", ["reporting", "kpi", "utilization", "automation", "migration",
                                   "framework", "timesheet", "time entry"]),
    ("Engineer performance & quality", ["performance", "underperform", "productivity", "closure",
                                        "throughput", "output", "technical quality", "ownership", "engineer"]),
    ("Reliability & attendance", ["absent", "attendance", "unreliable", "leave", "coverage",
                                  "replacement", "availability"]),
    ("CSAT / NPS sentiment", ["csat", "nps", "detractor", "satisfaction", "sentiment",
                              "feedback", "unheard"]),
    ("Active SIPs / PIPs", ["sip", "pip", "improvement plan", "monitoring", "corrective"]),
    ("Process & SOP adherence", ["sop", "process", "procedure", "adherence", "escalation", "compliance"]),
    ("Relationship & advocacy", ["advocacy", "relationship", "executive", "healthy", "strong"]),
    ("Communication & engagement", ["communication", "responsive", "disengage", "stakeholder",
                                    "update", "engagement"]),
    ("Onboarding & ramp-up", ["onboard", "training", "ramp", "new joiner", "floater", "shadow"]),
]
_SEV_W = {"high": 3, "medium": 2, "low": 1}


def top_drivers(all_data, top_n=6):
    """Aggregate the Grok churn drivers across partners into themed, severity-
    weighted bars. Score normalized 0-1 against the strongest theme. The catch-all
    'Other' bucket is excluded from the chart."""
    scores = defaultdict(float)
    counts = defaultdict(int)
    for d in all_data:
        for dr in (d.get("ai") or {}).get("drivers", []):
            factor = (dr.get("factor") or "").lower() + " " + (dr.get("evidence") or "").lower()
            w = _SEV_W.get((dr.get("severity") or "").lower(), 1)
            theme = next((name for name, kws in _THEMES if any(k in factor for k in kws)), None)
            if theme is None:
                continue
            scores[theme] += w
            counts[theme] += 1
    if not scores:
        return []
    top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    mx = top[0][1] or 1
    return [{"theme": t, "score": round(s / mx, 2), "weight": s, "count": counts[t]}
            for t, s in top]


def build(all_data):
    """Assemble the full portfolio aggregate block."""
    return {
        "risk_distribution": risk_distribution(all_data),
        "sentiment_trend": sentiment_trend(all_data),
        "feedback_mix": feedback_mix(all_data),
        "top_drivers": top_drivers(all_data),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
