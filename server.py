"""Local dev server for the PartnerPulse dashboard.

Dependency-free (stdlib only). Serves the project directory — dashboard HTML/JS/CSS
plus the generated data/*.json — with no-cache headers so rebuilds show instantly.

Also exposes a manual data-sync API used by the dashboard's "Sync Data" button:

    POST /api/refresh           start a sync cycle (409 if one is already running);
                                optional JSON body {"steps": ["step-id", ...]} runs a subset
    GET  /api/refresh/status    JSON progress: per-step status + log tail

The sync cycle shells out to the existing pipeline entry points (one subprocess per
step, sequential, continue-on-failure) and appends output to data/_sync.log.

    python server.py            # http://localhost:8000
    python server.py 8080       # custom port

For production this moves behind Firebase Hosting + Cloud Functions; this server is
only for local multi-partner testing.
"""
import json
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
    {"id": "registry",
     "label": "Registry partners — full rebuild (Halo + TeamGPS + docs + AI)",
     "cmd": [sys.executable, "-m", "extract.build_all"]},
    {"id": "real-extras",
     "label": "Additional real partners + exec-overview injection",
     "cmd": [sys.executable, str(ROOT / "scripts" / "build_real_partners.py")]},
    {"id": "reindex",
     "label": "Portfolio index regeneration",
     "cmd": [sys.executable, "-m", "extract.build_all", "--reindex"]},
]


class SyncManager:
    """Single-flight runner for the sync cycle; state is poll-friendly JSON."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {"status": "idle", "result": None, "started_at": None,
                       "finished_at": None, "steps": [], "log_tail": []}

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

    def _run(self, steps):
        self._log(f"=== sync cycle started ({len(steps)} steps) ===")
        ok_count = 0
        for i, step in enumerate(steps):
            self._set_step(i, status="running")
            self._log(f"step {i + 1}/{len(steps)}: {step['label']}")
            try:
                proc = subprocess.run(
                    step["cmd"], cwd=str(ROOT), capture_output=True, text=True,
                    timeout=STEP_TIMEOUT_S)
                tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
                for line in tail[-8:]:
                    self._log(f"  {line}")
                if proc.returncode == 0:
                    ok_count += 1
                    self._set_step(i, status="ok")
                else:
                    self._set_step(i, status="failed",
                                   detail=(tail[-1] if tail else f"exit {proc.returncode}"))
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
