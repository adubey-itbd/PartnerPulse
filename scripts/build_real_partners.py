"""Pull REAL data for a set of Halo clients and merge them into the dashboards.

Runs the same extraction as extract.build_partner (Halo client fields + SIP
counts + service-review meeting notes + TeamGPS CSAT/NPS + local .docx
transcripts when a matching Transcripts/{Partner}/ folder exists) then the
Grok churn analysis (extract.ai). Service-deck attachments (PDF/PPTX) on the
review tickets are converted to Markdown like the registry path (added
2026-06-12 — previously skipped, which left every extras partner with an empty
Service Decks tab). Deck conversion and transcript ingestion need markitdown;
if it is missing both are skipped with a warning instead of failing. Writes
data/{slug}.json (no demo flag); the dashboard picks these up via
data/_index.json + data/_overview.json (build_all --reindex, then
build_overview.py). Each fetched client is name-checked against the display name
(halo.fuzzy_name_match) and skipped if the pinned client_id points at the wrong
Halo record (the Acrisure 937->79 class).

    python scripts/build_real_partners.py            # build all
    python scripts/build_real_partners.py netgain    # build one (by slug) — smoke test

NOTE: to_exec_obj / exec_object_js / inject_exec below are NOT dead code — they
are imported by scripts/refresh_exec_row.py (deprecated, kept for rollback to the
pre-AIODI embedded-array dashboard). They were therefore left in place rather than
removed; inject_exec is no longer called from main() since the live dashboard is
data-driven (no embedded array to inject into).
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
from extract.textutil import slugify

DATA = ROOT / "data"
EXEC = ROOT / "index.html"


# display_name, halo_client_id (None = transcript-only, no Halo/TeamGPS),
# halo_search (for SIP name match), teamgps_company
NEW = [
    ("Netgain",            120, "NetGain",       "NetGain Technology"),
    ("F12",                775, "F12",           "F12"),
    ("RedHelm - 1Path",     21, "RedHelm -1Path", "RedHelm"),
    ("Proda Technologies", 713, "Proda",         "Proda"),
    ("Amoskeag Network Consulting Group LLC", 516, "Amoskeag",      "Amoskeag Network Consulting Group LLC"),
    ("Granite Networks Inc",                   72, "Granite Networks", "Granite Networks Inc"),
    ("Secure Future Tech Solutions",          835, "Secure Future", "Secure Future Tech Solutions"),
    ("Atlantic PC Inc",                       942, "Atlantic PC",   "Atlantic PC Inc"),
    # ---- added 2026-06-12: partners whose service-call transcripts Amit can
    # pull via the M365 connector (calendar audit) ----
    ("Continuous Networks",          49,  "Continuous Networks", "Continuous Networks LLC"),
    ("APM IT Solutions",             965, "APM IT",              "APM IT Solutions"),
    ("Matador Networks",             109, "Matador",             "Matador Networks LLC"),
    ("Vitis Tech",                   144, "Vitis",               "Vitis Tech"),
    ("Community IT",                 45,  "Community IT",        "Community IT Innovators"),
    ("PEI",                          137, "PEI",                 "Dataprise (PEI)"),
    # Independent "Dataprise" account (Halo 57, site PH, RM Pritam Das) — distinct from
    # PEI (137, NDA). Its monthly CSAT is filed under TeamGPS company "Dataprise" and is
    # the active one (2026 surveys); PEI (137) is the older record (surveys ended 2025).
    ("Dataprise",                    57,  "Dataprise",           "Dataprise"),
    ("Prevare LLC",                  141, "Prevare",             "Prevare LLC"),
    ("Perfect Cloud Solutions",      834, "Perfect Cloud",       "Perfect Cloud Solutions"),
    ("Network Builders IT",          426, "Network Builders",    "Network Builders IT"),
    ("Dependable Solutions",         60,  "Dependable",          "Dependable Solutions Inc"),
    ("Pegasus Technology Solutions", 135, "Pegasus",             "Pegasus Technology Solutions"),
    ("Boomtown CIO",                 34,  "Boomtown",            "Boomtown CIO"),
    # "CW Now" is the meeting-title shorthand for Halo client "C&W Computers"
    # (their domain is cwnow.com) — corrected 2026-06-12 from the bogus
    # transcript-only "CW Now" entry.
    ("C&W Computers",                39,  "C&W",                 "C&W Computers"),
    ("Networking Now",               121, "Networking Now",      "Networking Now"),
    ("Galactica Cybersecurity",      946, "Galactica",           "Galactica CyberSecurity"),
    ("ICSI",                         80,  "ICSI",                "ICSI"),
    ("Infopathways",                 83,  "Infopathways",        "Infopathways, Inc."),
    ("NerdsToGo",                    118, "NerdsToGo",           "NerdsToGo Inc"),
    ("CMIT Solutions Stamford",      44,  "CMIT",                "CMIT Solutions (Stamford, CT)"),
    ("Vistitude",                    187, "Vistitude",           "Vistitude Computer Solutions Inc"),
    ("Mission Technology",           975, "Mission Technology",  "Mission Technology Solutions"),
    # ---- added 2026-06-14 for the CTO demo roster ----
    # Halo has two "Acrisure Cyber Services" records: 79 is the real DES-managed
    # one (CFMDERAG=Green, CFProduct=MDE); 937 is an empty duplicate (no RAG/
    # service line). Corrected 937 -> 79 on 2026-06-15 so the health data is real.
    ("Acrisure Cyber Services",      79,  "Acrisure",            "Acrisure Cyber Services"),
    ("Byte Solutions Inc",            38, "Byte Solutions",      "Byte Solutions Inc"),
    ("SERVICAD",                     154, "SERVICAD",            "SERVICAD"),
    ("OutsourceIT",                  928, "OutsourceIT",         "OutsourceIT"),
    # ---- added 2026-06-15: full DES/MDE roster from Halo report 364 "DES RAG
    # Status" (filter: Area.CFMDERAG >= 1). These are the remaining RAG-managed
    # partners not previously onboarded. Display names are corp-suffix-stripped
    # so the Graph transcript pull's folders auto-match; teamgps_company is the
    # exact Halo client name (CSAT uses an exact filter, with a client.name
    # fallback). client_id pinned from the enumeration. Excluded by request:
    # InTelecom (81, inactive), iStreet Solutions (89, going inactive); deduped:
    # TAB 971 (kept 163), Spidernet 1006 (kept 1003).
    ("Atlas Professional Services",          28,  "Atlas Professional",        "Atlas Professional Services, Inc."),
    ("Blackline IT",                         841, "Black Line",                "Black Line IT"),
    ("IronEdge Group",                       200, "IronEdge",                  "IronEdge Group, LTD"),
    ("Marco",                                837, "Marco",                     "Marco Inc"),
    ("Thrive NextGen",                       29,  "Thrive",                    "Thrive NextGen"),
    ("Turn Key Solutions",                   182, "Turn Key",                  "Turn Key Solutions LLC"),
    ("ITSolutions",                          94,  "ITSolutions",               "ITSolutions Inc"),
    ("OPUS Consulting Group(ZymeWorks)",     131, "OPUS",                      "OPUS Consulting Group Ltd"),
    ("Summit Business Technologies",         160, "Summit Business",           "Summit Business Technologies"),
    ("Thinksocially",                        175, "Thinksocially",             "Thinksocially LLC"),
    ("Aqueduct Technologies",                958, "Aqueduct",                  "Aqueduct Technologies, Inc."),
    ("Brown Cow Technology",                 20,  "Brown Cow",                 "Brown Cow Technology Inc."),
    ("Deerwood Technologies",                59,  "Deerwood",                  "Deerwood Technologies Inc"),
    ("EasyIT",                               209, "EasyIT",                    "EasyIT"),
    ("Innovative Technology Solutions (ITS)", 199, "Innovative Technology",    "Innovative Technology Solutions"),
    ("ISOutsource",                          210, "ISOutsource",               "ISOutsource"),
    ("LanTek Online",                        100, "LanTek",                    "LanTek Online"),
    ("LATG",                                 883, "LATG",                      "LATG"),
    ("Microcomputer Consulting Group",       777, "Microcomputer",             "Microcomputer Consulting Group, Inc."),
    ("MyTech Partners",                      823, "MyTech",                    "MyTech Partners"),
    ("NTi Networks",                         126, "NTi",                       "NTi Networks"),
    ("Omega Systems",                        948, "Omega Systems",             "Omega Systems Corp"),
    ("OmegaCor IT",                          129, "OmegaCor",                  "OmegaCor Technologies"),
    ("PCH Technologies",                     134, "PCH",                       "PCH Technologies"),
    ("Planet Depos",                         216, "Planet Depos",              "Planet Depos"),
    ("Predictiveit",                         829, "Predictiveit",              "Predictiveit"),
    ("Servcom USA",                          153, "Servcom",                   "Servcom USA"),
    ("TAB Computer Systems",                 163, "TAB Computer",              "TAB Computer Systems, Inc"),
    ("Teal Tech",                            164, "Teal",                      "Teal LLC"),
    ("TekScape",                             169, "TekScape",                  "TekScape Inc"),
    ("Telecommunication Technologies Group", 170, "Telecommunication Technologies", "Telecommunication Technologies Group"),
    ("Think Unified",                        174, "Think Unified",             "Think Unified"),
    ("True North ITG",                       213, "True North",                "True North ITG Inc"),
    ("Ryan Creek Technology",                959, "Ryan Creek",                "Ryan Creek Technology Associates, Inc."),
    ("Spidernet Technical Consulting",       1003, "Spidernet",                "Spidernet Consulting"),
    ("Uptime USA",                           982, "Uptime",                    "Uptime USA"),
    # ---- added 2026-06-15: on DES dashboard 1015 but NOT caught by report-364's
    # CFMDERAG>=1 filter (their Halo RAG is untagged / they have no Halo record).
    # See scripts/discover_des_roster.py SUPPLEMENTAL — these are the documented
    # exceptions the auto-discovery can't derive from Halo alone.
    ("ETech 7 Inc",                          924, "ETech 7",                   "ETech 7 Inc"),
    # ECS Consulting LLC has no Halo client record — transcript-only build
    # (client_id=None): AI runs on the 3 service-call .vtt in Transcripts/ECS Consulting/.
    ("ECS Consulting",                       None, "ECS Consulting",           "ECS Consulting LLC"),
    # ---- added 2026-06-16: report-364 members surfaced by discover_des_roster.py
    # (CFMDERAG>=1 but never built). Inactive accounts (iStreet 89, InTelecom 81)
    # remain excluded per ops.
    ("CPCORP Inc",                           968, "CPCORP",                    "CPCORP Inc"),
    ("Stratti",                              636, "Stratti",                   "Stratti"),
]


def build_real(name, client_id, halo_search, teamgps_company, nps_all, force_ai=False):
    # markitdown-backed module, used for both deck conversion and .docx
    # transcripts; None when markitdown is missing (both are then skipped).
    try:
        from extract import transcripts as transcripts_mod
    except ImportError:
        transcripts_mod = None
        print("  [decks/transcripts] markitdown not installed — skipping deck "
              "conversion and transcript ingestion", file=sys.stderr)

    decks = []
    # Deck caching: reuse already-converted deck markdown (markitdown is slow) by the
    # stable attachment id, so a rebuild only re-converts genuinely new decks.
    prev_decks = {}
    _pc = DATA / f"{slugify(name)}.json"
    if _pc.exists() and not force_ai:
        try:
            for dk in (json.loads(_pc.read_text(encoding="utf-8")).get("decks") or []):
                if dk.get("attachment_id") is not None:
                    prev_decks[dk["attachment_id"]] = dk
        except (ValueError, OSError):
            pass
    if client_id is None:
        # Transcript-only partner: no Halo client record exists.
        client, cf, sips = {}, {}, {}
        csat, nps, historical_calls = [], [], []
        csat_stats = teamgps.csat_stats(csat)
        nps_stats = teamgps.nps_stats(nps)
        account_manager = ""
    else:
        client = halo.get_client(client_id)
        # Guard against a wrong client_id pinned in NEW (the Acrisure 937->79 class):
        # the fetched Halo client name must plausibly match the display name. If it
        # does not, the id points at the wrong/empty record -> WARN and skip so we
        # don't publish bogus health data under this partner.
        fetched_name = client.get("name") or ""
        if fetched_name and not halo.fuzzy_name_match(name, fetched_name):
            print(f"  WARNING: Halo client {client_id} is {fetched_name!r}, which does "
                  f"not match {name!r} -- wrong client_id? Skipping this partner.",
                  file=sys.stderr)
            return None
        cf = halo.parse_custom_fields(client)
        emails, domains = halo.get_users(client_id)
        sips = halo.count_sips(client_id, name_terms=[name, halo_search, client.get("name", "")],
                               sip_ticket_field=cf.get("CFSIPTicketMDE"))

        # TeamGPS CSAT uses a server-side EXACT company-name filter. The short search
        # terms miss, so fall back to the exact Halo client name (which matches).
        csat = teamgps.get_csat(teamgps_company)
        if not csat and client.get("name") and client.get("name") != teamgps_company:
            csat = teamgps.get_csat(client.get("name"))
        csat_stats = teamgps.csat_stats(csat)
        nps = teamgps.filter_nps(nps_all, emails, domains)
        nps_stats = teamgps.nps_stats(nps)

        historical_calls, note_authors = [], Counter()
        # Continue-on-failure: a persistent Halo 5xx on this client's ticket list
        # (seen intermittently) must not abort the whole batch — the partner just
        # builds without Halo call-notes (still gets transcripts + CSAT/NPS + AI).
        try:
            service_tickets = halo.find_service_tickets(client_id, search="Service Call")
        except Exception as e:
            print(f"  [calls] find_service_tickets failed: {e} — continuing without Halo call notes", file=sys.stderr)
            service_tickets = []
        for t in service_tickets:
            notes = halo.get_meeting_notes(t["id"])
            for n in notes:
                note_authors[n.get("who")] += 1
            if notes:
                # Call date = latest meeting-NOTE datetime, not ticket dateoccurred
                # (recurring tickets keep an early dateoccurred — see build_partner.py).
                note_dt = max((n.get("datetime") or "") for n in notes) or t["date"]
                historical_calls.append({
                    "ticket_id": t["id"], "summary": t["summary"], "date": note_dt,
                    "notes": "\n\n".join(n["note"] for n in notes),
                })
            # Service-deck attachments (PDF/PPTX -> Markdown), same as the
            # registry path in extract/build_partner.py.
            if transcripts_mod is not None:
                for a in halo.list_attachments(t["id"]):
                    fn = (a.get("filename") or "").lower()
                    ext = fn.rsplit(".", 1)[-1] if "." in fn else ""
                    if a.get("id") and ext in ("pdf", "pptx"):
                        if a["id"] in prev_decks:        # already converted — reuse
                            decks.append(prev_decks[a["id"]])
                            continue
                        try:
                            raw = halo.download_attachment(a["id"])
                            deck = transcripts_mod.deck_to_markdown(
                                raw, f"{slugify(name)}_{t['id']}_{a['id']}", ext=ext)
                            decks.append({
                                "ticket_id": t["id"], "attachment_id": a["id"],
                                "filename": a.get("filename"),
                                "md_path": deck["md_path"], "markdown": deck["markdown"],
                            })
                            print(f"  [deck] {a.get('filename')} -> "
                                  f"{len(deck['markdown'])} md chars", file=sys.stderr)
                        except Exception as e:
                            print(f"  [deck] FAILED {a.get('filename')}: {e}", file=sys.stderr)

        account_manager = (note_authors.most_common(1)[0][0] + " (Dedicated Team Lead)"
                           if note_authors else (client.get("accountmanagertech") or ""))

    # Local .docx/.vtt transcripts — any Transcripts/ folder matching the partner
    # name (case/punctuation-insensitive) is ingested, same as the registry path.
    tx = []
    if transcripts_mod is not None:
        tx = transcripts_mod.parse_partner_transcripts(name)
        if tx:
            print(f"  [transcripts] {len(tx)} parsed", file=sys.stderr)

    data = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "partner": name,
            "sources": {"csat": len(csat), "nps": len(nps), "calls": len(historical_calls),
                        "decks": len(decks), "transcripts": len(tx)},
        },
        "client": {
            # Halo Client Name is the source of truth for the displayed name (a Halo
            # rename then propagates everywhere); fall back to the roster label only if
            # Halo returns no name. meta.partner keeps the roster label (drives the slug
            # + Transcripts/ folder matching).
            "id": client.get("id"), "name": (client.get("name") if client_id else None) or name,
            "vip": bool(client.get("is_vip")),
            "rag": cf.get("CFMDERAG"), "cancel_risk": cf.get("CFCancelationRisk"),
            "health_reason": cf.get("CFHealthReason"), "next_step": cf.get("CFNextStep"),
            "sip_ticket": cf.get("CFSIPTicketMDE"),
            "sip_open": sips.get("open", 0), "sip_closed": sips.get("closed", 0),
            "service_line": cf.get("CFProduct"), "account_manager": account_manager,
        },
        "csat_stats": csat_stats, "csat_comments": csat,
        "nps_stats": nps_stats, "nps_comments": nps,
        "historical_calls": historical_calls,
        "action_items": [], "decks": decks, "transcripts": tx,
    }
    # Reuse cached AI when LLM inputs are unchanged (skips Grok + avoids score drift).
    prev_ai = None
    cache = DATA / f"{slugify(name)}.json"
    if cache.exists() and not force_ai:
        try:
            prev_ai = json.loads(cache.read_text(encoding="utf-8")).get("ai")
        except (ValueError, OSError):
            prev_ai = None
    data["ai"] = ai.analyze(data, cached_ai=prev_ai, force=force_ai)
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
    # The AI-Driven Operational Intelligence dashboard is data-driven (renders from
    # data/_overview.json, no embedded array). When index.html has neither the BEGIN/END
    # block nor the `const partners = [` anchor, there is nothing to inject — skip
    # gracefully. The partner JSONs this script just wrote still feed _index.json and the
    # _overview.json rollup (build_overview.py, the final sync step).
    if begin not in html and open_marker not in html:
        print("  index.html is data-driven (no embedded partner array) — skipping "
              "exec-row injection; the dashboard reads data/_overview.json.", file=sys.stderr)
        return
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
    force_ai = "--force-ai" in sys.argv
    only = {a.lower() for a in sys.argv[1:] if a.lower() != "--force-ai"}
    targets = [n for n in NEW if not only or slugify(n[0]) in only]
    warn_unmatched_transcript_dirs()
    print(f"Fetching TeamGPS NPS set once...", file=sys.stderr)
    nps_all = teamgps.get_nps_all()
    print(f"  {len(nps_all)} NPS responses cached", file=sys.stderr)

    built = 0
    skipped = 0
    for name, cid, hs, tg in targets:
        print(f"\n=== {name} (Halo {cid}) ===", file=sys.stderr)
        data = build_real(name, cid, hs, tg, nps_all, force_ai=force_ai)
        if data is None:                       # wrong client_id / name mismatch -> skipped
            skipped += 1
            continue
        slug = slugify(name)
        (DATA / f"{slug}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        aih = data["ai"]
        print(f"  sources={data['meta']['sources']} | RAG={data['client']['rag']} "
              f"sip_open={data['client']['sip_open']} sip_closed={data['client']['sip_closed']}")
        print(f"  risk={aih.get('risk_score')} ({aih.get('risk_band')}) trend={aih.get('sentiment_trend')} "
              f"err={aih.get('_error')}")
        built += 1

    print(f"\nBuilt {built} real partner cache(s)"
          + (f"; skipped {skipped} (client-name mismatch)" if skipped else "")
          + ". The dashboard reads them via data/_index.json + data/_overview.json "
            "(run build_all --reindex then build_overview.py).")


if __name__ == "__main__":
    main()
