"""Local dev server for the PartnerPulse dashboard.

Dependency-free (stdlib only). Serves the project directory — dashboard HTML/JS/CSS
plus the generated data/*.json — with no-cache headers so rebuilds show instantly.

Also exposes a manual data-sync API used by the dashboard's "Sync Data" button:

    POST /api/refresh           start a sync cycle (409 if one is already running);
                                optional JSON body {"steps": ["step-id", ...]} runs a subset
    GET  /api/refresh/status    JSON progress: per-step status + live `activity`
                                (current pipeline phase, e.g. "Logically: syncing
                                TeamGPS CSAT") + log tail

The sync cycle shells out to the existing pipeline entry points (one subprocess per
step, sequential, continue-on-failure), streams their output line-by-line into
data/_sync.log, and translates the pipeline's tagged phase lines into the live
activity shown by the dashboard's sync progress panel.

    python server.py            # http://localhost:8000
    python server.py 8080       # custom port

For production this moves behind Firebase Hosting + Cloud Functions; this server is
only for local multi-partner testing.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SYNC_LOG = ROOT / "data" / "_sync.log"
STEP_TIMEOUT_S = 1800  # per step; full registry rebuild runs ~5 min normally

# The manual sync cycle, in order. Steps run sequentially and independently —
# a failed step is reported but does not stop the rest (e.g. build_all needs
# markitdown, which some machines lack; the other steps still refresh Halo/
# TeamGPS data and the portfolio index).
SYNC_STEPS = [
    {"id": "transcripts",
     "label": "Pull call transcripts (app-only Graph → Transcripts/)",
     "cmd": [sys.executable, str(ROOT / "scripts" / "pull_graph_transcripts.py"), "--write"]},
    {"id": "registry",
     "label": "Registry partners — full rebuild (Halo + TeamGPS + docs + AI)",
     "cmd": [sys.executable, "-m", "extract.build_all"]},
    {"id": "real-extras",
     "label": "Additional real partners (extra Halo clients + transcript-only)",
     "cmd": [sys.executable, str(ROOT / "scripts" / "build_real_partners.py")]},
    {"id": "reindex",
     "label": "Portfolio index regeneration",
     "cmd": [sys.executable, "-m", "extract.build_all", "--reindex"]},
    {"id": "overview",
     "label": "Operational-intelligence feed (data/_overview.json ← caches)",
     "cmd": [sys.executable, str(ROOT / "scripts" / "build_overview.py")]},
]

# Live-activity translation: the build scripts emit one tagged stderr line per
# extraction phase (see extract/build_partner.py `log(...)` calls). Each tag
# maps to the human-readable activity the dashboard's sync button shows while
# that phase runs. Unknown lines simply don't change the activity.
TAG_ACTIVITY = {
    "resolve": "syncing HaloPSA client record",
    "client": "syncing HaloPSA client record",
    "users": "syncing HaloPSA contacts",
    "sips": "syncing HaloPSA SIP tickets",
    "notes": "syncing HaloPSA call notes",
    "deck": "converting QBR decks",
    "csat": "syncing TeamGPS CSAT",
    "nps": "syncing TeamGPS NPS",
    "transcripts": "syncing call transcripts",
}
PARTNER_LINE = re.compile(r"^=== (.+?)(?: \(Halo \d+\))? ===$")
TAG_LINE = re.compile(r"^\[(\w+)\]")


def parse_activity(line: str, ctx: dict):
    """Map one pipeline output line to a dashboard activity string (or None).

    ctx carries the current partner name between lines (the scripts print
    `=== Partner ===` once, then tagged phase lines for that partner).
    """
    line = line.strip()
    m = PARTNER_LINE.match(line)
    if m:
        ctx["partner"] = m.group(1)
        return f"{ctx['partner']}: syncing HaloPSA client record"
    if "NPS set once" in line:
        return "syncing TeamGPS NPS (portfolio-wide fetch)"
    if "churn analysis" in line:
        partner = ctx.get("partner")
        return (f"{partner}: " if partner else "") + "running AI churn analysis (Claude)"
    if line.startswith("Reindexed"):
        return "portfolio index rebuilt"
    if line.startswith("Wrote") and "_overview" in line:
        return "rebuilding operational-intelligence feed"
    if line.startswith("WRITE —") or line.startswith("scanned "):
        return "pulling call transcripts from Graph"
    m = TAG_LINE.match(line)
    if m and m.group(1) in TAG_ACTIVITY:
        partner = ctx.get("partner")
        activity = TAG_ACTIVITY[m.group(1)]
        return f"{partner}: {activity}" if partner else activity
    return None


class SyncManager:
    """Single-flight runner for the sync cycle; state is poll-friendly JSON."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {"status": "idle", "result": None, "started_at": None,
                       "finished_at": None, "activity": None, "steps": [],
                       "log_tail": []}

    def status(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._state))  # deep copy

    def start(self, step_ids=None) -> bool:
        with self._lock:
            if self._state["status"] == "running":
                return False
            steps = [s for s in SYNC_STEPS if not step_ids or s["id"] in step_ids]
            self._state = {
                "status": "running", "result": None,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "finished_at": None,
                "activity": "starting…",
                "steps": [{"id": s["id"], "label": s["label"], "status": "pending",
                           "detail": None} for s in steps],
                "log_tail": [],
            }
        threading.Thread(target=self._run, args=(steps,), daemon=True).start()
        return True

    def _log(self, line: str):
        stamped = f"[{time.strftime('%H:%M:%S')}] {line}"
        with self._lock:
            self._state["log_tail"] = (self._state["log_tail"] + [stamped])[-40:]
        try:
            SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
            with SYNC_LOG.open("a", encoding="utf-8") as f:
                f.write(stamped + "\n")
        except OSError:
            pass

    def _set_step(self, i: int, **kw):
        with self._lock:
            self._state["steps"][i].update(kw)

    def _set_activity(self, text):
        with self._lock:
            self._state["activity"] = text

    def _run_step(self, i: int, step: dict):
        """Run one step streaming its output: every line is logged as it
        arrives, and recognised pipeline phases update the step's `detail`
        + the top-level `activity` shown live by the dashboard. Returns
        (returncode, last_line); raises TimeoutExpired on the step timeout."""
        proc = subprocess.Popen(
            step["cmd"], cwd=str(ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", env={**os.environ, "PYTHONUNBUFFERED": "1"})
        timed_out = []
        killer = threading.Timer(
            STEP_TIMEOUT_S, lambda: (timed_out.append(True), proc.kill()))
        killer.start()
        ctx, last = {}, ""
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line.strip():
                    continue
                last = line.strip()
                self._log(f"  {line}")
                activity = parse_activity(line, ctx)
                if activity:
                    self._set_step(i, detail=activity)
                    self._set_activity(activity)
            returncode = proc.wait()
        finally:
            killer.cancel()
        if timed_out:
            raise subprocess.TimeoutExpired(step["cmd"], STEP_TIMEOUT_S)
        return returncode, last

    def _run(self, steps):
        self._log(f"=== sync cycle started ({len(steps)} steps) ===")
        ok_count = 0
        for i, step in enumerate(steps):
            self._set_step(i, status="running")
            self._set_activity(step["label"])
            self._log(f"step {i + 1}/{len(steps)}: {step['label']}")
            try:
                returncode, last = self._run_step(i, step)
                if returncode == 0:
                    ok_count += 1
                    self._set_step(i, status="ok", detail=None)
                else:
                    self._set_step(i, status="failed",
                                   detail=(last or f"exit {returncode}"))
            except subprocess.TimeoutExpired:
                self._set_step(i, status="failed", detail=f"timed out after {STEP_TIMEOUT_S}s")
                self._log("  TIMEOUT")
            except OSError as e:
                self._set_step(i, status="failed", detail=str(e))
                self._log(f"  ERROR: {e}")
        result = "ok" if ok_count == len(steps) else ("partial" if ok_count else "failed")
        self._log(f"=== sync cycle finished: {result} ({ok_count}/{len(steps)} steps ok) ===")
        with self._lock:
            self._state["status"] = "done"
            self._state["result"] = result
            self._state["activity"] = None
            self._state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")


SYNC = SyncManager()


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".json": "application/json",
        ".js": "text/javascript",
        ".css": "text/css",
    }

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/refresh/status":
            return self._send_json(SYNC.status())
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] == "/api/refresh":
            step_ids = None
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    step_ids = json.loads(self.rfile.read(length)).get("steps")
                except (ValueError, AttributeError):
                    return self._send_json({"error": "invalid JSON body"}, 400)
            if SYNC.start(step_ids):
                return self._send_json({"started": True}, 202)
            return self._send_json({"started": False, "error": "sync already running"}, 409)
        return self._send_json({"error": "not found"}, 404)

    def end_headers(self):
        # No caching during local development.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    handler = partial(Handler, directory=str(ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://localhost:{port}/"
    print(f"PartnerPulse dashboard serving at {url}")
    print(f"  Portfolio overview : {url}")
    print(f"  Partner detail     : {url}partner.html?partner=logically")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
