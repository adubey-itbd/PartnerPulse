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
    """GET /api/{path} as JSON, with retry/backoff for transient failures.

    Halo intermittently returns 5xx / 429 and the odd dropped connection; a
    single blip used to abort a whole multi-partner build (one 500 on /Tickets
    killed a 36-partner run). Retry transient errors a few times before raising,
    so callers only see a genuine, persistent failure."""
    url = f"{config.HALO_BASE_URL}/api/{path}"
    for attempt in range(5):
        try:
            r = requests.get(url, headers=_headers(), params=params, timeout=60)
        except requests.exceptions.RequestException:
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            time.sleep(float(r.headers.get("Retry-After", 1.5 * (attempt + 1))))
            continue
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
    # CSAT-reconciliation Site dimension (RAG tab): NDA / CDG / DL / PH.
    "CFAccountSite",
    # CSAT-reconciliation Product (MDE) dimension (RAG tab): Self-Managed / Co-Managed.
    "CFProductMDE",
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


def get_next_renewal(client_id: int) -> dict:
    """Contract-renewal facts for a client from /api/ClientContract. Partners carry many
    contract rows (one per service, staggered terms) plus a `2099-12-31` 'evergreen'
    sentinel, so this returns the ACTIVE, non-expired end_dates (excluding 2099 sentinels)
    sorted earliest-first, the active-contract count, and an evergreen flag. The caller
    (build_overview) picks the next upcoming date + days-to-renewal against 'today'.

    Returns {"end_dates": [YYYY-MM-DD, …], "active_contracts": int, "evergreen": bool}."""
    try:
        rows = _rows(get("ClientContract", client_id=client_id))
    except Exception:
        return {"end_dates": [], "active_contracts": 0, "evergreen": False}
    ends, active, evergreen = [], 0, False
    for r in rows:
        if not r.get("active") or r.get("expired"):
            continue
        active += 1
        ed = str(r.get("end_date") or "")[:10]
        if len(ed) != 10:
            continue
        try:
            year = int(ed[:4])
        except ValueError:
            continue
        if year >= 2099:                       # evergreen / no-end sentinel
            evergreen = True
            continue
        ends.append(ed)
    return {"end_dates": sorted(ends), "active_contracts": active, "evergreen": evergreen}


# --- Service Improvement Plans (ticket type 99) -----------------------------
# SIPs are a first-class Halo ticket type. There is NO working server-side type
# filter on /api/Tickets (every tickettype_* param is ignored), but each list
# ROW carries `tickettype_id`, so we narrow with the free-text `search` (which
# IS honoured) and filter the rows client-side.
SIP_TICKET_TYPE_ID = 99
_SIP_SEARCH_TERMS = ("SIP", "Service Improvement Plan", "Improvement Plan")

# Open vs closed is derived from the ticket's status name — Halo's Status objects
# expose no reliable `isclosed` flag. These are the terminal statuses.
_CLOSED_STATUS_NAMES = {
    "closed", "closed order", "closed item", "completed", "cancelled", "rejected",
    "resolved",   # a Resolved SIP is concluded, not active (e.g. RedHelm HD SIP)
}

# Generic words that appear in many MSP names and are useless (or actively
# harmful) as a partner-identifying SIP-summary token.
_NAME_STOPWORDS = {
    "the", "and", "inc", "llc", "ltd", "limited", "corp", "corporation",
    "company", "group", "holdings", "services", "service", "solutions",
    "solution", "systems", "system", "technology", "technologies", "tech",
    "cloud", "data", "digital", "global", "managed", "network", "networks",
    "computer", "computers", "consulting", "partners", "partner", "support",
    "improvement", "plan",
}


def _name_tokens(name_terms) -> list:
    """Distinct lower-cased identifying tokens from a partner's name term(s):
    word-split, drop tokens < 5 chars and generic stopwords. Used for
    bucket-B word-boundary SIP matching."""
    toks = []
    for term in name_terms:
        if not term:
            continue
        for w in re.split(r"[^a-z0-9]+", str(term).lower()):
            if len(w) >= 5 and w not in _NAME_STOPWORDS and w not in toks:
                toks.append(w)
    return toks


