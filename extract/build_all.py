"""Build every partner + AI insight + the consolidated portfolio index.

    python -m extract.build_all            # all partners, with decks + AI
    python -m extract.build_all --no-ai    # skip the gpt-5.4 pass
    python -m extract.build_all --no-decks

Writes data/{slug}.json (each with an `ai` block) and data/_index.json (the
roll-up consumed by the portfolio dashboard).
"""
import argparse
import json
import sys
import traceback

from . import ai, config, portfolio, teamgps
from .build_partner import build, slugify
from .partners import PARTNERS


def write_index(all_data, error_rows=None):
    """Write data/_index.json: per-partner rows (sorted by risk) + portfolio
    aggregate block. `all_data` is the list of full per-partner data dicts."""
    rows = [index_row(d) for d in all_data] + list(error_rows or [])
    rows.sort(key=lambda r: (r.get("risk_score") is None, -(r.get("risk_score") or 0)))
    payload = {"partners": rows, "portfolio": portfolio.build(all_data)}
    (config.DATA_DIR / "_index.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows


def _csat_positive_pct(stats: dict) -> float:
    total = sum(stats.values()) or 1
    return round(stats.get("Positive", 0) / total * 100, 1)


def index_row(data: dict) -> dict:
    c = data.get("client", {})
    aih = data.get("ai", {}) or {}
    return {
        # Slug MUST match the per-partner filename, which is slugify(registry name)
        # i.e. meta.partner — NOT the Halo client name (they can differ, e.g.
        # "MSPCorp" file vs "MSP Corp" client name).
        "slug": slugify(data.get("meta", {}).get("partner") or c.get("name")),
        "name": c.get("name"),
        "client_id": c.get("id"),
        "rag": c.get("rag"),
        "cancel_risk": c.get("cancel_risk"),
        "service_line": c.get("service_line"),
        "vip": c.get("vip"),
        "sip_ticket": c.get("sip_ticket"),
        "sip_open": c.get("sip_open", 0),
        "sip_closed": c.get("sip_closed", 0),
        "account_manager": c.get("account_manager"),
        "csat_positive_pct": _csat_positive_pct(data.get("csat_stats", {})),
        "csat_total": sum(data.get("csat_stats", {}).values()),
        "nps_promoters": data.get("nps_stats", {}).get("Promoter", 0),
        "nps_detractors": data.get("nps_stats", {}).get("Detractor", 0),
        "risk_score": aih.get("risk_score"),
        "risk_band": aih.get("risk_band"),
        "sentiment_trend": aih.get("sentiment_trend"),
        "summary": aih.get("summary"),
        "sources": data.get("meta", {}).get("sources", {}),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--force-ai", action="store_true",
                    help="re-run gpt-5.4 even when inputs are unchanged (default: reuse cached AI)")
    ap.add_argument("--no-decks", action="store_true")
    ap.add_argument("--only", nargs="*", help="limit to these partner names")
    ap.add_argument("--reindex", action="store_true",
                    help="rebuild data/_index.json from existing per-partner JSONs (no fetch)")
    args = ap.parse_args()

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.reindex:
        # Index EVERY per-partner cache in data/ — registry partners and the
        # extras built by scripts/build_real_partners.py alike (skip _index.json
        # and other _-prefixed artifacts).
        all_data = []
        for f in sorted(config.DATA_DIR.glob("*.json")):
            if f.name.startswith("_"):
                continue
            all_data.append(json.loads(f.read_text(encoding="utf-8")))
        rows = write_index(all_data)
        print(f"Reindexed {len(rows)} partners (+ portfolio aggregates)")
        return
    targets = PARTNERS
    if args.only:
        wanted = {n.lower() for n in args.only}
        targets = [p for p in PARTNERS if p.name.lower() in wanted]

    # Fetch the full NPS set ONCE and reuse for every partner's local filter.
    print("Fetching full NPS set once…", file=sys.stderr)
    nps_all = teamgps.get_nps_all()
    print(f"  {len(nps_all)} NPS responses cached", file=sys.stderr)

    all_data, error_rows = [], []
    for p in targets:
        print(f"\n=== {p.name} ===", file=sys.stderr)
        try:
            data = build(p.name, with_decks=not args.no_decks, nps_all=nps_all)
            out = config.DATA_DIR / f"{slugify(p.name)}.json"
            if not args.no_ai:
                # Reuse the cached AI result when the LLM inputs are unchanged (skips the
                # gpt-5.4 call + avoids score drift); --force-ai re-runs regardless.
                prev_ai = None
                if out.exists() and not args.force_ai:
                    try:
                        prev_ai = json.loads(out.read_text(encoding="utf-8")).get("ai")
                    except (ValueError, OSError):
                        prev_ai = None
                data["ai"] = ai.analyze(data, cached_ai=prev_ai, force=args.force_ai)
                print(f"  risk: {data['ai'].get('risk_score')} "
                      f"({data['ai'].get('risk_band')})"
                      f"{' [cached]' if data['ai'].get('_cached') else ' [gpt-5.4]'}", file=sys.stderr)
            out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            all_data.append(data)
        except Exception as e:
            print(f"  FAILED {p.name}: {e}", file=sys.stderr)
            traceback.print_exc()
            error_rows.append({"slug": slugify(p.name), "name": p.name, "error": str(e)})

    rows = write_index(all_data, error_rows)
    print(f"\nWrote {config.DATA_DIR / '_index.json'} with {len(rows)} partners "
          f"(+ portfolio aggregates)", file=sys.stderr)
    print(json.dumps([{"name": r.get("name"), "risk": r.get("risk_score"),
                       "band": r.get("risk_band")} for r in rows], indent=2))


if __name__ == "__main__":
    main()
