"""Local dev server for the PartnerPulse dashboard.

Dependency-free (stdlib only). Serves the project directory — dashboard HTML/JS/CSS
plus the generated data/*.json — with no-cache headers so rebuilds show instantly.

    python server.py            # http://localhost:8000
    python server.py 8080       # custom port

For production this moves behind Firebase Hosting + Cloud Functions; this server is
only for local multi-partner testing.
"""
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".json": "application/json",
        ".js": "text/javascript",
        ".css": "text/css",
    }

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