def fuzzy_name_match(expected: str, actual: str) -> bool:
    """Case/punctuation-insensitive token-overlap match between two names.

    Returns True when the two names plausibly refer to the same partner. Used
    by the roster build (build_real_partners) to detect a wrong client_id —
    i.e. when the Halo client name resolved for a partner does NOT look like the
    partner's expected name. Conservative: ignores short/generic stopword tokens
    and requires a meaningful overlap of the remaining identifying tokens."""
    def sig(s):
        return [w for w in re.split(r"[^a-z0-9]+", (s or "").lower())
                if len(w) >= 3 and w not in _NAME_STOPWORDS]
    a, b = sig(expected), sig(actual)
    if not a or not b:
        # Fall back to a normalized exact comparison when nothing meaningful
        # survives stopword filtering (e.g. very short names).
        na = re.sub(r"[^a-z0-9]+", "", (expected or "").lower())
        nb = re.sub(r"[^a-z0-9]+", "", (actual or "").lower())
        return bool(na) and na == nb
    sa, sb = set(a), set(b)
    overlap = sa & sb
    if not overlap:
        return False
    # Require the overlap to cover most of the smaller name's identifying tokens.
    return len(overlap) >= max(1, min(len(sa), len(sb)) - 1)


_status_names = None
_global_sips = None


def _status_name_map() -> dict:
    """{status_id: name}, fetched once."""
    global _status_names
    if _status_names is None:
        _status_names = {s.get("id"): (s.get("name") or "")
                         for s in _rows(get("Status"))}
    return _status_names


def _search_type99(seen: dict, **params):
    """Paginate /Tickets for the given params, keeping type-99 rows into `seen`."""
    for page in range(1, 12):
        rows = _rows(get("Tickets", page_size=100, page_no=page,
                         pageinate="true", **params))
        if not rows:
            break
        for r in rows:
            if r.get("tickettype_id") == SIP_TICKET_TYPE_ID:
                seen[r.get("id")] = r
        if len(rows) < 50:        # short page => last page for this query
            break


def _all_text_sips() -> list:
    """All type-99 tickets discoverable via the SIP free-text searches, fetched
    once and reused across partners (used to catch SIPs filed under ITBD's own
    client record with the partner named only in the summary)."""
    global _global_sips
    if _global_sips is None:
        seen = {}
        for term in _SIP_SEARCH_TERMS:
            _search_type99(seen, search=term)
        _global_sips = list(seen.values())
    return _global_sips


def _discover_sips(client_id: int, name_terms=(), sip_ticket_field=None) -> dict:
    """All of a partner's SIP tickets, de-duplicated by id -> {id: ticket_row}.

    Unions three buckets:
      A) type-99 SIPs filed under the partner's own Halo client record (`client_id`).
      B) type-99 SIPs filed under another record (typically ITBD's own) whose summary
         names the partner — matched against `name_terms`.
      C) the ticket(s) explicitly named in the partner's `CFSIPTicketMDE` custom field
         (`sip_ticket_field`). This is authoritative and catches SIPs the type-99 search
         misses — they aren't always type 99 (APM IT's SIP is type 148) and aren't always
         under this client record (RedHelm's are under another client). Fetched by id.
    """
    seen = {}

    # A) the partner's own client record (catches SIPs whose summary may not even
    #    mention the partner, e.g. "Service Improvement Plan - <agent name>").
    for term in _SIP_SEARCH_TERMS:
        _search_type99(seen, client_id=client_id, search=term)

    # B) SIPs filed elsewhere that name the partner in the summary.
    #    Match WHOLE words only (\b...\b) and ignore short/generic fragments,
    #    so a partner whose name contains a common word (e.g. "IT", "Cloud",
    #    "Tech", "Group") doesn't swallow every unrelated SIP that mentions it.
    toks = _name_tokens(name_terms)
    if toks:
        pat = re.compile(
            r"\b(?:" + "|".join(re.escape(t) for t in toks) + r")\b", re.I)
        for r in _all_text_sips():
            if r.get("id") in seen or r.get("client_id") == client_id:
                continue
            summ = r.get("summary") or ""
            if pat.search(summ):
                seen[r.get("id")] = r

    # C) tickets named in the SIP custom field — fetch each by id (any type/client).
    if sip_ticket_field:
        for tid in {int(m) for m in re.findall(r"\d{4,}", str(sip_ticket_field))}:
            if tid in seen:
                continue
            try:
                t = get(f"Tickets/{tid}")
            except Exception:
                continue
            if t and t.get("id"):
                seen[t["id"]] = t
    return seen


