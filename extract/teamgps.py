"""TeamGPS Open API client.

CSAT and NPS extraction per the Data-Extraction SOP. Two schema quirks:
  - CSAT results live under  data.results  and DO support a `company` filter.
  - NPS  results live under  data.data  and have NO server-side company filter,
    so the full set is pulled once and filtered locally by the client's contact
    emails / domains (from halo.get_users).
"""
import requests

from . import config

_HEADERS = {"X-API-KEY": config.TEAMGPS_API_KEY, "Accept": "application/json"}


def _get(path: str, **params):
    r = requests.get(f"{config.TEAMGPS_BASE_URL}/{path.lstrip('/')}",
                     headers=_HEADERS, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


# --- CSAT (server-side company filter; data.results) -------------------------
def get_csat(company: str):
    """All CSAT reviews for a company. Returns list of normalized review dicts."""
    out, page = [], 1
    while True:
        body = _get("csat/", company=company, page_size=1000, page=page)
        data = body.get("data", {}) or {}
        rows = data.get("results", []) or []
        for r in rows:
            out.append({
                "id": r.get("id"),
                "rating": r.get("rating"),                 # Positive/Neutral/Negative ('' until answered)
                "comment": r.get("comment"),
                "contact": r.get("contact_name"),
                "contact_email": r.get("contact_email"),
                "date": r.get("submitted_date"),
                "ticket_id": r.get("ticket_id"),
                "ticket_name": r.get("ticket_name"),
                # The /csat endpoint returns sent surveys too — a not-yet-answered one
                # has is_responded=false (empty rating/comment, null submitted_date).
                # Carry the flag so consumers can count only real responses.
                "is_responded": r.get("is_responded"),
            })
        if page >= (data.get("total_pages") or 1):
            break
        page += 1
    return out


def csat_stats(reviews: list) -> dict:
    """Counts by rating bucket (matches dashboard's csat_stats shape)."""
    stats = {"Positive": 0, "Neutral": 0, "Negative": 0, "Unrated": 0}
    for r in reviews:
        rating = (r.get("rating") or "").capitalize()
        stats[rating if rating in stats else "Unrated"] += 1
    return stats


# --- NPS (no company filter; data.data; filter locally) ----------------------
def get_nps_all():
    """Every NPS-client response (paginated). Returns raw normalized dicts incl.
    respondent_email for local filtering."""
    out, page = [], 1
    while True:
        body = _get("survey/nps-client/", page_size=1000, page=page)
        data = body.get("data", {}) or {}
        rows = data.get("data", []) or []
        for r in rows:
            out.append({
                "id": r.get("id"),
                "score": r.get("nps_score"),
                "category": r.get("nps_category"),         # Promoter/Passive/Detractor
                "comment": r.get("comment"),
                "respondent": (r.get("respondent_email") or "").strip().lower(),
                "respondent_name": r.get("respondent_name"),
                "respondent_email": (r.get("respondent_email") or "").strip().lower(),
                "campaign": r.get("campaign_name"),
                "date": r.get("submitted_date"),
            })
        pg = data.get("pagination", {}) or {}
        if page >= (pg.get("total_pages") or 1):
            break
        page += 1
    return out


def _dominant_domains(emails: set, domains: set):
    """The partner's DOMINANT corporate domain(s): among the contact emails,
    the most-common domain(s) that are in `domains` (already free-mail-filtered
    by halo.get_users). Returns a set (ties keep all leaders). Empty when the
    partner has no resolvable corporate domain (e.g. all contacts on free mail).

    Domain-based NPS attribution must use only the dominant corporate domain(s)
    rather than every stray contact domain: a single contact who happens to use
    another company's domain (e.g. a leftover @milner.com address on Perfect
    Cloud's record) would otherwise cross-attribute that company's NPS."""
    counts = {}
    for e in emails:
        if "@" in e:
            dom = e.split("@", 1)[1]
            if dom in domains:
                counts[dom] = counts.get(dom, 0) + 1
    if not counts:
        return set()
    top = max(counts.values())
    return {d for d, n in counts.items() if n == top}


def filter_nps(all_nps: list, emails: set, domains: set):
    """Keep NPS responses whose respondent belongs to this partner.

    Matches on the partner's DOMINANT corporate domain(s) (the most common
    non-free domain among contacts) plus an exact contact-email fallback. When
    no corporate domain is resolvable (all contacts on free mail), falls back to
    exact email match only — this avoids both the gmail N-way over-count and
    stray-contact cross-attribution between partners."""
    dom_set = _dominant_domains(emails, domains)
    out = []
    for r in all_nps:
        e = r.get("respondent_email") or ""
        dom = e.split("@", 1)[1] if "@" in e else ""
        if e in emails or (dom and dom in dom_set):
            out.append(r)
    return out


def nps_stats(reviews: list) -> dict:
    cats = {"Promoter": 0, "Passive": 0, "Detractor": 0}
    for r in reviews:
        c = r.get("category")
        if c in cats:
            cats[c] += 1
    return cats
