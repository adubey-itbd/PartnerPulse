"""HaloPSA client (read-only).

Implements the Halo half of the Data-Extraction SOP:
  - OAuth2 client_credentials token (cached, auto-refresh)
  - Client detail + custom fields (RAG, cancel risk, health reason, next step, SIP)
  - Client users -> email + domain sets (for TeamGPS NPS filtering)
  - Bi-weekly service-call ticket search -> actions -> cleaned meeting notes
  - Attachment listing + download (the service-review deck PDFs)

Deliberately does NOT pull bulk ticket SLA/status data: for ITBD's white-label
NOC model those are end-customer ticket metrics, not partner-churn signals, and
the relevant KPIs are already distilled in the review decks/notes.
"""
import re
import time
import requests

from . import config

_token = None
_token_exp = 0.0


def _get_token() -> str:
    global _token, _token_exp
    if _token and time.time() < _token_exp - 60:
        return _token
    r = requests.post(
        f"{config.HALO_BASE_URL}/auth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": config.HALO_CLIENT_ID,
            "client_secret": config.HALO_CLIENT_SECRET,
            "scope": config.HALO_SCOPE,
        },
        timeout=40,
    )
    r.raise_for_status()
    j = r.json()
    _token, _token_exp = j["access_token"], time.time() + j["expires_in"]
    return _token


def _headers(accept="application/json") -> dict:
    return {"Authorization": f"Bearer {_get_token()}", "Accept": accept}


def get(path: str, **params):
    """GET /api/{path} as JSON."""
    r = requests.get(f"{config.HALO_BASE_URL}/api/{path}", headers=_headers(),
                     params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def _rows(body):
    """Robustly extract the data array per SOP: bare list -> itself; dict ->
    first value that is a non-empty list of dicts."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for v in body.values():
            if isinstance(v, list) and (not v or isinstance(v[0], dict)):
                return v
    return []


# --- HTML cleaning (SOP §5) --------------------------------------------------
_TAG_RE = re.compile(r"<.*?>", re.S)


def clean_html(raw: str) -> str:
    if not raw:
        return ""
    txt = re.sub(_TAG_RE, "", raw)
    txt = (txt.replace("&nbsp;", " ").replace("&lt;", "<")
              .replace("&gt;", ">").replace("&amp;", "&").replace("&#39;", "'"))
    return txt.strip()


# --- Clients -----------------------------------------------------------------
_CF_KEYS = {
    "CFCancelationRisk", "CFMDERAG", "CFHealthReason", "CFNextStep",
    "CFSIPTicketMDE", "CFProduct",
}


def resolve_client_id(search: str):
    """Find a client_id by name substring search. Returns (id, name) of the best
    (shortest-name, active) match, or (None, None)."""
    rows = _rows(get("Client", search=search, includeinactive="false", page_size=50))
    rows = [c for c in rows if not c.get("inactive")] or rows
    if not rows:
        return None, None
    # Prefer an exact (case-insensitive) name match, else the shortest name.
    exact = [c for c in rows if c.get("name", "").lower() == search.lower()]
    pick = (exact or sorted(rows, key=lambda c: len(c.get("name", ""))))[0]
    return pick.get("id"), pick.get("name")


def get_client(client_id: int) -> dict:
    """Client detail incl. customfields[]. Returns the raw Halo client object."""
    return get(f"Client/{client_id}", includedetails="true")


def parse_custom_fields(client: dict) -> dict:
    """Pull the churn-relevant custom fields into a flat dict keyed by CF name."""
    out = {}
    for cf in client.get("customfields") or []:
        name = cf.get("name")
        if name in _CF_KEYS:
            # `display` is the human label of the value; `value` the raw code.
            out[name] = cf.get("display") if cf.get("display") not in (None, "") else cf.get("value")
    return out


# --- Users -> emails / domains ----------------------------------------------
def get_users(client_id: int):
    """Return (emails:set, domains:set) for a client's contacts."""
    rows = _rows(get("Users", client_id=client_id, page_size=1000,
                      pageinate="true", includeinactive="true"))
    emails, domains = set(), set()
    for u in rows:
        e = (u.get("emailaddress") or "").strip().lower()
        if e and "@" in e:
            emails.add(e)
            domains.add(e.split("@", 1)[1])
    return emails, domains


# --- Service-review tickets, actions, meeting notes (SOP §5) -----------------
_NOTE_MARKERS = ("meeting summary", "action items", "discussion points", "join the call")


def find_service_tickets(client_id: int, search="Service Call", limit=5):
    """Recent service-review tickets for a client (capped). Returns list of
    {id, summary, date}."""
    rows = _rows(get("Tickets", client_id=client_id, search=search,
                     page_size=limit, pageinate="true"))
    out = []
    for t in rows[:limit]:
        out.append({
            "id": t.get("id"),
            "summary": t.get("summary"),
            "date": t.get("dateoccurred") or t.get("lastactiondate"),
        })
    return out


def get_meeting_notes(ticket_id: int):
    """Fetch all actions for a ticket, pull full detail, clean HTML, and return
    the action note(s) that look like a meeting write-up."""
    actions = _rows(get("Actions", ticket_id=ticket_id))
    notes = []
    for a in actions:
        aid = a.get("id")
        if aid is None:
            continue
        detail = get(f"Actions/{aid}", ticket_id=ticket_id)
        cleaned = clean_html(detail.get("note") or "")
        low = cleaned.lower()
        if cleaned and any(m in low for m in _NOTE_MARKERS):
            notes.append({
                "action_id": aid,
                "who": detail.get("who"),
                "datetime": detail.get("datetime"),
                "note": cleaned,
            })
    return notes


# --- Attachments (deck PDFs) -------------------------------------------------
def list_attachments(ticket_id: int):
    """Metadata for a ticket's attachments. Each: {id, filename, filesize, type,
    isimage}."""
    body = get("Attachment", ticket_id=ticket_id)
    rows = body.get("attachments", []) if isinstance(body, dict) else _rows(body)
    return [
        {k: a.get(k) for k in ("id", "filename", "filesize", "type", "isimage", "note")}
        for a in rows
    ]


def download_attachment(attachment_id: int) -> bytes:
    """Raw bytes of an attachment.

    Halo serves attachments two ways depending on where the file is stored:
      1. Inline  — `GET /api/Attachment/{id}` returns the raw bytes directly
         (octet-stream), e.g. the smaller PDF decks.
      2. CDN     — the same call returns JSON `{"link": "<pre-signed CDN URL>"}`
         and the real bytes must be fetched from that (already-authenticated)
         link with a second GET. Larger PPTX decks come this way.
    This handles both transparently.
    """
    r = requests.get(f"{config.HALO_BASE_URL}/api/Attachment/{attachment_id}",
                     headers=_headers("application/octet-stream"), timeout=120)
    r.raise_for_status()
    body = r.content
    ctype = r.headers.get("content-type", "").lower()
    if "json" in ctype or body[:8].lstrip().startswith(b'{"link"'):
        try:
            link = r.json().get("link")
        except ValueError:
            link = None
        if link:
            r2 = requests.get(link, timeout=180)   # pre-signed URL; no auth header
            r2.raise_for_status()
            return r2.content
    return body