def _count_sip_rows(rows) -> dict:
    """Split discovered SIP rows into open vs closed by terminal status name."""
    names = _status_name_map()
    open_n = closed_n = 0
    for r in rows:
        nm = names.get(r.get("status_id"), "").strip().lower()
        if nm in _CLOSED_STATUS_NAMES:
            closed_n += 1
        else:
            open_n += 1
    return {"open": open_n, "closed": closed_n}


def count_sips(client_id: int, name_terms=(), sip_ticket_field=None) -> dict:
    """All-time SIP counts for a partner, split open vs closed, de-duplicated by id.
    See `_discover_sips` for the three buckets unioned."""
    return _count_sip_rows(
        _discover_sips(client_id, name_terms, sip_ticket_field).values())


# A SIP ticket's substantive write-ups (the SDM's weekly progress updates and the
# initial action plan) are filed as PRIVATE notes (hiddenfromuser=True). Halo's
# /api/Actions LIST endpoint silently OMITS private notes, so they are invisible to
# the bulk fetch — they are only retrievable by fetching each action by id. Within a
# ticket the action `id` is a 1-based sequence, so we walk 1..max(+buffer) and keep
# the notes that read like SIP progress write-ups (not the SLA/status-change noise).
_SIP_NOTE_MARKERS = ("sip progress", "service improvement action plan", "utilization",
                     "governance review", "ticket closure", "parameter compliance",
                     "overall status")
_SIP_NOTE_SEQ_BUFFER = 6      # private notes can sit just past the last visible action
_SIP_NOTE_SEQ_CAP = 150       # hard runaway guard
# Capture the engineer name on the SAME line only ([ \t], not \s) — the notes read
# "Engineer: Mazid\nReporting Manager: …", so \s+ would wrongly swallow "Reporting".
_SIP_ENGINEER_RE = re.compile(r"Engineer:[ \t]*([A-Za-z][\w'.\-]*(?:[ \t]+[A-Za-z][\w'.\-]*)?)", re.I)


def _sip_ticket_notes(ticket_id: int) -> list:
    """A SIP ticket's progress-update notes (newest first), INCLUDING private notes
    (the LIST hides them, so each action is fetched by its 1-based id). Each item:
    {action_id, who, datetime, note}."""
    body = get("Actions", ticket_id=ticket_id)
    listed = body.get("actions") if isinstance(body, dict) else _rows(body)
    max_seq = max((a.get("id") or 0 for a in (listed or [])), default=0)
    notes = []
    for seq in range(1, min(max_seq + _SIP_NOTE_SEQ_BUFFER, _SIP_NOTE_SEQ_CAP) + 1):
        try:
            d = get(f"Actions/{seq}", ticket_id=ticket_id)
        except Exception:
            continue
        if not isinstance(d, dict) or not d.get("id"):
            continue
        note = clean_html(d.get("note") or "")
        if len(note) >= 40 and any(m in note.lower() for m in _SIP_NOTE_MARKERS):
            notes.append({"action_id": d.get("id"), "who": d.get("who"),
                          "datetime": d.get("datetime"), "note": note})
    notes.sort(key=lambda n: n.get("datetime") or "", reverse=True)
    return notes


def _sip_status_label(name: str):
    """Map a Halo SIP status NAME to a simplified (label, class) for the dashboard
    badge: ('On Hold','hold') | ('Closed'/'Resolved'/…, 'closed') | ('Open','open')."""
    low = (name or "").lower()
    if "hold" in low:
        return "On Hold", "hold"
    if low in _CLOSED_STATUS_NAMES:
        return (name.title() if name else "Closed"), "closed"
    return "Open", "open"


def _sip_subject(raw_summary: str, notes: list) -> str:
    """A short label for a SIP. Prefer the engineer named in the notes
    ('Engineer: Mazid' -> 'Mazid SIP'); else fall back to the ticket summary."""
    for n in notes:
        m = _SIP_ENGINEER_RE.search(n.get("note") or "")
        if m:
            return f"{m.group(1).strip()} SIP"
    return (raw_summary or "SIP").strip()


