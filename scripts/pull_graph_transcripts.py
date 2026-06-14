"""Pull Teams meeting transcripts for partner service/review calls from the
DES calendar via the Graph app registration, saving them as .vtt files into
`Transcripts/{Partner}/` (the same location the manual exports live in).

This is the automated replacement for the by-hand Teams export + the
M365-connector pull (which 403'd for any call the connector user wasn't invited
to — see docs/Data-Extraction-SOP.md §1). The app identity
("DESManagement@itbd.net", client id in .env GRAPH_* vars) reads transcripts
for every meeting organized under the DES Teams identity, so it covers all
partner service calls regardless of who attended.

    python scripts/pull_graph_transcripts.py                 # DRY RUN — plan only, writes nothing
    python scripts/pull_graph_transcripts.py --write         # actually download + save
    python scripts/pull_graph_transcripts.py --since 2026-01-01 --write
    python scripts/pull_graph_transcripts.py --include-docx-folders --write   # also pull into folders that already hold manual .docx exports (double-ingest risk)

How it works:
  * Pages the DES calendar's /events (the onlineMeeting/joinUrl field is reliably
    populated there — /calendarView intermittently drops it).
  * Keeps only partner service / review / business-review calls (CALL_RE),
    dropping interviews / onboarding / internal meetings (EXCLUDE_RE).
  * Dedupes events to unique meeting *series* by join URL — a recurring series'
    transcripts endpoint returns the full back-catalogue in one call, each
    transcript tagged with its own createdDateTime.
  * Resolves each series by the organizer's OBJECT ID (parsed from the join
    URL's `Oid` context param — addressing by UPN returns a masking 404; see
    scripts/probe_graph_transcripts.py), lists transcripts, keeps those on/after
    --since, downloads each as text/vtt, and writes
    `Transcripts/{Partner}/{sanitized subject}-{YYYYMMDD}.vtt` with the
    `WEBVTT` + `NOTE title/date/duration` header extract/transcripts.py expects.

Content-retention limit (verified 2026-06-13): Teams keeps transcript CONTENT
for only ~90 days, even though the transcript object stays listed indefinitely.
So a series lists every occurrence back to 2024, but only the last ~3 months
fetch 200 — older ones 404 on /content (reported as "content expired (404)").
The first full pull (2026-06-13) recovered Apr–Jun cleanly; Jan–early-Mar were
all expired. Practically, run this monthly so nothing ages out.

Safety rails:
  * Idempotent: skips a transcript whose target .vtt already exists.
  * Per-date dedup: if a series has several transcript objects for the SAME day
    (split recordings), only the longest is written — one file per meeting, so
    the AI layer never double-counts a call.
  * By default SKIPS any partner folder that already contains manual .docx
    exports (MSPCorp, Stasmayer, Premier, …): their freeform-named .docx can't
    be date-matched, so auto-adding .vtt risks the double-ingestion bug that
    once mis-scored Milner. Those folders are listed at the end; pull them
    deliberately with --include-docx-folders after checking for overlap.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract import config
from extract.transcripts import resolve_partner_dir

GRAPH = "https://graph.microsoft.com/v1.0"
DES = "DESManagement@itbd.net"

# Partner service/review/business-review calls only.
CALL_RE = re.compile(r"(service call|service review|business review|\bMBR\b|\bQBR\b)", re.I)
# ...but never recruitment interviews, onboarding sessions, or internal syncs.
EXCLUDE_RE = re.compile(r"(interview|onboarding|stand ?up|huddle|internal|1:1|one[- ]?on[- ]?one)", re.I)

# Segments that are generic prefixes (ITBD's own side of the title), never the partner.
GENERIC_LEAD = {"itbd", "mde", "ph", "sbd", "nda", "it by design"}
# Trailing corporate suffixes stripped so 'Granite Networks Inc' -> 'Granite Networks'
# and 'Infopathways, Inc.' matches the existing 'Infopathways' folder.
CORP_SUFFIX_RE = re.compile(r",?\s+(inc\.?|llc|l\.l\.c\.?|corp\.?|co\.?|ltd\.?)$", re.I)
# Title separators: a literal '|' OR a standalone capital 'I' used as a pipe
# ('Prevare LLC I ITBD Service Call').
SEP_RE = re.compile(r"\s*\|\s*|\s+I\s+")

# display-name -> existing-folder overrides where stripping/normalising isn't enough.
PARTNER_ALIASES = {
    "msp corp": "MSPCorp",
    "realtime": "Realtime IT",
    "netgain technology": "Netgain",
    # ---- 2026-06-14: meeting-subject short names → canonical roster folder, so the
    # pull routes into the existing partner folder instead of creating a fragmented
    # short-named one (the durable fix for the folder-mismatch found in the audit). ----
    "amoskeag": "Amoskeag Network Consulting Group LLC",
    "atlantic pc": "Atlantic PC Inc",
    "granite networks": "Granite Networks Inc",
    "granite": "Granite Networks Inc",
    "proda technology": "Proda Technologies",
    "proda": "Proda Technologies",
    "redhelm": "RedHelm - 1Path",
    "secure future tech": "Secure Future Tech Solutions",
    "secure future tech (sft)": "Secure Future Tech Solutions",
}

_TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.\d{3}\s+-->\s+(\d{2}):(\d{2}):(\d{2})\.\d{3}")


def token():
    r = requests.post(
        f"https://login.microsoftonline.com/{config._env('GRAPH_TENANT_ID')}/oauth2/v2.0/token",
        data={"client_id": config._env("GRAPH_CLIENT_ID"),
              "client_secret": config._env("GRAPH_CLIENT_SECRET"),
              "scope": "https://graph.microsoft.com/.default",
              "grant_type": "client_credentials"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def get(url, headers, **kw):
    """GET with retries for transient connection resets (WinError 10054) and
    Graph throttling (HTTP 429 / 503, honouring Retry-After)."""
    for attempt in range(5):
        try:
            r = requests.get(url, headers=headers, timeout=60, **kw)
        except requests.exceptions.RequestException:
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (429, 503) and attempt < 4:
            time.sleep(float(r.headers.get("Retry-After", 2 * (attempt + 1))))
            continue
        return r


def is_descriptor(seg: str) -> bool:
    """A segment that names the meeting type, not the partner."""
    return bool(CALL_RE.search(seg))


def partner_from_subject(subject: str) -> str:
    """Best-effort partner name (RAW, suffix intact): the first '|'/'I'-separated
    segment that is neither a generic ITBD-side prefix nor a meeting-type
    descriptor. Corporate-suffix handling is left to target_folder so an existing
    folder like 'Prevare LLC' still matches."""
    s = re.sub(r"^cancell?ed:\s*", "", subject, flags=re.I)
    s = re.sub(r"\*\*[^*]*\*\*", "", s)                  # drop "**New Evite**" noise
    segs = [p.strip() for p in SEP_RE.split(s) if p.strip()]
    for seg in segs:
        if seg.lower() in GENERIC_LEAD or is_descriptor(seg):
            continue
        return seg
    return segs[0] if segs else subject.strip()


def target_folder(partner_name: str):
    """Resolve to an existing Transcripts/ folder, else a NEW folder path.
    Matches existing folders against both the raw name and a corp-suffix-stripped
    variant ('Prevare LLC' matches as-is; 'Infopathways, Inc.' strips to
    'Infopathways'); new folders use the stripped name. Returns (path, is_new)."""
    stripped = CORP_SUFFIX_RE.sub("", partner_name).strip()
    for cand in (partner_name, stripped):
        alias = PARTNER_ALIASES.get(cand.lower())
        if alias:
            existing = resolve_partner_dir(alias)
            if existing:
                return existing, False
    for cand in (partner_name, stripped):
        existing = resolve_partner_dir(cand)
        if existing:
            return existing, False
    return config.TRANSCRIPTS_DIR / (stripped or partner_name), True


def sanitize(subject: str) -> str:
    s = re.sub(r"\*\*[^*]*\*\*", "", subject)
    s = s.replace("|", "_").replace(":", "-")
    s = re.sub(r"[<>\"/\\?*]+", "", s)
    s = re.sub(r"\s+", " ", s).strip(" _-")
    return s


def duration_from_vtt(body: str) -> str:
    last = None
    for m in _TIME_RE.finditer(body):
        last = m
    if not last:
        return ""
    h, mn, s = int(last.group(4)), int(last.group(5)), int(last.group(6))
    return (f"{h}h {mn}m {s}s" if h else f"{mn}m {s}s")


def build_vtt(subject: str, date: str, body: str) -> str:
    """Reattach our NOTE header to Graph's raw VTT cues."""
    lines = body.splitlines()
    while lines and (lines[0].strip().upper() == "WEBVTT" or not lines[0].strip()):
        lines.pop(0)
    cues = "\n".join(lines)
    header = (f"WEBVTT\nNOTE title: {subject}\nNOTE date: {date}\n"
              f"NOTE duration: {duration_from_vtt(body)}\n")
    return f"{header}\n{cues}\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01", help="ISO date; keep transcripts on/after this (default 2026-01-01)")
    ap.add_argument("--scan-from", default="2025-06-01", help="ISO date; how far back to scan the calendar for series (default 2025-06-01)")
    ap.add_argument("--write", action="store_true", help="actually download+write (default is a dry run)")
    ap.add_argument("--include-docx-folders", action="store_true", help="also write into folders that already contain manual .docx exports")
    args = ap.parse_args()

    H = {"Authorization": f"Bearer {token()}"}
    print(f"{'WRITE' if args.write else 'DRY RUN'} — since {args.since}, scanning calendar from {args.scan_from}\n")

    # 1. page the DES calendar's events
    events, url = [], f"{GRAPH}/users/{DES}/events"
    params = {"$top": "100", "$orderby": "start/dateTime desc",
              "$select": "subject,start,onlineMeeting"}
    while url:
        r = get(url, H, params=params); params = None
        j = r.json()
        events += j.get("value", [])
        if j.get("value") and j["value"][-1]["start"]["dateTime"][:10] < args.scan_from:
            break
        url = j.get("@odata.nextLink")
    print(f"scanned {len(events)} calendar events")

    # 2. filter to partner service calls, dedupe to unique series by join URL
    series = {}
    for e in events:
        subj = e.get("subject", "")
        if not CALL_RE.search(subj) or EXCLUDE_RE.search(subj):
            continue
        ju = (e.get("onlineMeeting") or {}).get("joinUrl")
        if not ju or "context=" not in ju or ju in series:
            continue
        try:
            oid = json.loads(urllib.parse.unquote(ju.split("context=", 1)[1])).get("Oid")
        except Exception:
            oid = None
        if oid:
            series[ju] = {"subject": subj, "oid": oid}
    print(f"{len(series)} unique partner service-call series\n")

    written = skipped = no_tx = errors = 0
    plan = {}
    docx_deferred = {}     # folder -> count of transcripts skipped for .docx safety
    resolve_errors = []

    for ju, meta in series.items():
        subj, oid = meta["subject"], meta["oid"]
        folder, is_new = target_folder(partner_from_subject(subj))
        has_docx = folder.is_dir() and any(folder.glob("*.docx"))

        m = get(f"{GRAPH}/users/{oid}/onlineMeetings", H,
                params={"$filter": f"JoinWebUrl eq '{ju}'"})
        if m.status_code != 200 or not m.json().get("value"):
            errors += 1
            resolve_errors.append((subj[:60], f"resolve {m.status_code}"))
            continue
        mid = m.json()["value"][0]["id"]
        t = get(f"{GRAPH}/users/{oid}/onlineMeetings/{mid}/transcripts", H)
        if t.status_code != 200:
            errors += 1
            resolve_errors.append((subj[:60], f"transcripts {t.status_code}"))
            continue
        items = t.json().get("value", [])
        if not items:
            no_tx += 1
            continue

        # group transcripts by occurrence date, keep only dates >= since
        by_date = defaultdict(list)
        for it in items:
            d = (it.get("createdDateTime") or "")[:10]
            if d and d >= args.since:
                by_date[d].append(it)
        if not by_date:
            continue

        if has_docx and not args.include_docx_folders:
            docx_deferred[folder.name] = docx_deferred.get(folder.name, 0) + len(by_date)
            continue

        base = sanitize(subj)
        tag = "NEW folder" if is_new else ""
        for d in sorted(by_date):
            fname = f"{base}-{d.replace('-', '')}.vtt"
            dest = folder / fname
            if dest.exists():
                skipped += 1
                plan.setdefault(folder.name, []).append((d, "skip (exists)", fname))
                continue
            if not args.write:
                note = f"WOULD WRITE {tag}".strip()
                if len(by_date[d]) > 1:
                    note += f" (longest of {len(by_date[d])})"
                plan.setdefault(folder.name, []).append((d, note, fname))
                written += 1
                continue
            # fetch every transcript for this date, keep the longest body
            best, last_status = "", None
            for it in by_date[d]:
                c = get(f"{GRAPH}/users/{oid}/onlineMeetings/{mid}/transcripts/{it['id']}/content",
                        H, params={"$format": "text/vtt"})
                last_status = c.status_code
                if c.status_code == 200 and len(c.text) > len(best):
                    best = c.text
            if not best.strip():
                # Teams retains transcript CONTENT ~90 days even though the
                # transcript object stays listed forever — older calls 404 here.
                errors += 1
                label = "content expired (404)" if last_status == 404 else f"content error ({last_status})"
                plan.setdefault(folder.name, []).append((d, label, fname))
                continue
            folder.mkdir(parents=True, exist_ok=True)
            dest.write_text(build_vtt(subj, d, best), encoding="utf-8")
            written += 1
            plan.setdefault(folder.name, []).append((d, f"WROTE {tag}".strip(), fname))

    # 3. report
    for fname in sorted(plan):
        print(f"\n{fname}")
        for d, action, fn in sorted(plan[fname]):
            print(f"   {d}  {action:28} {fn}")

    if docx_deferred:
        print(f"\n--- DEFERRED (folder already has manual .docx — pull with --include-docx-folders after checking overlap) ---")
        for f, n in sorted(docx_deferred.items()):
            print(f"   {f}: {n} dated transcript(s) not written")
    if resolve_errors:
        print(f"\n--- {len(resolve_errors)} series could not be read (mostly QBRs organized outside the DES identity) ---")
        for subj, why in resolve_errors:
            print(f"   {why:18} {subj}")

    verb = "written" if args.write else "to write"
    print(f"\n=== {written} {verb}, {skipped} skipped (exist), "
          f"{sum(docx_deferred.values())} deferred (.docx folders), "
          f"{no_tx} series w/o transcripts, {errors} errors ===")
    if not args.write:
        print("Dry run only — re-run with --write to download and save.")


if __name__ == "__main__":
    main()
