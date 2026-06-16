"""Publish the dashboard data to Cloud Firestore — the sharded layer.

All dashboard data lives in Firestore (see docs/Firebase-Deploy-SOP.md). This
script derives the document tree from data/_overview.json (which already honours
the demo allowlist) + the per-partner data/<slug>.json caches:

    meta/overview                     { generated_at, as_of, coverage, portfolio }
    partners/<slug>                   summary doc (powers the Exec Overview)
    partners/<slug>/detail/profile    { meta, client, ai, csat_stats, nps_stats }
    partners/<slug>/transcripts/<i>   one doc per call transcript
    partners/<slug>/decks/<i>         one doc per converted deck
    partners/<slug>/calls/<i>         one doc per service-review note (historical_calls)
    partners/<slug>/csat/<i>          one doc per CSAT comment
    partners/<slug>/nps/<i>           one doc per NPS response
    partners/<slug>/actions/<i>       one doc per action item

Each detail doc carries an `_i` field = its index in the source list, so the
dashboard restores the original order via orderBy('_i'). Doc ids are the
zero-padded index, which makes the upload idempotent and reconcilable: per
subcollection, docs beyond the current count are deleted, and partners no longer
in the feed are removed entirely (summary + profile + all subcollections).

Run AFTER a sync/build cycle, from the repo root:

    pip install google-cloud-firestore
    gcloud auth application-default login        # once, on the pipeline machine
    python scripts/upload_firebase_data.py --dry-run
    python scripts/upload_firebase_data.py

Project defaults to the .firebaserc "default" alias; override with --project.

Publish safety (atomicity)
--------------------------
The publish is made as close to all-or-nothing as Firestore batches allow:

  * Every per-partner blob and the feed itself are loaded + validated BEFORE any
    write — a corrupt/missing-keyed file aborts the whole run, untouched.
  * A SANITY GATE compares the new feed's partner count against the partners
    already in Firestore. If the count collapses (drop > PP_MAX_DROP_PCT, default
    20%) or the feed is empty, the run ABORTS before writing anything. This also
    guards the destructive stale-partner reconcile, so a thin/broken feed can
    never mass-delete the live roster.
  * meta/overview is written LAST, after every partner write has been flushed, so
    it behaves as a completion sentinel: if the run dies mid-way, the dashboard's
    freshness stamp still points at the previous, fully-consistent snapshot.

ROLLBACK: writes are not transactional across batches, so a crash *after* some
partner writes but *before* the meta/overview sentinel leaves the per-partner
docs partly updated while meta/overview still reflects the prior run. To recover,
simply re-run this script against the last-good build (restore data/ from the GCS
state bucket if needed) — the upload is idempotent (doc ids are zero-padded
indices; trailing docs are pruned; stale partners removed), so a clean re-run
fully reconciles Firestore back to the source feed.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_MAX_DROP_PCT = 20.0
_META_KEYS = ("generated_at", "as_of", "coverage", "portfolio")
_PROFILE_KEYS = ("meta", "client", "ai", "csat_stats", "nps_stats")
# Firestore subcollection -> source key in the per-partner blob.
_SECTIONS = {
    "transcripts": "transcripts",
    "decks": "decks",
    "calls": "historical_calls",
    "csat": "csat_comments",
    "nps": "nps_comments",
    "actions": "action_items",
}


def default_project():
    rc = ROOT / ".firebaserc"
    if rc.exists():
        try:
            return json.loads(rc.read_text(encoding="utf-8")).get("projects", {}).get("default")
        except (ValueError, OSError):
            pass
    return None


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def max_drop_pct():
    """Allowed shrink before the sanity gate aborts (env PP_MAX_DROP_PCT)."""
    raw = os.environ.get("PP_MAX_DROP_PCT")
    if not raw:
        return DEFAULT_MAX_DROP_PCT
    try:
        val = float(raw)
    except ValueError:
        print(f"  WARN: PP_MAX_DROP_PCT={raw!r} is not a number; using "
              f"{DEFAULT_MAX_DROP_PCT}")
        return DEFAULT_MAX_DROP_PCT
    if val < 0:
        print(f"  WARN: PP_MAX_DROP_PCT={raw!r} is negative; using "
              f"{DEFAULT_MAX_DROP_PCT}")
        return DEFAULT_MAX_DROP_PCT
    return val


def validate_feed(feed):
    """Return a clean partners list or raise ValueError on a bad feed."""
    if not isinstance(feed, dict):
        raise ValueError("feed is not a JSON object")
    missing = [k for k in _META_KEYS if feed.get(k) in (None, "")]
    if missing:
        raise ValueError(f"feed missing/empty meta keys: {', '.join(missing)}")
    if not str(feed.get("generated_at") or "").strip():
        raise ValueError("feed has no generated_at timestamp")
    partners = [p for p in feed.get("partners", []) if p.get("slug")]
    if not partners:
        raise ValueError("feed has no partners with a slug")
    return partners


def load_blobs(partners):
    """Load + validate every per-partner blob up front (fail-fast, no writes).

    Returns {slug: blob-or-None}; None means the cache file is legitimately
    absent (summary-only publish). A present-but-corrupt file aborts the run.
    """
    blobs = {}
    for p in partners:
        slug = p["slug"]
        blob_path = DATA / f"{slug}.json"
        if not blob_path.exists():
            blobs[slug] = None
            continue
        try:
            blob = load_json(blob_path)
        except (ValueError, OSError) as exc:
            raise ValueError(f"{blob_path.name} is unreadable/corrupt: {exc}")
        if not isinstance(blob, dict):
            raise ValueError(f"{blob_path.name} is not a JSON object")
        blobs[slug] = blob
    return blobs


def sanity_gate(new_count, existing_count, drop_pct):
    """Abort (return False) if the new feed collapses vs Firestore."""
    if new_count <= 0:
        print("  ABORT: new feed has zero partners - refusing to publish.")
        return False
    if existing_count <= 0:
        # Empty/first-run Firestore — nothing to lose, allow the publish.
        return True
    dropped = existing_count - new_count
    if dropped <= 0:
        return True
    pct = (dropped / existing_count) * 100.0
    if pct > drop_pct:
        print(f"  ABORT: partner count would drop {dropped} "
              f"({pct:.1f}%) from {existing_count} to {new_count}; "
              f"exceeds PP_MAX_DROP_PCT={drop_pct:.1f}%. Refusing to publish "
              f"(suspected thin/broken feed). Override via PP_MAX_DROP_PCT.")
        return False
    return True


class Batcher:
    """Auto-committing Firestore write batch (cap is 500 ops)."""

    def __init__(self, db):
        self.db = db
        self._b = db.batch()
        self._n = 0
        self.writes = 0
        self.deletes = 0

    def set(self, ref, data):
        self._b.set(ref, data)
        self.writes += 1
        self._tick()

    def delete(self, ref):
        self._b.delete(ref)
        self.deletes += 1
        self._tick()

    def _tick(self):
        self._n += 1
        if self._n >= 450:
            self.flush()

    def flush(self):
        if self._n:
            self._b.commit()
            self._b = self.db.batch()
            self._n = 0


def publish_partner(db, batch, summary, blob):
    slug = summary["slug"]
    base = db.collection("partners").document(slug)
    batch.set(base, summary)
    if blob is None:
        return
    batch.set(base.collection("detail").document("profile"),
              {k: blob.get(k) for k in _PROFILE_KEYS})
    for section, src in _SECTIONS.items():
        items = blob.get(src) or []
        coll = base.collection(section)
        keep = set()
        for i, item in enumerate(items):
            did = f"{i:04d}"
            keep.add(did)
            doc = dict(item)
            doc["_i"] = i
            batch.set(coll.document(did), doc)
        # Drop docs left over from a previous, longer list.
        for ref in coll.list_documents():
            if ref.id not in keep:
                batch.delete(ref)


def delete_partner(db, batch, slug):
    base = db.collection("partners").document(slug)
    for section in list(_SECTIONS) + ["detail"]:
        for ref in base.collection(section).list_documents():
            batch.delete(ref)
    batch.delete(base)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=default_project(),
                    help="Firebase/GCP project id (default: .firebaserc 'default')")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    args = ap.parse_args()
    if not args.project:
        sys.exit("no project - set .firebaserc default or pass --project")

    overview = DATA / "_overview.json"
    if not overview.exists():
        sys.exit(f"missing {overview} - run scripts/build_overview.py first")

    # Load + validate EVERYTHING before any write touches Firestore.
    try:
        feed = load_json(overview)
    except (ValueError, OSError) as exc:
        sys.exit(f"{overview.name} is unreadable/corrupt: {exc}")
    try:
        partners = validate_feed(feed)
        blobs = load_blobs(partners)
    except ValueError as exc:
        sys.exit(f"feed validation failed (nothing written): {exc}")

    drop_pct = max_drop_pct()

    if args.dry_run:
        print(f"Firestore ({args.project}) - DRY RUN")
        print(f"  meta/overview (written LAST, as completion sentinel)")
        for p in partners:
            slug = p["slug"]
            blob = blobs.get(slug)
            if blob is None:
                print(f"  partners/{slug}  (summary only - {slug}.json missing)")
                continue
            counts = {s: len(blob.get(src) or []) for s, src in _SECTIONS.items()}
            detail = " ".join(f"{s}={n}" for s, n in counts.items() if n)
            print(f"  partners/{slug}  + detail/profile  [{detail or 'no detail items'}]")
        print(f"  sanity gate: max drop {drop_pct:.1f}% (existing count checked "
              f"live at publish time)")
        print(f"{len(partners)} partner(s). Nothing written (dry run).")
        return

    from google.cloud import firestore

    db = firestore.Client(project=args.project)

    # SANITY GATE: don't publish (or reconcile) a feed that collapses the roster.
    existing = list(db.collection("partners").list_documents())
    existing_count = len(existing)
    if not sanity_gate(len(partners), existing_count, drop_pct):
        sys.exit(2)

    batch = Batcher(db)

    slugs = []
    for p in partners:
        slug = p["slug"]
        slugs.append(slug)
        blob = blobs.get(slug)
        if blob is None:
            print(f"  WARN: {slug}.json missing - writing summary only for {slug}")
        publish_partner(db, batch, p, blob)
        print(f"  + partners/{slug}")

    # Reconcile: remove partners no longer in the feed. Guarded by the same gate
    # above, so a thin feed can never reach this mass-delete.
    keep = set(slugs)
    stale = [d.id for d in existing if d.id not in keep]
    for sid in stale:
        delete_partner(db, batch, sid)
        print(f"  - partners/{sid} (stale, removed)")

    # Flush all partner writes/deletes BEFORE the sentinel so meta/overview only
    # advertises a fully-written snapshot.
    batch.flush()

    sentinel = Batcher(db)
    sentinel.set(db.collection("meta").document("overview"),
                 {k: feed.get(k) for k in _META_KEYS})
    sentinel.flush()

    print(f"done. {batch.writes + sentinel.writes} writes, {batch.deletes} "
          f"deletes across {len(slugs)} partner(s); {len(stale)} stale removed. "
          f"meta/overview sentinel written last.")


if __name__ == "__main__":
    main()