def analyze_sips(client_id: int, name_terms=(), sip_ticket_field=None) -> dict:
    """One-pass SIP read for a partner. Returns {open, closed, sips} where `sips` is
    one object PER SIP ticket — {ticket_id, subject, raw_summary, status,
    status_label, status_class, started, latest, updates[]} — grouped so the AI can
    summarize each SIP's journey and the dashboard can show it with a status badge.
    Active (open / on-hold) SIPs sort before closed ones; newest update first."""
    rows = _discover_sips(client_id, name_terms, sip_ticket_field)
    names = _status_name_map()
    counts = _count_sip_rows(rows.values())
    sips = []
    for r in rows.values():
        tid = r.get("id")
        if not tid:
            continue
        notes = _sip_ticket_notes(tid)
        label, cls = _sip_status_label(names.get(r.get("status_id"), "").strip())
        dts = [n["datetime"] for n in notes if n.get("datetime")]
        sips.append({
            "ticket_id": tid,
            "subject": _sip_subject(r.get("summary"), notes),
            "raw_summary": r.get("summary"),
            "status": names.get(r.get("status_id"), "").strip(),
            "status_label": label,
            "status_class": cls,
            "started": (min(dts) if dts else r.get("dateoccurred")) or "",
            "latest": (max(dts) if dts else r.get("dateoccurred")) or "",
            "updates": notes,
        })
    sips.sort(key=lambda s: s.get("latest") or "", reverse=True)   # newest first…
    sips.sort(key=lambda s: s["status_class"] == "closed")         # …active before closed
    return {"open": counts["open"], "closed": counts["closed"], "sips": sips}


# --- Monthly CSAT survey tickets (the "sent" side of CSAT reconciliation) ----
# ITBD's "DES CSAT Monthly" team raises one ticket per recipient per month; each
# is one CSAT *sent*. They live under three ticket types and their summary embeds
# the survey month ("Monthly Feedback for <Name> For The Month of <Month>"). As
# with SIPs (type 99) there is NO working server-side tickettype filter, but the
# free-text `search` IS honoured and narrows a client's tickets to the CSAT ones
# cheaply (~7 pages vs ~17 for a full sweep), so we search then keep the rows whose
# `tickettype_id` is one of the CSAT types. The TeamGPS response (the "received"
# side) joins back to these by `ticket_id` — see scripts/build_csat_recon.py.
CSAT_TICKET_TYPE_IDS = {36, 163, 164}
_CSAT_SEARCH = "Monthly Feedback"


def fetch_csat_tickets(client_id: int) -> list:
    """All monthly-CSAT survey tickets raised for a client, across all time.

    Returns list of {id, tickettype_id, summary, dateoccurred}. De-duplicated by
    id. The caller parses the survey month from the summary and windows by year
    (the summary month + dateoccurred year — see build_csat_recon)."""
    seen = {}
    for page in range(1, 30):
        rows = _rows(get("Tickets", client_id=client_id, search=_CSAT_SEARCH,
                         page_size=100, page_no=page, pageinate="true"))
        if not rows:
            break
        for r in rows:
            if r.get("tickettype_id") in CSAT_TICKET_TYPE_IDS:
                seen[r.get("id")] = {
                    "id": r.get("id"),
                    "tickettype_id": r.get("tickettype_id"),
                    "summary": r.get("summary") or "",
                    "dateoccurred": r.get("dateoccurred"),
                }
        if len(rows) < 100:        # short page => last page for this client
            break
    return list(seen.values())


# --- Users -> emails / domains ----------------------------------------------
# Free / consumer mail providers. A contact at one of these tells us nothing
# about which partner owns an NPS response (a stray @gmail.com contact would
# otherwise match EVERY partner that happens to have a gmail contact), so we
# never treat these as partner-owned domains.
FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "aol.com", "icloud.com", "me.com", "mac.com", "comcast.net", "verizon.net",
    "att.net", "sbcglobal.net", "btinternet.com", "protonmail.com", "proton.me",
    "gmx.com", "mail.com", "zoho.com", "yandex.com",
}


def get_users(client_id: int):
    """Return (emails:set, domains:set) for a client's contacts.

    Free / consumer mail domains (FREE_MAIL) are kept out of the `domains` set:
    a partner does not "own" gmail.com, so domain-based NPS attribution must
    only use genuine corporate domains. The contact's exact email is still
    returned in `emails` for an exact-match fallback."""
    rows = _rows(get("Users", client_id=client_id, page_size=1000,
                      pageinate="true", includeinactive="true"))
    emails, domains = set(), set()
    for u in rows:
        e = (u.get("emailaddress") or "").strip().lower()
        if e and "@" in e:
            emails.add(e)
            dom = e.split("@", 1)[1]
            if dom and dom not in FREE_MAIL:
                domains.add(dom)
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
