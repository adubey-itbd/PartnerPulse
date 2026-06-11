"""Orchestrator — build one partner's unified data cache (Data-Extraction SOP §6).

Usage:
    python -m extract.build_partner "Logically"
    python -m extract.build_partner "Logically" --no-decks

Emits data/{slug}.json in the dashboard's PARTNER_DATA schema, plus deck PDFs +
Markdown under data/decks/. Bulk ticket SLA/status is intentionally not pulled.

`action_items` is left empty here — structured action extraction from the meeting
notes/decks is the job of the AI layer (next phase), which reads this JSON.
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone

from . import config, halo, teamgps, transcripts
from .partners import get as get_partner


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _client_block(client: dict, cf: dict, account_manager: str, sips: dict) -> dict:
    return {
        "id": client.get("id"),
        "name": client.get("name"),
        "vip": bool(client.get("is_vip")),
        "rag": cf.get("CFMDERAG"),
        "cancel_risk": cf.get("CFCancelationRisk"),
        "health_reason": cf.get("CFHealthReason"),
        "next_step": cf.get("CFNextStep"),
        "sip_ticket": cf.get("CFSIPTicketMDE"),
        "sip_open": sips.get("open", 0),
        "sip_closed": sips.get("closed", 0),
        "service_line": cf.get("CFProduct"),
        "account_manager": account_manager,
    }


def build(partner_name: str, with_decks: bool = True, verbose: bool = True,
          nps_all: list = None) -> dict:
    p = get_partner(partner_name)
    log = (lambda *a: print(*a, file=sys.stderr)) if verbose else (lambda *a: None)

    # 1. Resolve client id ----------------------------------------------------
    client_id = p.client_id
    if not client_id:
        client_id, resolved = halo.resolve_client_id(p.halo_search)
        log(f"[resolve] {p.name!r} -> client_id={client_id} ({resolved})")
        if not client_id:
            raise RuntimeError(f"Could not resolve Halo client_id for {p.name!r}")

    # 2. Client detail + custom fields ---------------------------------------
    client = halo.get_client(client_id)
    cf = halo.parse_custom_fields(client)
    log(f"[client] {client.get('name')} | RAG={cf.get('CFMDERAG')} "
        f"risk={cf.get('CFCancelationRisk')}")

    # 3. Users -> emails / domains -------------------------------------------
    emails, domains = halo.get_users(client_id)
    log(f"[users] {len(emails)} emails, domains={sorted(domains)}")

    # SIP (Service Improvement Plan, ticket type 99) counts — own record plus
    # SIPs filed under ITBD's record that name the partner in the summary.
    sips = halo.count_sips(client_id, name_terms=[p.name, p.halo_search])
    log(f"[sips] open={sips['open']} closed={sips['closed']}")

    # 4. CSAT -----------------------------------------------------------------
    csat = teamgps.get_csat(p.teamgps_company)
    csat_stats = teamgps.csat_stats(csat)
    log(f"[csat] {len(csat)} reviews {csat_stats}")

    # 5. NPS (fetch all, filter local) ---------------------------------------
    if nps_all is None:
        nps_all = teamgps.get_nps_all()
    nps = teamgps.filter_nps(nps_all, emails, domains)
    nps_stats = teamgps.nps_stats(nps)
    log(f"[nps] {len(nps)}/{len(nps_all)} after filter {nps_stats}")

    # 6-7. Service tickets -> notes + decks -----------------------------------
    historical_calls, decks = [], []
    note_authors = Counter()
    for t in halo.find_service_tickets(client_id, search=p.ticket_search):
        tid = t["id"]
        notes = halo.get_meeting_notes(tid)
        for n in notes:
            note_authors[n.get("who")] += 1
        if notes:
            historical_calls.append({
                "ticket_id": tid,
                "summary": t["summary"],
                "date": t["date"],
                "notes": "\n\n".join(n["note"] for n in notes),
            })
        if with_decks:
            for a in halo.list_attachments(tid):
                fn = (a.get("filename") or "").lower()
                ext = fn.rsplit(".", 1)[-1] if "." in fn else ""
                if a.get("id") and ext in ("pdf", "pptx"):
                    try:
                        raw = halo.download_attachment(a["id"])
                        deck = transcripts.deck_to_markdown(
                            raw, f"{slugify(p.name)}_{tid}_{a['id']}", ext=ext)
                        decks.append({
                            "ticket_id": tid, "attachment_id": a["id"],
                            "filename": a.get("filename"),
                            "md_path": deck["md_path"], "markdown": deck["markdown"],
                        })
                        log(f"[deck] {a.get('filename')} -> {len(deck['markdown'])} md chars")
                    except Exception as e:
                        log(f"[deck] FAILED {a.get('filename')}: {e}")
    log(f"[notes] {len(historical_calls)} calls with notes; {len(decks)} decks")

    # 8. Transcripts ----------------------------------------------------------
    tx = transcripts.parse_partner_transcripts(p.transcript_dir)
    log(f"[transcripts] {len(tx)} files, "
        f"{sum(len(t['dialogue']) for t in tx)} dialogue turns")

    # account manager heuristic: the ITBD lead who authors the review notes
    account_manager = (note_authors.most_common(1)[0][0] + " (Dedicated Team Lead)"
                       if note_authors else
                       client.get("accountmanagertech") or "")

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "partner": p.name,
            "sources": {
                "csat": len(csat), "nps": len(nps), "calls": len(historical_calls),
                "decks": len(decks), "transcripts": len(tx),
            },
        },
        "client": _client_block(client, cf, account_manager, sips),
        "csat_stats": csat_stats,
        "csat_comments": csat,
        "nps_stats": nps_stats,
        "nps_comments": nps,
        "historical_calls": historical_calls,
        "action_items": [],            # populated by the AI layer (next phase)
        "decks": decks,
        "transcripts": tx,
    }


def main():
    ap = argparse.ArgumentParser(description="Build a partner data cache.")
    ap.add_argument("partner", help="Partner name (see extract/partners.py)")
    ap.add_argument("--no-decks", action="store_true", help="Skip deck download/convert")
    args = ap.parse_args()

    data = build(args.partner, with_decks=not args.no_decks)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = config.DATA_DIR / f"{slugify(args.partner)}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out}  ({out.stat().st_size:,} bytes)")
    print("Sources:", json.dumps(data["meta"]["sources"]))


if __name__ == "__main__":
    main()
