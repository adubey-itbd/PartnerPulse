"""Pull REAL data for a set of Halo clients and merge them into the dashboards.

Runs the same extraction as extract.build_partner (Halo client fields + SIP
counts + service-review meeting notes + TeamGPS CSAT/NPS + local .docx
transcripts when a matching Transcripts/{Partner}/ folder exists) then the
gpt-5.4 churn analysis (extract.ai). Transcript ingestion needs markitdown; if
it is missing the step is skipped with a warning instead of failing. Skips the
deck path. Writes data/{slug}.json (no demo flag) and injects an exec-overview
object for each into the hardcoded real-partner array.

    python scripts/build_real_partners.py            # build all
    python scripts/build_real_partners.py netgain    # build one (by slug) — smoke test
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extract import config, halo, teamgps, ai

DATA = ROOT / "data"
EXEC = ROOT / "index.html"


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# display_name, halo_client_id, halo_search (for SIP name match), teamgps_company
NEW = [
    ("Netgain",            120, "NetGain",       "NetGain Technology"),
    ("F12",                775, "F12",           "F12"),
    ("RedHelm - 1Path",     21, "RedHelm -1Path", "RedHelm"),
    ("Proda Technologies", 713, "Proda",         "Proda"),
    ("Amoskeag Network Consulting Group LLC", 516, "Amoskeag",      "Amoskeag Network Consulting Group LLC"),
    ("Granite Networks Inc",                   72, "Granite Networks", "Granite Networks Inc"),
    ("Secure Future Tech Solutions",          835, "Secure Future", "Secure Future Tech Solutions"),
    ("Atlantic PC Inc",                       942, "Atlantic PC",   "Atlantic PC Inc"),
]


def build_real(name, client_id, halo_search, teamgps_company, nps_all):
    client = halo.get_client(client_id)
    cf = halo.parse_custom_fields(client)
    emails, domains = halo.get_users(client_id)
    sips = halo.count_sips(client_id, name_terms=[name, halo_search, client.get("name", "")])

    # TeamGPS CSAT uses a server-side EXACT company-name filter. The short search
    # terms miss, so fall back to the exact Halo client name (which matches).
    csat = teamgps.get_csat(teamgps_company)
    if not csat and client.get("name") and client.get("name") != teamgps_company:
        csat = teamgps.get_csat(client.get("name"))
    csat_stats = teamgps.csat_stats(csat)
    nps = teamgps.filter_nps(nps_all, emails, domains)
    nps_stats = teamgps.nps_stats(nps)

    historical_calls, note_authors = [], Counter()
    for t in halo.find_service_tickets(client_id, search="Service Call"):
        notes = halo.get_meeting_notes(t["id"])
        for n in notes:
            note_authors[n.get("who")] += 1
        if notes:
            historical_calls.append({
                "ticket_id": t["id"], "summary": t["summary"], "date": t["date"],
                "notes": "\n\n".join(n["note"] for n in notes),
            })

    account_manager = (note_authors.most_common(1)[0][0] + " (Dedicated Team Lead)"
                       if note_authors else (client.get("accountmanagertech") or ""))

    # Local .docx transcripts — any Transcripts/ folder matching the partner name
    # (case/punctuation-insensitive) is ingested, same as the registry build path.
    tx = []
    try:
        from extract import transcripts as transcripts_mod
        tx = transcripts_mod.parse_partner_transcripts(name)
        if tx:
            print(f"  [transcripts] {len(tx)} parsed", file=sys.stderr)
    except ImportError:
        print("  [transcripts] markitdown not installed — skipping transcript ingestion",
              file=sys.stderr)

    data = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "partner": name,
            "sources": {"csat": len(csat), "nps": len(nps), "calls": len(historical_calls),
                        "decks": 0, "transcripts": len(tx)},
        },
        "client": {
            "id": client.get("id"), "name": name, "vip": bool(client.get("is_vip")),
            "rag": cf.get("CFMDERAG"), "cancel_risk": cf.get("CFCancelationRisk"),
            "health_reason": cf.get("CFHealthReason"), "next_step": cf.get("CFNextStep"),
            "sip_ticket": cf.get("CFSIPTicketMDE"),
            "sip_open": sips.get("open", 0), "sip_closed": sips.get("closed", 0),
            "service_line": cf.get("CFProduct"), "account_manager": account_manager,
        },
        "csat_stats": csat_stats, "csat_comments": csat,
        "nps_stats": nps_stats, "nps_comments": nps,
        "historical_calls": historical_calls,
        "action_items": [], "decks": [], "transcripts": tx,
    }
    data["ai"] = ai.analyze(data)
    return data


def to_exec_obj(data):
    """Convert a built partner cache into an executive-overview array object."""
    c, aih = data["client"], data.get("ai", {}) or {}
    cs = data.get("csat_stats", {})
    csat_total = sum(v for k, v in cs.items() if k != "Unrated")
    if csat_total:
        pos = round(cs.get("Positive", 0) / csat_total * 100)
        neg = round(cs.get("Negative", 0) / csat_total * 100)
        neu = max(0, 100 - pos - neg)
        vol = sum(cs.values())
    else:
        ns = data.get("nps_stats", {})
        nt = sum(ns.values())
        if nt:
            pos = round(ns.get("Promoter", 0) / nt * 100)
            neg = round(ns.get("Detractor", 0) / nt * 100)
            neu = max(0, 100 - pos - neg)
        else:
            pos, neu, neg = 100, 0, 0
        vol = nt
    drivers = [d.get("factor", "") for d in (aih.get("drivers") or []) if d.get("factor")]
    summary = (aih.get("summary") or "").strip()
    talk = [s.strip() + "." for s in re.split(r"(?<=[.!?])\s+", summary) if s.strip()][:2]
    last_call = ""
    calls = data.get("historical_calls", [])
    if calls:
        last_call = str(calls[0].get("date") or "")[:10]
    return {
        "name": c["name"], "slug": slugify(data["meta"]["partner"]),
        "churnRisk": aih.get("risk_score") or 0,
        "csatPositivePct": pos, "reviewVolume": vol,
        "sentiment": {"positive": pos, "neutral": neu, "negative": neg},
        "sentimentTrend": aih.get("sentiment_trend") or "Stable",
        "topDriver": (drivers[0] if drivers else "—"),
        "themes": drivers[:4] or ["No drivers identified"],
        "talkingPoints": talk or [summary or "No summary available."],
        "lastCall": last_call or "2026-06-01", "callsAnalyzed": len(calls),
    }


def js(o):
    return json.dumps(o, ensure_ascii=False)


def exec_object_js(o):
    return (
        '        { name: %s, slug: %s, churnRisk: %d, csatPositivePct: %d, reviewVolume: %d,\n'
        '          sentiment: { positive: %d, neutral: %d, negative: %d }, sentimentTrend: %s,\n'
        '          topDriver: %s,\n'
        '          themes: %s,\n'
        '          talkingPoints: %s,\n'
        '          lastCall: %s, callsAnalyzed: %d },'
        % (js(o["name"]), js(o["slug"]), o["churnRisk"], o["csatPositivePct"], o["reviewVolume"],
           o["sentiment"]["positive"], o["sentiment"]["neutral"], o["sentiment"]["negative"],
           js(o["sentimentTrend"]), js(o["topDriver"]), js(o["themes"]),
           js(o["talkingPoints"]), js(o["lastCall"]), o["callsAnalyzed"]))


def inject_exec(objs):
    """Additively merge real-partner objects into the BEGIN/END block at the top of
    the hardcoded array. Existing entries are preserved; a freshly built object whose
    slug is already present is replaced in place, otherwise it is appended — so a
    partial run can add new partners without re-fetching or overwriting the others."""
    html = EXEC.read_text(encoding="utf-8")
    open_marker = "    const partners = [\n"
    begin = "        // ---- BEGIN real partners pulled by build_real_partners.py ----\n"
    end = "        // ---- END real partners ----\n"
    if begin in html and end in html:
        pre, rest = html.split(begin, 1)
        block, post = rest.split(end, 1)
    else:
        idx = html.index(open_marker) + len(open_marker)
        pre, block, post = html[:idx], "", html[idx:]
    # Split the block into per-object chunks so we can replace/keep by slug.
    chunks = re.split(r"(?=^        \{ name: )", block, flags=re.M)
    by_slug = {}
    kept = []
    for ch in chunks:
        m = re.search(r'slug: "([^"]+)"', ch)
        if m:
            by_slug[m.group(1)] = len(kept)
            kept.append(ch.rstrip("\n"))
    built = {o["slug"]: exec_object_js(o) for o in objs}
    for slug, js_obj in built.items():
        if slug in by_slug:                 # replace existing entry in place
            kept[by_slug[slug]] = js_obj
        else:                               # append new entry
            kept.append(js_obj)
    block = "\n".join(c for c in kept if c.strip()) + "\n"
    html = pre + begin + block + end + post
    EXEC.write_text(html, encoding="utf-8")


def warn_unmatched_transcript_dirs():
    """Every Transcripts/ subfolder should belong to SOME built partner — the
    registry (extract.build_all) or the NEW list here. Anything else would be
    silently ignored by both build paths, so call it out."""
    from extract import partners as registry
    known = {slugify(p.name) for p in registry.PARTNERS} | {slugify(n[0]) for n in NEW}
    if not config.TRANSCRIPTS_DIR.is_dir():
        return
    unmatched = [d.name for d in sorted(config.TRANSCRIPTS_DIR.iterdir())
                 if d.is_dir() and slugify(d.name) not in known]
    for name in unmatched:
        print(f"WARNING: Transcripts/{name}/ does not match any built partner — "
              f"its files are NOT being ingested. Add the partner to "
              f"extract/partners.py or scripts/build_real_partners.py NEW.",
              file=sys.stderr)


def main():
    only = {a.lower() for a in sys.argv[1:]}
    targets = [n for n in NEW if not only or slugify(n[0]) in only]
    warn_unmatched_transcript_dirs()
    print(f"Fetching TeamGPS NPS set once…", file=sys.stderr)
    nps_all = teamgps.get_nps_all()
    print(f"  {len(nps_all)} NPS responses cached", file=sys.stderr)

    exec_objs = []
    for name, cid, hs, tg in targets:
        print(f"\n=== {name} (Halo {cid}) ===", file=sys.stderr)
        data = build_real(name, cid, hs, tg, nps_all)
        slug = slugify(name)
        (DATA / f"{slug}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        aih = data["ai"]
        print(f"  sources={data['meta']['sources']} | RAG={data['client']['rag']} "
              f"sip_open={data['client']['sip_open']} sip_closed={data['client']['sip_closed']}")
        print(f"  risk={aih.get('risk_score')} ({aih.get('risk_band')}) trend={aih.get('sentiment_trend')} "
              f"err={aih.get('_error')}")
        exec_objs.append(to_exec_obj(data))

    if exec_objs:
        inject_exec(exec_objs)
        print(f"\nInjected {len(exec_objs)} real partners into executive-overview array")


if __name__ == "__main__":
    main()
