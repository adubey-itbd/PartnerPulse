"""Re-render partners' executive-overview rows in index.html from their built
data/{slug}.json caches.

Companion to scripts/build_real_partners.py: its inject_exec only manages the
BEGIN/END marker block, but the registry partners' rows live in the static part
of the embedded array — a full sync rebuilds their caches without ever touching
those rows, so the two frontend data layers drift apart. This script replaces a
row by slug wherever it sits (static or managed block) so a refreshed partner
never ends up duplicated; a partner with a cache but no row yet is appended
into the managed block.

    python scripts/refresh_exec_row.py <slug>           # one partner, cache must exist
    python scripts/refresh_exec_row.py --all            # every data/*.json cache
                                                        # (sync-cycle step "exec-rows")
    python scripts/refresh_exec_row.py --remove <slug>  # delete a partner's row
                                                        # (offboarding; cache not needed)

Single-partner refresh recipe:
    python -m extract.build_all --only Milner     # rebuild the cache first
    python -m extract.build_all --reindex         # restore the full index
    python scripts/refresh_exec_row.py milner     # then refresh the exec row
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.build_real_partners import to_exec_obj, exec_object_js, inject_exec, DATA, EXEC


def row_pattern(slug):
    # An exec row spans from its `{ name:` line (slug is on that same line)
    # to its closing `callsAnalyzed: N },` line.
    return re.compile(
        r"^        \{ name: [^\n]*slug: %s,.*?callsAnalyzed: \d+ \},"
        % re.escape(json.dumps(slug)), re.S | re.M)


def load_exec_obj(cache: Path) -> dict:
    obj = to_exec_obj(json.loads(cache.read_text(encoding="utf-8")))
    obj["slug"] = cache.stem  # cache filename is authoritative (slug != slugified name for some)
    return obj


def refresh(objs):
    """Replace each object's row in place; collect & inject the ones with no row."""
    html = EXEC.read_text(encoding="utf-8")
    replaced, new = 0, []
    for obj in objs:
        pattern = row_pattern(obj["slug"])
        if pattern.search(html):
            html = pattern.sub(lambda m, o=obj: exec_object_js(o), html, count=1)
            replaced += 1
        else:
            new.append(obj)
    EXEC.write_text(html, encoding="utf-8")
    if new:
        inject_exec(new)  # re-reads index.html, appends into the managed block
    return replaced, new


def remove(slug):
    html = EXEC.read_text(encoding="utf-8")
    # Consume the row plus one trailing blank line so no double gap is left.
    pattern = re.compile(row_pattern(slug).pattern + r"\n(\r?\n)?", re.S | re.M)
    if not pattern.search(html):
        sys.exit(f"no exec-overview row with slug {slug!r} in {EXEC.name}")
    EXEC.write_text(pattern.sub("", html, count=1), encoding="utf-8")
    print(f"Removed exec-overview row for {slug!r} from {EXEC.name}")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--remove":
        remove(sys.argv[2])
        return
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/refresh_exec_row.py <slug>|--all|--remove <slug>")
    if sys.argv[1] == "--all":
        caches = [f for f in sorted(DATA.glob("*.json")) if not f.name.startswith("_")]
        if not caches:
            sys.exit(f"no partner caches in {DATA}")
        replaced, new = refresh([load_exec_obj(f) for f in caches])
        print(f"Refreshed {replaced} exec-overview rows from {len(caches)} caches"
              + (f"; appended {len(new)} new ({', '.join(o['slug'] for o in new)})"
                 if new else ""))
        return
    slug = sys.argv[1]
    cache = DATA / f"{slug}.json"
    if not cache.is_file():
        sys.exit(f"no cache at {cache} — build the partner first")
    replaced, new = refresh([load_exec_obj(cache)])
    print(f"Replaced exec-overview row for {slug!r} in {EXEC.name}" if replaced
          else f"No existing row for {slug!r} — appended into the managed block")


if __name__ == "__main__":
    main()
