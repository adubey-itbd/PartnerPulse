"""Generate 40 synthetic demo partners to stress-test dashboard scalability.

Writes a stub data/{slug}.json for each demo partner (enough structure for the
Partner-360 drilldown to load) and regenerates data/_index.json from ALL
per-partner files (real + demo) using the real index_row + portfolio logic, so
the aggregates stay correct. Also emits executive-overview demo objects to
data/demo_exec_partners.js for injection into the root index.html.

Demo partners carry "demo": true on their client block so they can be filtered
or removed later. Re-running is idempotent (demo files are rewritten).

    python scripts/gen_demo_partners.py
"""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extract import portfolio


def slugify(name: str) -> str:
    """Mirror of extract.build_partner.slugify."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def index_row(data: dict) -> dict:
    """Mirror of extract.build_all.index_row (inlined to avoid the Azure SDK import)."""
    c = data.get("client", {})
    aih = data.get("ai", {}) or {}
    stats = data.get("csat_stats", {})
    total = sum(stats.values()) or 1
    return {
        "slug": slugify(data.get("meta", {}).get("partner") or c.get("name")),
        "name": c.get("name"), "client_id": c.get("id"), "rag": c.get("rag"),
        "cancel_risk": c.get("cancel_risk"), "service_line": c.get("service_line"),
        "vip": c.get("vip"), "sip_ticket": c.get("sip_ticket"),
        "sip_open": c.get("sip_open", 0), "sip_closed": c.get("sip_closed", 0),
        "account_manager": c.get("account_manager"),
        "csat_positive_pct": round(stats.get("Positive", 0) / total * 100, 1),
        "csat_total": sum(stats.values()),
        "nps_promoters": data.get("nps_stats", {}).get("Promoter", 0),
        "nps_detractors": data.get("nps_stats", {}).get("Detractor", 0),
        "risk_score": aih.get("risk_score"), "risk_band": aih.get("risk_band"),
        "sentiment_trend": aih.get("sentiment_trend"), "summary": aih.get("summary"),
        "sources": data.get("meta", {}).get("sources", {}),
    }

DATA = ROOT / "data"
SEED = 42
random.seed(SEED)

# How many synthetic demo partners to seed (on top of the real ones).
DEMO_COUNT = 40

# Realistic-but-synthetic demo partner names. (Netgain, F12, RedHelm - 1Path and
# Proda Technologies were moved OUT of this pool — they are now pulled live from
# Halo by build_real_partners.py, so they must not be regenerated as demo data.)
NAMES = [
    "Cedar Ridge Networks", "Vantage IT Solutions",
    "Ironclad Technologies", "Meridian Managed IT", "Harborline Systems",
    "Brightpath Technology", "Stonegate IT Services", "Aspen Digital Works",
    "Crestwood Networks", "Pinnacle Tech Group", "Riverstone IT",
    "Silverline Managed Services", "Beacon Technology Partners", "Granite Peak IT",
    "Evergreen Systems Group", "Falcon Ridge Technologies", "Lighthouse IT Co.",
    "Maple Grove Networks", "Sterling Managed IT", "Atlas Technology Solutions",
    "Copperfield Systems", "Westgate IT Partners", "Lakeside Technology Group",
    "Redwood Managed Services", "Horizon Edge IT", "Compass Network Solutions",
    "Keystone Technology", "Sandbar Digital", "Foundry IT Services",
    "Talon Managed IT", "Driftwood Technology Group", "Quartz Networks",
    "Anchorpoint Systems", "Highland Tech Partners", "Sequoia Managed Services",
    "Tidewater IT Group",
]

SERVICE_LINES = ["NOC", "MDE", "SOC", "Helpdesk", "Cloud"]
MANAGERS = [
    "Ashish Paul (Dedicated Team Lead)", "Aman Thakur (Dedicated Team Lead)",
    "Akhilesh Shukla (Dedicated Team Lead)", "Kip Singh (Dedicated Team Lead)",
    "Priya Nair (Dedicated Team Lead)", "Rohan Mehta (Dedicated Team Lead)",
]

TREND_BY_TIER = {
    "High": ["Declining", "Declining", "Stable"],
    "Watch": ["Stable", "Declining", "Improving"],
    "Healthy": ["Stable", "Improving", "Stable"],
}

DRIVERS_HIGH = [
    ("Active performance management on named engineer", "High",
     "Repeated CSAT complaints and an open SIP on the assigned resource."),
    ("Renewal and resource alignment risk", "High",
     "Partner has flagged contract scope and is reviewing resource fit ahead of renewal."),
    ("Recent negative CSAT tied to delivery quality", "Medium",
     "Cluster of negative ratings on ticket quality and turnaround in the last reviews."),
]
DRIVERS_WATCH = [
    ("Named engineer performance inconsistency", "Medium",
     "Mixed feedback on reliability and follow-through across recent tickets."),
    ("Open / aging action items", "Medium",
     "Several reporting and KPI action items have slipped across reviews."),
    ("Reporting & KPI visibility gaps", "Low",
     "Partner has requested clearer utilization and SLA reporting."),
]
DRIVERS_HEALTHY = [
    ("Strong partner satisfaction and advocacy", "Low",
     "Consistently positive CSAT and promoter-heavy NPS with no escalations."),
    ("Positive named-engineer feedback", "Low",
     "Repeated praise for the assigned engineer in recent service reviews."),
    ("Minor open action item", "Low",
     "One long-open reporting item, not currently affecting sentiment."),
]

THEMES_HIGH = [
    "Active performance management across named resources",
    "Contract scope / renewal risk signal raised",
    "Recent negative CSAT tied to underperforming technician",
    "Unresolved action items keeping the account fragile",
]
THEMES_WATCH = [
    "Named-engineer performance inconsistency",
    "Open / aging action items without firm due dates",
    "Reporting & KPI visibility gaps",
    "Mixed but recoverable customer sentiment",
]
THEMES_HEALTHY = [
    "Strong partner satisfaction and advocacy",
    "Positive named-engineer feedback",
    "No active escalations or churn signals",
    "Minor operational watchpoint only",
]

TALK_HIGH = [
    "High churn risk from active performance-management cases and renewal/scope signals.",
    "Recent reviews show pockets of stabilization, but unresolved items keep the account fragile.",
]
TALK_WATCH = [
    "Broadly satisfied, but recurring engineer-specific and reporting concerns drive amber health.",
    "Follow-through gaps are straining the relationship; needs closer cadence.",
]
TALK_HEALTHY = [
    "Healthy relationship with consistently positive CSAT and strong NPS.",
    "Only minor open action items; no current churn indicators.",
]


def tier_of(risk):
    return "High" if risk >= 45 else "Watch" if risk >= 25 else "Healthy"


def band_of(risk):
    return "High" if risk >= 45 else "Medium" if risk >= 25 else "Low"


def rag_of(tier):
    return {"High": "Red", "Watch": "Amber", "Healthy": "Green"}[tier]


def make_partner(i, name):
    # Realistic portfolio skew: a few High, some Watch, many Healthy.
    roll = random.random()
    if roll < 0.12:
        risk = random.randint(48, 84)
    elif roll < 0.37:
        risk = random.randint(26, 44)
    else:
        risk = random.randint(6, 24)
    tier = tier_of(risk)
    trend = random.choice(TREND_BY_TIER[tier])

    # Sentiment: higher risk -> more negative share. Positive == csat positive %.
    if tier == "High":
        positive = random.randint(62, 88)
    elif tier == "Watch":
        positive = random.randint(78, 94)
    else:
        positive = random.randint(90, 100)
    rem = 100 - positive
    negative = min(rem, random.randint(0, 3) + (4 if tier == "High" else 1 if tier == "Watch" else 0))
    negative = min(negative, rem)
    neutral = rem - negative

    review_vol = random.choice([random.randint(3, 25), random.randint(20, 90),
                                random.randint(60, 280)])
    # Build CSAT stats consistent with positive % and volume.
    pos_n = round(review_vol * positive / 100)
    neg_n = round(review_vol * negative / 100)
    neu_n = max(0, review_vol - pos_n - neg_n)
    nps_prom = random.randint(0, 18) if tier != "High" else random.randint(0, 4)
    nps_detr = random.randint(0, 2) if tier != "Healthy" else 0
    nps_pass = random.randint(0, 6)

    drivers_pool = (DRIVERS_HIGH if tier == "High"
                    else DRIVERS_WATCH if tier == "Watch" else DRIVERS_HEALTHY)
    themes_pool = (THEMES_HIGH if tier == "High"
                   else THEMES_WATCH if tier == "Watch" else THEMES_HEALTHY)
    talk_pool = (TALK_HIGH if tier == "High"
                 else TALK_WATCH if tier == "Watch" else TALK_HEALTHY)

    summary = " ".join(talk_pool)
    drivers = [{"factor": f, "severity": s, "evidence": e} for f, s, e in drivers_pool]

    client_id = 1000 + i
    am = random.choice(MANAGERS)
    sip = f"DEMO-{client_id}" if tier == "High" and random.random() < 0.7 else ""
    # Demo SIP counts: higher-risk partners tend to have more.
    if tier == "High":
        sip_open, sip_closed = random.randint(1, 3), random.randint(0, 3)
    elif tier == "Watch":
        sip_open, sip_closed = random.randint(0, 1), random.randint(0, 2)
    else:
        sip_open, sip_closed = 0, random.randint(0, 1)

    detail = {
        "meta": {
            "generated_at": "2026-06-06T00:00:00+00:00",
            "partner": name,
            "demo": True,
            "sources": {"csat": review_vol, "nps": nps_prom + nps_pass + nps_detr,
                        "calls": random.randint(0, 4), "decks": random.randint(0, 4),
                        "transcripts": random.randint(0, 8)},
        },
        "client": {
            "id": client_id, "name": name, "vip": random.random() < 0.1,
            "rag": rag_of(tier), "cancel_risk": ("Medium" if tier == "High" else "Low"),
            "health_reason": "", "next_step": "", "sip_ticket": sip,
            "sip_open": sip_open, "sip_closed": sip_closed,
            "service_line": random.choice(SERVICE_LINES), "account_manager": am,
            "demo": True,
        },
        "csat_stats": {"Positive": pos_n, "Neutral": neu_n, "Negative": neg_n, "Unrated": 0},
        "csat_comments": [],
        "nps_stats": {"Promoter": nps_prom, "Passive": nps_pass, "Detractor": nps_detr},
        "nps_comments": [],
        "historical_calls": [],
        "action_items": [],
        "decks": [],
        "transcripts": [],
        "ai": {
            "risk_score": risk, "risk_band": band_of(risk), "confidence": "Medium",
            "summary": summary, "sentiment_trend": trend, "drivers": drivers,
            "remediation": [], "action_items": [], "_model": "demo-seed",
        },
    }

    # Object for the executive-overview hardcoded array.
    last_call = f"2026-0{random.randint(4,6)}-{random.randint(10,28):02d}"
    exec_obj = {
        "name": name, "slug": slugify(name), "churnRisk": risk, "csatPositivePct": positive,
        "reviewVolume": review_vol,
        "sentiment": {"positive": positive, "neutral": neutral, "negative": negative},
        "sentimentTrend": trend, "topDriver": themes_pool[0],
        "themes": themes_pool[:], "talkingPoints": talk_pool[:],
        "lastCall": last_call, "callsAnalyzed": detail["meta"]["sources"]["calls"],
        "demo": True,
    }
    return detail, exec_obj


def main():
    # 1. Remove any stale demo files (idempotent re-run).
    for f in DATA.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (d.get("client") or {}).get("demo") or (d.get("meta") or {}).get("demo"):
            f.unlink()

    exec_objs = []
    for i, name in enumerate(NAMES[:DEMO_COUNT]):
        detail, exec_obj = make_partner(i, name)
        slug = slugify(name)
        (DATA / f"{slug}.json").write_text(
            json.dumps(detail, indent=2, ensure_ascii=False), encoding="utf-8")
        exec_objs.append(exec_obj)

    # 2. Regenerate _index.json from ALL per-partner files (real + demo).
    all_data = []
    for f in sorted(DATA.glob("*.json")):
        if f.name.startswith("_"):
            continue
        all_data.append(json.loads(f.read_text(encoding="utf-8")))

    rows = [index_row(d) for d in all_data]
    rows.sort(key=lambda r: (r.get("risk_score") is None, -(r.get("risk_score") or 0)))
    payload = {"partners": rows, "portfolio": portfolio.build(all_data)}
    (DATA / "_index.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. Emit exec-overview demo objects as a JS array fragment.
    def js(o):
        return json.dumps(o, ensure_ascii=False)
    lines = []
    for o in exec_objs:
        lines.append(
            "        { name: %s, slug: %s, churnRisk: %d, csatPositivePct: %d, reviewVolume: %d,\n"
            "          sentiment: { positive: %d, neutral: %d, negative: %d }, sentimentTrend: %s, demo: true,\n"
            "          topDriver: %s,\n"
            "          themes: %s,\n"
            "          talkingPoints: %s,\n"
            "          lastCall: %s, callsAnalyzed: %d },"
            % (js(o["name"]), js(o["slug"]), o["churnRisk"], o["csatPositivePct"], o["reviewVolume"],
               o["sentiment"]["positive"], o["sentiment"]["neutral"], o["sentiment"]["negative"],
               js(o["sentimentTrend"]), js(o["topDriver"]), js(o["themes"]),
               js(o["talkingPoints"]), js(o["lastCall"]), o["callsAnalyzed"]))
    demo_block = "\n".join(lines)
    (DATA / "demo_exec_partners.js").write_text(demo_block + "\n", encoding="utf-8")

    # 4. Inject the demo objects into the executive-overview hardcoded array
    #    (now the root index.html), replacing whatever demo block is there. The
    #    real partners are kept; we splice between the last real partner
    #    (Stasmayer) and the array close.
    exec_html = ROOT / "index.html"
    if exec_html.exists():
        html = exec_html.read_text(encoding="utf-8")
        anchor = '          lastCall: "2026-05-29", callsAnalyzed: 4 },\n'
        if anchor in html:
            head, rest = html.split(anchor, 1)
            close = "\n    ];"
            _, tail = rest.split(close, 1)   # drop the old demo block
            marker = ("\n\n        // ---- %d synthetic demo partners (scalability test) · "
                      "generated by gen_demo_partners.py ----\n" % len(exec_objs))
            html = head + anchor + marker + demo_block + close + tail
            exec_html.write_text(html, encoding="utf-8")
            print(f"Injected {len(exec_objs)} demo partners into {exec_html.relative_to(ROOT)}")
        else:
            print("WARN: exec-overview anchor not found; skipped HTML injection")

    dist = payload["portfolio"]["risk_distribution"]
    print(f"Wrote {len(exec_objs)} demo partners. Total partners: {len(rows)}")
    print(f"Risk distribution: {dist}")


if __name__ == "__main__":
    main()
