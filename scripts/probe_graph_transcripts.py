"""Acceptance test for the Graph transcript app registration.

Probes the app registration from docs/IT-Request-Graph-Transcript-Access.md:
token (client credentials), then resolve a known meeting from its join URL and
fetch one transcript. Run after IT completes the provisioning
(scripts/setup_graph_transcript_access.ps1) to verify items 2-3 of the request:

    python scripts/probe_graph_transcripts.py

Expected once fully provisioned: token roles include OnlineMeetings.Read.All,
onlineMeetings 200, transcripts list 200 + content fetch 200 (needs the Teams
application access policy on the organizer accounts). Credentials come from
.env (GRAPH_* vars).

Gotcha (found 2026-06-12): app-only /users/{id}/onlineMeetings calls must
address the organizer by **object id** — addressing by UPN returns an empty
"404 UnknownError" even when the real failure is the missing access policy
(which reports properly as 403 "No application access policy found for this
app" when queried by object id). The organizer's object id is parsed from the
join URL's context parameter (Oid), so no User.Read.All permission is needed.
"""
import base64
import json
import sys
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract.config import _env

TENANT = _env("GRAPH_TENANT_ID")
CLIENT = _env("GRAPH_CLIENT_ID")
SECRET = _env("GRAPH_CLIENT_SECRET")
if not (TENANT and CLIENT and SECRET):
    sys.exit("GRAPH_TENANT_ID / GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET missing from .env")

r = requests.post(
    f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
    data={"client_id": CLIENT, "client_secret": SECRET,
          "scope": "https://graph.microsoft.com/.default",
          "grant_type": "client_credentials"}, timeout=30)
print("token request:", r.status_code)
if r.status_code != 200:
    print(r.json().get("error_description", r.text)[:500])
    sys.exit(1)
tok = r.json()["access_token"]
payload = tok.split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
print("app roles in token:", ", ".join(sorted(claims.get("roles", []))) or "(none)")
H = {"Authorization": f"Bearer {tok}"}

# Acceptance test: resolve the Atlantic PC 2026-05-22 meeting (organizer
# DESManagement — its object id is the Oid in the join URL context below),
# list transcripts, fetch content.
join = ("https://teams.microsoft.com/l/meetup-join/19%3ameeting_YjJmZTY1M2UtMDY5My00ZTNhLWE2ZjItMjI4OGNmOWJiOTky%40thread.v2/0"
        "?context=%7b%22Tid%22%3a%22d3ce7374-043d-42ad-9d54-b68633f244c9%22%2c%22Oid%22%3a%223f79ace1-8cf8-4033-9432-3e4243b3c8c8%22%7d")
oid = json.loads(urllib.parse.unquote(join.split("context=", 1)[1]))["Oid"]
print("organizer object id (from join URL):", oid)

m = requests.get(
    f"https://graph.microsoft.com/v1.0/users/{oid}/onlineMeetings",
    params={"$filter": f"JoinWebUrl eq '{join}'"}, headers=H, timeout=30)
print("onlineMeetings:", m.status_code)
if m.status_code != 200:
    print(" ", m.text[:300])
    sys.exit(1)
meetings = m.json().get("value", [])
print(f"  {len(meetings)} meeting(s)")
if not meetings:
    sys.exit(1)
mid = meetings[0]["id"]
t = requests.get(
    f"https://graph.microsoft.com/v1.0/users/{oid}/onlineMeetings/{mid}/transcripts",
    headers=H, timeout=30)
print("  transcripts list:", t.status_code)
if t.status_code == 200:
    items = t.json().get("value", [])
    print(f"  {len(items)} transcript(s)")
    if items:
        c = requests.get(
            f"https://graph.microsoft.com/v1.0/users/{oid}/onlineMeetings/{mid}/transcripts/{items[0]['id']}/content",
            params={"$format": "text/vtt"}, headers=H, timeout=60)
        print("  content fetch:", c.status_code, f"({len(c.text)} chars)")
        print("  first 200 chars:", c.text[:200].replace("\r\n", " | "))
else:
    print(" ", t.text[:300])
