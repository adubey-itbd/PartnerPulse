#!/usr/bin/env python3
"""Cloud Run Job entrypoint — the full nightly data-refresh cycle, headless.

RETIRED (2026-06-18): this unattended cloud pipeline is no longer used. The AI
churn-analysis step now bills the operator's personal Claude subscription via the
Claude Agent SDK's local OAuth login (see extract/ai.py), and subscription auth is
for individual, interactive use — the Agent SDK cannot legitimately bill a personal
subscription from unattended cloud automation. The AI step therefore runs MANUALLY
on a laptop, and the cloud footprint is now HOSTING + Firestore SERVING ONLY. The
nightly Cloud Scheduler trigger should be disabled (e.g. `gcloud scheduler jobs
pause <job>`) and this Job retired; refresh data locally instead with
  python -m extract.build_all  ->  scripts/build_overview.py  ->  scripts/upload_firebase_data.py
This file is kept for reference / rollback only — the step logic is unchanged.

Runs the same pipeline the local "Sync Data" button used to drive, then
publishes the result to Cloud Firestore, all in one container:

  1. (optional) pull persisted state  ← gs://$STATE_BUCKET   (data/ + Transcripts/)
  2. pull_graph_transcripts --write    (Microsoft Graph → Transcripts/)
  3. extract.build_all                 (Halo + TeamGPS + docs + Claude, incremental)
  4. scripts/build_real_partners.py    (extra real Halo clients)
  5. extract.build_all --reindex       (data/_index.json)
  6. scripts/build_overview.py         (data/_overview.json — the dashboard feed)
  7. scripts/upload_firebase_data.py   (publish the sharded Firestore tree)
  8. (optional) push persisted state   → gs://$STATE_BUCKET

Why persist state: the pipeline is INCREMENTAL — the Claude churn analysis is
cached by input-hash so risk scores don't drift run-to-run (see CLAUDE.md), and
Teams only keeps transcript *content* ~90 days. A stateless container would
re-run the LLM for all partners every night (cost + drift) and lose older
transcripts. The state bucket (seeded once from the local caches) fixes both.

Steps 2-5 (transcripts, registry, real-extras, reindex) are continue-on-failure,
mirroring server.py's SYNC_STEPS: a transient Halo/Graph blip degrades coverage
for that run instead of aborting the night. Each soft step also has a per-step
timeout (SOFT_STEP_TIMEOUT_S, ~1500s); a timeout is treated as a soft failure
(logged, continue) so one stuck step can't hang the whole execution.

The 'overview' step (build_overview) is effectively REQUIRED: it builds the
dashboard feed, so if it fails we must NOT republish stale data as if it were
fresh. On overview failure we skip the hard upload and exit non-zero.

Steps 1, 6 (overview gate) and 7 are HARD — a failure there exits non-zero so the
Cloud Run execution is marked failed (and you get alerted) rather than silently
shipping a half-built or unpublished dataset. State is pushed BEFORE the hard
upload (and again after, in a finally) so freshly-pulled transcripts / AI caches
are never lost even if the publish fails.

Env:
  STATE_BUCKET            bucket name (with or without gs://) for persisted
                          state; unset → stateless (full rebuild each run).
  PARTNERPULSE_DATA       data dir (default ./data) — honoured by extract.config
  PARTNERPULSE_TRANSCRIPTS transcripts dir (default ./Transcripts)
  pipeline secrets        HALO_*, TEAMGPS_*, GRAPH_* — injected from
                          Secret Manager by the Cloud Run Job. (No AI secret: the
                          Claude Agent SDK bills the local subscription OAuth login,
                          which is unavailable in the cloud — another reason this
                          Job is retired.)
Firestore auth is the job's attached service account, resolved via ADC by
scripts/upload_firebase_data.py (project from .firebaserc).
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
STATE_BUCKET = os.environ.get("STATE_BUCKET", "").replace("gs://", "").strip("/ ")
DATA_DIR = os.environ.get("PARTNERPULSE_DATA", str(ROOT / "data"))
TRANSCRIPTS_DIR = os.environ.get("PARTNERPULSE_TRANSCRIPTS", str(ROOT / "Transcripts"))

# Per-soft-step timeout; mirrors server.py STEP_TIMEOUT_S (kept a touch lower so a
# stuck step is reaped before the Cloud Run Job's own wall-clock budget).
SOFT_STEP_TIMEOUT_S = 1500

# Cache-bust guard: if the pulled data/ has fewer than this many objects, assume
# the state pull was incomplete/corrupt and abort BEFORE building — otherwise the
# incremental Claude cache is effectively empty and we'd trigger a full cold
# re-run (cost + risk-score drift). A healthy data/ holds dozens of caches.
DATA_FLOOR = 10

# (id, command). Same order as server.py SYNC_STEPS. 'overview' is special-cased
# in main() (effectively required); the rest are soft (continue-on-fail).
SYNC_STEPS = [
    ("transcripts", [PY, str(ROOT / "scripts" / "pull_graph_transcripts.py"), "--write"]),
    ("registry",    [PY, "-m", "extract.build_all"]),
    ("real-extras", [PY, str(ROOT / "scripts" / "build_real_partners.py")]),
    ("reindex",     [PY, "-m", "extract.build_all", "--reindex"]),
    ("overview",    [PY, str(ROOT / "scripts" / "build_overview.py")]),
]

# step id -> return code (or sentinel), for the end-of-run RUN SUMMARY line.
RESULTS = {}


def run(cmd, *, hard, timeout=None):
    print(f"\n=== RUN {' '.join(str(c) for c in cmd)} (hard={hard}) ===", flush=True)
    try:
        rc = subprocess.run(cmd, cwd=str(ROOT), timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        msg = f"step TIMED OUT after {timeout}s: {' '.join(str(c) for c in cmd)}"
        if hard:
            raise SystemExit("FATAL " + msg)
        print("WARN: " + msg + " - continuing", flush=True)
        return 124  # conventional timeout return code; soft failure
    if rc != 0:
        msg = f"step exit {rc}: {' '.join(str(c) for c in cmd)}"
        if hard:
            raise SystemExit("FATAL " + msg)
        print("WARN: " + msg + " - continuing", flush=True)
    return rc


# --- Cloud Storage state sync (pure Python; no gcloud CLI needed) -------------
def _bucket():
    from google.cloud import storage
    return storage.Client().bucket(STATE_BUCKET)


def pull_state():
    bucket = _bucket()
    counts = {}
    for prefix, dest in (("data", DATA_DIR), ("Transcripts", TRANSCRIPTS_DIR)):
        Path(dest).mkdir(parents=True, exist_ok=True)
        n = 0
        for blob in bucket.list_blobs(prefix=prefix + "/"):
            rel = blob.name[len(prefix) + 1:]
            if not rel or blob.name.endswith("/"):
                continue
            out = Path(dest) / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(out))
            n += 1
        counts[prefix] = n
        print(f"  pulled {n} object(s) from gs://{STATE_BUCKET}/{prefix} -> {dest}", flush=True)
    return counts


def _push_prefix(bucket, src, prefix, *, prune):
    """Upload local files under src to gs://bucket/prefix. If prune, also delete
    bucket objects under the prefix that no longer exist locally (mirror
    deletions). Returns (uploaded, deleted)."""
    src_path = Path(src)
    if not src_path.exists():
        return 0, 0
    local = set()
    n = 0
    for f in src_path.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src_path).as_posix()
            local.add(rel)
            bucket.blob(f"{prefix}/{rel}").upload_from_filename(str(f))
            n += 1
    deleted = 0
    if prune:
        for blob in bucket.list_blobs(prefix=prefix + "/"):
            rel = blob.name[len(prefix) + 1:]
            if not rel or blob.name.endswith("/"):
                continue
            if rel not in local:
                blob.delete()
                deleted += 1
    return n, deleted


def push_state():
    bucket = _bucket()
    # data/ is pruned (mirror deletions so orphan caches don't accumulate);
    # Transcripts/ is append-only (Teams ages content out, so keep our archive).
    for src, prefix, prune in (
        (DATA_DIR, "data", True),
        (TRANSCRIPTS_DIR, "Transcripts", False),
    ):
        n, deleted = _push_prefix(bucket, src, prefix, prune=prune)
        extra = f", pruned {deleted} orphan(s)" if prune else " (append-only)"
        print(f"  pushed {n} file(s) from {src} -> gs://{STATE_BUCKET}/{prefix}{extra}",
              flush=True)


def main():
    if STATE_BUCKET:
        print(f"== state: gs://{STATE_BUCKET} ==", flush=True)
        counts = pull_state()
        # Cache-bust guard: an implausibly small data/ means the pull was
        # incomplete; building now would cold-start the whole Claude cache.
        data_n = counts.get("data", 0)
        if data_n < DATA_FLOOR:
            raise SystemExit(
                f"FATAL aborting before build: pulled only {data_n} data/ object(s) "
                f"(< floor {DATA_FLOOR}). State pull looks incomplete; refusing to "
                f"trigger a full cold Claude re-run / score drift.")
    else:
        print("== stateless run (STATE_BUCKET unset) ==", flush=True)

    overview_ok = True
    for _id, cmd in SYNC_STEPS:
        rc = run(cmd, hard=False, timeout=SOFT_STEP_TIMEOUT_S)
        RESULTS[_id] = rc
        if _id == "overview" and rc != 0:
            overview_ok = False

    # Push state BEFORE the hard upload (and before any abort) so freshly-pulled
    # transcripts + AI caches are persisted even if the publish never happens or
    # fails. Wrapped so a state-push hiccup never masks the real outcome.
    pushed = False
    if STATE_BUCKET:
        try:
            push_state()
            pushed = True
        except Exception as e:
            print(f"WARN: pre-upload push_state failed: {e}", flush=True)

    try:
        # The 'overview' step is effectively required: without a fresh feed we'd
        # publish stale data as if it were current. Gate the upload on it.
        if not overview_ok:
            RESULTS["upload"] = "skipped"
            raise SystemExit(
                "FATAL build_overview failed - refusing to publish stale data as "
                "fresh; skipping Firestore upload. Exiting non-zero.")

        # Publishing to Firestore is the whole point of the job. Capture the rc
        # (don't auto-raise) so the RUN SUMMARY always reflects the outcome, then
        # fail hard if it didn't publish.
        rc = run([PY, str(ROOT / "scripts" / "upload_firebase_data.py")], hard=False)
        RESULTS["upload"] = rc
        if rc != 0:
            raise SystemExit(f"FATAL Firestore upload failed (exit {rc}).")
    finally:
        # Belt-and-suspenders: if the pre-upload push failed, try once more so we
        # never discard the run's freshly-pulled transcripts / AI caches.
        if STATE_BUCKET and not pushed:
            try:
                push_state()
            except Exception as e:  # state push must never mask the real error
                print(f"WARN: fallback push_state failed: {e}", flush=True)
        # Always emit the machine-greppable run summary, even on a failure path.
        _summary()

    print("\n=== nightly sync complete ===", flush=True)


def _summary():
    parts = [f"{k}={RESULTS[k]}" for k in
             ["transcripts", "registry", "real-extras", "reindex", "overview", "upload"]
             if k in RESULTS]
    print("\nRUN SUMMARY: " + " ".join(parts), flush=True)


if __name__ == "__main__":
    main()
