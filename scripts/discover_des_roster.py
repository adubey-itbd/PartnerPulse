#!/usr/bin/env python
"""Auto-discover the DES/MDE partner roster from HaloPSA — the durable replacement
for hand-maintaining the dashboard's partner set.

WHY THIS EXISTS
---------------
The dashboard (`data/_demo_roster.json` allowlist) must mirror ITBD's DES/MDE book
of business — the same set as Halo **dashboard 1015 / report 364 "DES RAG Status"**.
Report rows aren't fetchable via the API (only the SQL definition is), so we
reproduce its filter — `Area.CFMDERAG >= 1`, i.e. every account with a DES RAG
health assigned — by enumerating clients and reading the custom field. That single
flag captures the vast majority automatically, so newly RAG-tagged partners appear
on the next run with **zero manual edits**.

A few report members carry no `CFMDERAG` (untagged in Halo) or have no Halo client
record at all; those can't be derived and live in `SUPPLEMENTAL` below with a
reason. Likewise a few rows must be dropped (duplicate Halo records, going-inactive
accounts) — `EXCLUDE_IDS`. Both lists are tiny and explicit; the 80+ common case is
fully automatic.

WHAT IT DOES
------------
1. Enumerates all Halo clients (`/api/Client`, `pageinate=true`) and reads
   `CFMDERAG` per client (detail call — there is no server-side CF filter).
2. Canonical roster = (active AND CFMDERAG>=1, minus EXCLUDE_IDS) + SUPPLEMENTAL.
3. Matches each canonical member to a built cache in `data/<slug>.json` (by Halo
   client id, or explicit slug for transcript-only members).
4. Reports drift: canonical partners with NO built cache (need a build), and any
   UNRESOLVED report names with neither a Halo record nor transcripts.
5. With `--write`, regenerates `data/_demo_roster.json` from the matched slugs.

    python scripts/discover_des_roster.py            # audit only (no changes)
    python scripts/discover_des_roster.py --write     # also rewrite the allowlist

Run it as part of (or right before) a sync: it keeps the allowlist honest and
flags any DES partner that still needs building. After it flags a NEEDS-BUILD
partner, add the one-line entry it prints to `scripts/build_real_partners.py` NEW,
build, then re-run this with --write.
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract import halo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Halo records to DROP from the auto set (duplicate records / going-inactive).
# Inactive clients are already filtered out; ids here are active ones we still drop.
EXCLUDE_IDS = {
    971,   # duplicate "TAB Computer Systems" record — canonical is 163
    1006,  # duplicate "Spidernet" record — canonical is 1003
    89,    # iStreet Solutions(20 MSP) — going inactive (per ops, 2026-06-15)
    81,    # InTelecom — inactive
}

# DES dashboard members Halo's CFMDERAG does NOT capture. Keep this list SMALL and
# always with a reason; prefer fixing the Halo data (set CFMDERAG) so the partner
# flows automatically and can be removed from here.
SUPPLEMENTAL = [
    {"id": 924, "slug": "etech-7-inc", "name": "ETech 7 Inc",
     "reason": "On DES dashboard 1015 but CFMDERAG untagged in Halo (=0)"},
    {"id": None, "slug": "ecs-consulting", "name": "ECS Consulting LLC",
     "reason": "No Halo client record; transcript-only build"},
]

# Report names we could NOT resolve to a Halo client OR local transcripts — they
# can't be built until ops provides a Halo client id (or onboards them in Halo).
UNRESOLVED = ["Evernet"]


def enumerate_clients():
    rows, seen = [], set()
    for pn in range(1, 200):
        page = halo._rows(halo.get("Client", page_size=100, page_no=pn,
                                   pageinate="true", includeinactive="true"))
        new = [c for c in page if c.get("id") not in seen]
        for c in new:
            seen.add(c.get("id"))
        rows.extend(new)
        if not new:
            break
    return rows


def cfmderag(client_id):
    """Raw numeric CFMDERAG code (1=Red..5=Hypercare Amber), or None.

    NOTE: halo.parse_custom_fields returns the human DISPLAY label ("Green"), not
    the code — `int("Green")` fails. Read the raw `value` straight off the detail
    object so the `>= 1` filter (report 364's actual SQL) works."""
    try:
        det = halo.get_client(client_id)
    except Exception:
        return None
    for cf in det.get("customfields") or []:
        if cf.get("name") == "CFMDERAG":
            return cf.get("value")
    return None


def built_caches():
    """Map Halo client id -> slug and slug set, from data/<slug>.json."""
    id2slug, slugs = {}, set()
    for f in glob.glob(os.path.join(DATA, "*.json")):
        b = os.path.basename(f)
        if b.startswith("_"):
            continue
        slug = b[:-5]
        slugs.add(slug)
        try:
            cid = (json.load(open(f, encoding="utf-8")).get("client") or {}).get("id")
        except (ValueError, OSError):
            cid = None
        if cid is not None:
            id2slug[cid] = slug
    return id2slug, slugs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="rewrite data/_demo_roster.json from the discovered set")
    args = ap.parse_args()

    print("Enumerating Halo clients + reading CFMDERAG (this hits ~880 detail calls)…",
          file=sys.stderr)
    clients = enumerate_clients()
    id2name = {c["id"]: c.get("name") for c in clients}

    # AUTO: active + CFMDERAG >= 1, minus explicit excludes.
    auto = {}
    for c in clients:
        cid = c.get("id")
        if c.get("inactive") or cid in EXCLUDE_IDS:
            continue
        v = cfmderag(cid)
        try:
            iv = int(v)
        except (TypeError, ValueError):
            iv = 0
        if iv >= 1:
            auto[cid] = c.get("name")

    id2slug, built_slugs = built_caches()

    # Canonical = auto (by id) + supplemental.
    canonical = []           # (id_or_None, name, slug_or_None, source)
    for cid, name in sorted(auto.items(), key=lambda kv: (kv[1] or "").lower()):
        canonical.append((cid, name, id2slug.get(cid), "auto (CFMDERAG>=1)"))
    for s in SUPPLEMENTAL:
        slug = s.get("slug") or (id2slug.get(s["id"]) if s.get("id") else None)
        canonical.append((s.get("id"), s["name"], slug, f"supplemental — {s['reason']}"))

    allow, needs_build = [], []
    for cid, name, slug, source in canonical:
        resolved = slug or (id2slug.get(cid) if cid else None)
        if resolved and resolved in built_slugs:
            allow.append(resolved)
        else:
            needs_build.append((cid, name, source))

    allow = sorted(set(allow))

    print(f"\n===== DES/MDE ROSTER DISCOVERY =====")
    print(f"auto (active, CFMDERAG>=1, minus excludes): {len(auto)}")
    print(f"supplemental: {len(SUPPLEMENTAL)}  |  excluded ids: {sorted(EXCLUDE_IDS)}")
    print(f"canonical roster: {len(canonical)}  |  built & allowlisted: {len(allow)}")

    if needs_build:
        print(f"\n[NEEDS BUILD] {len(needs_build)} DES partner(s) not yet in data/ — "
              f"add to build_real_partners.py NEW and build:")
        for cid, name, source in needs_build:
            term = re.sub(r"[^A-Za-z0-9 ]", "", (name or "").split("(")[0]).strip()[:18]
            print(f'    ("{name}", {cid}, "{term}", "{name}"),   # {source}')
    else:
        print("\n[OK] every canonical DES partner has a built cache.")

    if UNRESOLVED:
        print(f"\n[UNRESOLVED] {len(UNRESOLVED)} report name(s) with no Halo record or "
              f"transcripts — need a Halo client id from ops before they can be built:")
        for n in UNRESOLVED:
            print(f"    - {n}")

    if args.write:
        with open(os.path.join(DATA, "_demo_roster.json"), "w", encoding="utf-8") as fh:
            json.dump(allow, fh, indent=2)
        print(f"\nWrote data/_demo_roster.json: {len(allow)} slugs")
    else:
        print(f"\n(dry run — re-run with --write to regenerate data/_demo_roster.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
