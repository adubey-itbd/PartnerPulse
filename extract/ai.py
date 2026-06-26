"""AI churn-analysis layer (Grok via Azure AI Foundry, OpenAI SDK).

Calls a Global Standard `grok-4-1-fast-reasoning` deployment over its synchronous
OpenAI-compatible endpoint (`config.AI_BASE_URL` + `config.AI_API_KEY`, model
`config.AI_MODEL`). Swapped from Azure Foundry gpt-5.4 on 2026-06-18 (that gpt-5.4
deployment is Batch-only and can't serve synchronous per-partner calls).

Consumes a partner's unified cache (the dict from build_partner.build) and returns
structured churn insight: a risk score + band, the drivers behind it, proactive
remediation, extracted action items, and sentiment trend. Designed to be merged
back into the partner JSON under the `ai` key and rolled up on the portfolio view.
"""
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta

from openai import OpenAI

from . import config

# Bump when the cached-result shape/semantics change so old caches are invalidated
# (a cached result whose `_schema_version` differs is treated as stale and re-run).
CACHE_SCHEMA_VERSION = 2

# Keys an AI result must carry to be considered a usable cached value.
_REQUIRED_KEYS = ("risk_score", "risk_band", "summary", "drivers",
                  "remediation", "action_items")

# Network hardening for the OpenAI client. max_retries is generous because the Grok
# deployment is rate-limited (50k TPM / 50 RPM) — the SDK backs off on 429s.
_REQUEST_TIMEOUT_S = 120
_MAX_RETRIES = 5
# Reasoning model: give the completion enough room for reasoning + the JSON payload.
_MAX_COMPLETION_TOKENS = 8000

# Rolling recency windows (relative to "today") for what the model ANALYZES — keeps the
# churn read current so resolved 2025 discussions/actions don't distort it:
#   - meetings within ANALYSIS_WINDOW_DAYS feed the churn/sentiment analysis;
#   - only meetings within ACTION_WINDOW_DAYS yield "open" action items (older meetings
#     are tagged HISTORICAL and used as background/trend context only).
# ROLLING (today - N), NOT a fixed calendar date, so freshness stays constant as the
# nightly job runs forever. A partner's prompt changes only when a meeting crosses a
# boundary or a new one arrives, so the incremental AI cache mostly still holds.
ANALYSIS_WINDOW_DAYS = 180
ACTION_WINDOW_DAYS = 90
_MAX_CALLS = 4
_MAX_TRANSCRIPTS = 4

_client = None


def _client_singleton() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=config.AI_BASE_URL,
            api_key=config.AI_API_KEY,
            timeout=_REQUEST_TIMEOUT_S,
            max_retries=_MAX_RETRIES,
        )
    return _client


SYSTEM = (
    "You are a churn-risk analyst for ITBD, a white-label NOC/helpdesk provider whose "
    "customers ('partners') are MSPs that outsource engineering work to ITBD. Churn means a "
    "partner cancelling their ITBD contract. You assess the health of ONE partner from their "
    "service-review notes/decks, CSAT/NPS feedback, and the account team's own risk flags. "
    "Weigh recent signals over old ones, named-engineer complaints, unmet/ slipping action "
    "items, declining CSAT/NPS, and active SIPs/PIPs. Ignore raw ticket SLA volume. "
    "Respond with STRICT JSON only, no prose, matching the requested schema exactly."
)

SCHEMA_HINT = """Return JSON with exactly these keys:
{
  "risk_score": <int 0-100, higher = more likely to churn>,
  "risk_band": "Low" | "Medium" | "High" | "Critical",
  "confidence": "Low" | "Medium" | "High",
  "summary": "<=2 sentence executive summary of the relationship health",
  "sentiment_trend": "Improving" | "Stable" | "Declining",
  "drivers": [ {"factor": "...", "severity": "Low|Medium|High", "evidence": "<short quote/fact>"} ],
  "remediation": [ {"action": "...", "owner": "<ITBD role/person if known>", "priority": "Low|Medium|High", "rationale": "..."} ],
  "action_items": [ {"task": "...", "owner": "...", "due": "...", "status": "Pending|In Progress|Completed", "source": "<which call/deck>"} ]
}
Provide 2-5 drivers and 2-5 remediation steps. Extract concrete action_items ONLY from meetings
and SIP progress notes NOT marked "[HISTORICAL …]" — HISTORICAL-tagged items are background for the
relationship trend only; their action items are old and likely already resolved, so do NOT list them
as open. When a recent meeting/SIP note conflicts with an older one, trust the most recent.
Output ONLY the JSON object — no prose, no code fences."""


def _truncate(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + " …[truncated]"


_DATE_RE = re.compile(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})")


def _today() -> date:
    """Analysis 'today' — honours PARTNERPULSE_ASOF (same as build_overview) else host date."""
    s = (os.environ.get("PARTNERPULSE_ASOF") or "").strip()
    if s:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


def _meeting_date(obj: dict, keys):
    """Best-effort meeting date from the given fields (ISO date or embedded YYYYMMDD)."""
    for k in keys:
        m = _DATE_RE.search(str(obj.get(k) or ""))
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    return None


def _window_meetings(items, date_keys, today, max_n):
    """Select up to max_n meetings within the analysis window, NEWEST-FIRST, as
    (item, date_or_None, is_historical) tuples. is_historical is True for meetings older
    than ACTION_WINDOW_DAYS (background/trend only — their action items are stale). Undated
    items fill any leftover slots as historical. If nothing falls inside the window (e.g. a
    transcript-only partner whose calls are all old), the single newest dated meeting is kept
    (flagged historical) so the prompt is never empty."""
    analysis_cut = today - timedelta(days=ANALYSIS_WINDOW_DAYS)
    action_cut = today - timedelta(days=ACTION_WINDOW_DAYS)
    dated, undated = [], []
    for it in items:
        dt = _meeting_date(it, date_keys)
        (dated if dt else undated).append((dt, it))
    dated.sort(key=lambda x: x[0], reverse=True)          # newest first
    out = [(it, dt, dt < action_cut) for dt, it in dated if dt >= analysis_cut][:max_n]
    for _dt, it in undated:                               # fill remaining as historical
        if len(out) >= max_n:
            break
        out.append((it, None, True))
    if not out and dated:                                 # fallback: newest stale meeting
        dt, it = dated[0]
        out.append((it, dt, True))
    return out[:max_n]


def _meeting_header(label, dt, is_historical) -> str:
    ds = dt.isoformat() if dt else "date unknown"
    tag = (" [HISTORICAL >90d — background/trend context only; do NOT list its action items as open]"
           if is_historical else "")
    return f"### {label} ({ds}){tag}"


def build_context(data: dict) -> str:
    """Compact, churn-relevant context from a partner cache (keeps tokens sane)."""
    c = data.get("client", {})
    today = _today()
    parts = [f"# PARTNER: {c.get('name')} (Halo client {c.get('id')})"]

    parts.append("\n## Account team risk flags (ground truth)")
    for k in ("rag", "cancel_risk", "health_reason", "next_step", "sip_ticket", "service_line", "vip"):
        parts.append(f"- {k}: {c.get(k)}")
    # Live SIP ticket counts (from halo.count_sips, which checks each ticket's real
    # status) are authoritative; the CFNextStep/CFSIPTicketMDE free-text fields above
    # can be stale -- e.g. still read "SIP in progress" after the SIP was cancelled
    # (Community IT, ticket 778319 -> Cancelled). Only emit a correction when the
    # narrative implies a SIP but 0 are open, so unaffected partners' context (and
    # their AI cache) stays byte-identical -- no needless re-score / drift.
    if not (c.get("sip_open") or 0) and (
        re.search(r"\d{4,}", str(c.get("sip_ticket") or ""))
        or "sip" in str(c.get("next_step") or "").lower()
    ):
        parts.append(
            f"- NOTE: there is NO active SIP -- 0 open SIP tickets "
            f"({c.get('sip_closed') or 0} closed/cancelled on record). Any "
            f"'SIP in progress' wording above is stale; do not treat it as an active SIP."
        )

    cs = data.get("csat_stats", {})
    _pos, _neu, _neg = cs.get("Positive", 0), cs.get("Neutral", 0), cs.get("Negative", 0)
    _rated = _pos + _neu + _neg
    _pos_pct = round(_pos / _rated * 100, 1) if _rated else 0
    _neg_pct = round(_neg / _rated * 100, 1) if _rated else 0
    parts.append(f"\n## CSAT (raw counts): {cs}")
    # Pre-compute the percentage and tell the model to cite IT, not the raw count —
    # the model otherwise misreads "Positive: 75" as "75% positive" (it is 97.4%).
    parts.append(
        f"## CSAT summary: {_pos_pct}% positive, {_neg_pct}% negative "
        f"({_pos} positive / {_neg} negative / {_neu} neutral, of {_rated} rated reviews). "
        f'IMPORTANT: when citing CSAT, quote the PERCENTAGE (e.g. "{_pos_pct}% positive"); '
        f"the bare numbers above are review COUNTS, not percentages — never present a count as a percent."
    )
    negs = [r for r in data.get("csat_comments", []) if r.get("rating") in ("Negative", "Neutral")]
    if negs:
        parts.append("Negative/neutral CSAT comments (most recent first):")
        for r in negs[:12]:
            parts.append(f'- [{r.get("rating")}] {r.get("date","")[:10]} {r.get("contact")}: "{_truncate(r.get("comment"), 240)}"')

    parts.append(f"\n## NPS stats: {data.get('nps_stats', {})}")
    for r in data.get("nps_comments", [])[:10]:
        parts.append(f'- score {r.get("score")} ({r.get("category")}) {r.get("respondent")}: "{_truncate(r.get("comment"), 240)}"')

    sel_calls = _window_meetings(data.get("historical_calls", []), ("date",), today, _MAX_CALLS)
    if sel_calls:
        parts.append(f"\n## Service-review meeting notes (newest first; last {ANALYSIS_WINDOW_DAYS} days)")
        for call, dt, hist in sel_calls:
            parts.append(_meeting_header(call.get("summary"), dt, hist))
            parts.append(_truncate(call.get("notes"), 2500))

    # SIP execution detail: the SDM's weekly progress write-ups on the SIP ticket
    # (utilization, ticket-closure, governance, on-track status). These are filed as
    # private Halo notes and are the ground truth for whether an active SIP is actually
    # turning the account around — distinct from the service-review call notes above.
    # `sips` is grouped per ticket; flatten its updates (tagging the SIP subject/status)
    # so the recency window applies per individual note.
    sip_updates = [
        {"summary": f"{s.get('subject')} [{s.get('status_label')}]",
         "datetime": u.get("datetime"), "note": u.get("note")}
        for s in data.get("sips", []) for u in (s.get("updates") or [])
    ]
    sel_sip = _window_meetings(sip_updates, ("datetime",), today, _MAX_CALLS)
    if sel_sip:
        parts.append(f"\n## SIP (Service Improvement Plan) progress notes (newest first; last {ANALYSIS_WINDOW_DAYS} days)")
        for note, dt, hist in sel_sip:
            parts.append(_meeting_header(f"SIP note: {note.get('summary')}", dt, hist))
            parts.append(_truncate(note.get("note"), 2000))

    decks = data.get("decks", [])
    if decks:
        parts.append("\n## Service-review deck content (converted)")
        for d in decks[:3]:
            parts.append(f"### Deck: {d.get('filename')}")
            parts.append(_truncate(d.get("markdown"), 4000))

    # Service-call transcripts (.docx/.vtt). For transcript-only partners
    # (client_id=None) this is the ONLY substantive signal, so it MUST be in the
    # prompt -- otherwise the model scores on an empty context and fabricates.
    sel_tx = _window_meetings(data.get("transcripts", []), ("date", "title", "filename"),
                              today, _MAX_TRANSCRIPTS)
    if sel_tx:
        parts.append(f"\n## Service-call transcripts (newest first; last {ANALYSIS_WINDOW_DAYS} days)")
        for t, dt, hist in sel_tx:
            parts.append(_meeting_header(f"Transcript: {t.get('filename')}", dt, hist))
            parts.append(_truncate(t.get("markdown"), 4000))

    return "\n".join(str(p) for p in parts)


def _has_substantive_signal(data: dict) -> bool:
    """True when the partner cache carries real churn signal (CSAT/NPS comments,
    call notes, decks, or transcripts) -- as opposed to just the boilerplate
    header + empty flag stubs that build_context always emits."""
    if data.get("csat_comments") or data.get("nps_comments"):
        return True
    if any((c.get("notes") or "").strip() for c in data.get("historical_calls", [])):
        return True
    if any((u.get("note") or "").strip()
           for s in data.get("sips", []) for u in (s.get("updates") or [])):
        return True
    if any((d.get("markdown") or "").strip() for d in data.get("decks", [])):
        return True
    if any((t.get("markdown") or "").strip() for t in data.get("transcripts", [])):
        return True
    return False


def _insufficient_data_result(input_hash: str) -> dict:
    """A low-confidence placeholder used when there is essentially no context to
    analyze, so we never fabricate a risk score from an empty prompt."""
    return {
        "risk_score": None,
        "risk_band": "Unknown",
        "confidence": "Low",
        "summary": "Insufficient data: no CSAT/NPS feedback, call notes, decks, "
                   "or transcripts available to assess churn risk.",
        "sentiment_trend": "Stable",
        "drivers": [],
        "remediation": [],
        "action_items": [],
        "_insufficient_data": True,
        "_model": config.AI_MODEL,
        "_schema_version": CACHE_SCHEMA_VERSION,
        "_input_hash": input_hash,
    }


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_OBJ_RE = re.compile(r"\{.*\}", re.S)


def _extract_json(text: str) -> dict:
    """Parse the model reply into a dict. response_format=json_object is honored by
    the endpoint, but be tolerant of a stray fence / leading token from a reasoning
    model: strip fences, else grab the outermost {...} object."""
    t = (text or "").strip()
    t = _FENCE_RE.sub("", t).strip()
    try:
        return json.loads(t)
    except (ValueError, TypeError):
        m = _OBJ_RE.search(t)
        if m:
            return json.loads(m.group(0))
        raise


def _grok_call(system: str, user: str) -> dict:
    """One synchronous Grok JSON call (raises on error)."""
    resp = _client_singleton().chat.completions.create(
        model=config.AI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_completion_tokens=_MAX_COMPLETION_TOKENS,
        response_format={"type": "json_object"},
    )
    return _extract_json(resp.choices[0].message.content)


def _normalize_insight(insight: dict) -> dict:
    """Repair quirks in the model's JSON before it's cached/uploaded. The reasoning
    model occasionally emits the `action_items` array under a BLANK or non-string key
    (seen: `"": [...]` with no `action_items` key) — which both fails the cache's
    required-key check and is rejected by Firestore (field names must be non-empty
    strings). Coalesce such a key into `action_items`, then drop any empty/non-string
    keys so the result is always Firestore-safe."""
    if not isinstance(insight, dict):
        return insight
    if "action_items" not in insight:
        for k, v in insight.items():
            if (not isinstance(k, str) or not k) and isinstance(v, list):
                insight["action_items"] = v
                break
    for bad in [k for k in insight if not isinstance(k, str) or not k]:
        insight.pop(bad, None)
    insight.setdefault("action_items", [])
    return insight


def _grok_json(context: str) -> dict:
    """The base churn-analysis call (full SYSTEM + schema + partner context)."""
    return _normalize_insight(_grok_call(SYSTEM, f"{SCHEMA_HINT}\n\n---\n{context}"))


def analyze(data: dict, cached_ai: dict = None, force: bool = False) -> dict:
    """Run Grok churn analysis for one partner. Returns the insight dict (with an
    `_error` key if the call/parse failed).

    Incremental: the LLM input (`build_context`) is hashed into `_input_hash`. When
    `cached_ai` carries the same hash, the same model, and a valid prior result, that
    result is reused verbatim — no model call. This makes a full rebuild skip the
    expensive, score-drifting LLM call for any partner whose inputs are unchanged. A
    change of `config.AI_MODEL` invalidates the cache so a model switch re-scores
    cleanly. Pass `force=True` to override.
    """
    context = build_context(data)
    input_hash = hashlib.sha256(context.encode("utf-8")).hexdigest()
    cache_ok = (
        cached_ai
        and cached_ai.get("_input_hash") == input_hash
        and cached_ai.get("_schema_version") == CACHE_SCHEMA_VERSION
        and cached_ai.get("_model") == config.AI_MODEL
        and not cached_ai.get("_error")
        and all(k in cached_ai for k in _REQUIRED_KEYS)
    )
    if not force and cache_ok:
        cached_ai["_cached"] = True            # marker for callers/logs; harmless in the UI
        return cached_ai

    # No real signal -> don't burn an LLM call or fabricate a score.
    if not _has_substantive_signal(data):
        return _insufficient_data_result(input_hash)
    insight = None
    try:
        insight = _grok_json(context)
    except Exception as e:
        # Azure RAI content filter: some service-call transcripts trip the deployment's
        # "Default" content filter — a hard HTTP 400 (finish_reason=content_filter) that
        # the SDK does NOT retry. Retry once WITHOUT transcripts so the partner still
        # scores from CSAT/NPS/risk-flags/decks instead of being stuck unscored (this is
        # what blocked F12 — its transcripts tripped the filter; the rest scores fine).
        if "content_filter" in str(e) and data.get("transcripts"):
            try:
                insight = _grok_json(build_context({**data, "transcripts": []}))
                insight["_content_filtered"] = (
                    "transcripts excluded (Azure content filter blocked them); scored "
                    "from CSAT/NPS/risk-flags/decks only")
            except Exception as e2:
                e = e2
        if insight is None:
            # Graceful degradation: a transient AI outage (auth/rate-limit/timeout) or a
            # hard content-filter block must NOT wipe a partner's existing score to 0.
            # Keep a usable prior result (flagged `_stale`) rather than regressing to None
            # -- this is what zeroed 28 partners on 2026-06-18 when the Azure key was
            # revoked. Only emit the error placeholder when there was never a good score.
            if (cached_ai and not cached_ai.get("_error")
                    and all(k in cached_ai for k in _REQUIRED_KEYS)):
                kept = dict(cached_ai)
                kept["_stale"] = True
                kept["_stale_reason"] = str(e)[:200]
                kept.pop("_cached", None)
                return kept
            return {"_error": str(e), "risk_score": None, "risk_band": "Unknown",
                    "summary": "AI analysis unavailable.", "drivers": [],
                    "remediation": [], "action_items": []}
    insight["_model"] = config.AI_MODEL
    insight["_input_hash"] = input_hash
    insight["_schema_version"] = CACHE_SCHEMA_VERSION
    return insight


# --- Renewal-aware pass (Option A: lightweight overlay on the base churn score) -----------
# A SMALL second call that re-weights the base churn score for contract-renewal timing — it
# is fed only the base assessment + the renewal facts (NO transcripts), so it's cheap and the
# base `ai` block is left untouched. Powers the separate "Renewal Risk" dashboard view.
RENEWAL_SYSTEM = (
    "You are a churn-risk analyst for ITBD (a white-label NOC/helpdesk provider; partners are "
    "MSPs). You are given a partner's EXISTING churn assessment plus their contract-renewal "
    "timing, and must produce a RENEWAL-ADJUSTED churn risk. Guidance: an imminent renewal is a "
    "decision window that AMPLIFIES risk for a shaky/declining account; a distant renewal or a "
    "strong, healthy account dampens near-term risk; an evergreen/auto-renew contract with no "
    "near-term end slightly lowers near-term risk. NEVER lower a high base risk merely because "
    "renewal is far off. Stay close to the base score unless renewal timing clearly changes it. "
    "Respond with STRICT JSON only, no prose."
)
RENEWAL_SCHEMA = """Return JSON with exactly these keys:
{
  "renewal_risk_score": <int 0-100, the renewal-adjusted churn risk>,
  "renewal_band": "Low" | "Medium" | "High" | "Critical",
  "renewal_summary": "<=2 sentences on how the renewal timing changes the churn picture>"
}
Output ONLY the JSON object — no prose, no code fences."""


def _renewal_bucket(days):
    if days is None:
        return "none"
    if days < 0:
        return "overdue"
    if days <= 30:
        return "le30"
    if days <= 90:
        return "le90"
    if days <= 180:
        return "le180"
    return "gt180"


def resolve_renewal(raw: dict) -> dict:
    """From halo.get_next_renewal output ({end_dates, active_contracts, evergreen}) pick the
    NEXT upcoming renewal (earliest end_date >= today; else the most recent past end) and
    days-to-renewal, relative to _today(). Returns the resolved renewal facts."""
    r = raw or {}
    ends = [e for e in (r.get("end_dates") or []) if e]
    today = _today()
    iso = today.isoformat()
    upcoming = [e for e in ends if e >= iso]
    nxt = upcoming[0] if upcoming else (ends[-1] if ends else None)
    days = None
    if nxt:
        try:
            days = (datetime.strptime(nxt, "%Y-%m-%d").date() - today).days
        except ValueError:
            days = None
    return {"next_renewal": nxt, "days_to_renewal": days,
            "active_contracts": r.get("active_contracts", 0),
            "evergreen": bool(r.get("evergreen"))}


def analyze_renewal(base_ai: dict, renewal_raw: dict, cached: dict = None,
                    force: bool = False) -> dict:
    """Renewal-adjusted churn score for one partner (Option A). `renewal_raw` is
    halo.get_next_renewal output. Returns an `ai_renewal` block carrying the adjusted score +
    a short rationale + the resolved next_renewal/days_to_renewal (echoed for the feed).
    Cached/keyed on base risk + next date + proximity bucket + model, so it only re-runs when
    the churn picture or the renewal window actually moves. Degrades to mirroring the base
    score when there is no renewal data or the call fails — never blocks a partner."""
    base = base_ai or {}
    base_risk = base.get("risk_score")
    rr = resolve_renewal(renewal_raw)
    nxt, days = rr["next_renewal"], rr["days_to_renewal"]

    def _mirror(reason, **extra):
        out = {"renewal_risk_score": base_risk, "renewal_band": base.get("risk_band"),
               "renewal_summary": reason, "_model": config.AI_MODEL}
        out.update(rr)
        out.update(extra)
        return out

    key = f"{base_risk}|{nxt}|{_renewal_bucket(days)}|{rr['evergreen']}|{config.AI_MODEL}"
    input_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if (not force and cached and cached.get("_input_hash") == input_hash
            and cached.get("_model") == config.AI_MODEL and not cached.get("_error")
            and cached.get("renewal_risk_score") is not None):
        cached["_cached"] = True
        return cached

    # Nothing to refine: no base score, or no renewal date and not evergreen.
    if base_risk is None or (nxt is None and not rr["evergreen"]):
        return _mirror("No active contract-renewal date on file; renewal-adjusted risk "
                       "mirrors the base churn score.", _no_renewal_data=True,
                       _input_hash=input_hash)

    facts = f"next renewal: {nxt or 'none (evergreen/auto-renew)'}"
    if days is not None:
        facts += f" (~{days} days from today)"
    facts += f"; active contracts: {rr['active_contracts']}"
    if rr["evergreen"]:
        facts += "; has an evergreen/auto-renew contract"
    drivers = "; ".join(d.get("factor", "") for d in (base.get("drivers") or []))[:400]
    user = (f"{RENEWAL_SCHEMA}\n\n---\nBASE CHURN ASSESSMENT: risk {base_risk}/100, trend "
            f"{base.get('sentiment_trend')}. Summary: {base.get('summary', '')}\n"
            f"Key drivers: {drivers}\n\nCONTRACT RENEWAL: {facts}")
    try:
        out = _grok_call(RENEWAL_SYSTEM, user)
        if out.get("renewal_risk_score") is None:
            raise ValueError("no renewal_risk_score in response")
        out.update(rr)
        out["_model"] = config.AI_MODEL
        out["_input_hash"] = input_hash
        return out
    except Exception as e:
        if (cached and not cached.get("_error")
                and cached.get("renewal_risk_score") is not None):
            kept = dict(cached)
            kept["_stale"] = True
            kept["_stale_reason"] = str(e)[:200]
            kept.pop("_cached", None)
            return kept
        return _mirror("Renewal-adjusted scoring unavailable; showing the base churn score.",
                       _error=str(e)[:200], _input_hash=input_hash)


# --- SIP journey summary (per-ticket narrative for the Partner-360 SIP card) ---------------
# A SMALL per-SIP call that turns a SIP ticket's weekly progress notes into a 1-2 sentence
# start->date narrative + a short current-status label. Only ACTIVE (open / on-hold) SIPs are
# summarized — closed ones render as a collapsed one-liner. Cached per ticket on a hash of its
# notes so a rebuild only re-summarizes a SIP whose notes actually changed.
SIP_SUMMARY_SYSTEM = (
    "You are a service-delivery analyst for ITBD (a white-label NOC/helpdesk provider; partners "
    "are MSPs). You are given ONE Service Improvement Plan (SIP) for an engineer/team and its "
    "weekly progress notes (oldest to newest). Write a concise factual summary of the SIP's "
    "journey from start to the latest update — what it was opened for and how it has trended — "
    "citing concrete figures (utilization %, tickets closed, governance feedback) when present. "
    "Do NOT invent data. Respond with STRICT JSON only, no prose."
)
SIP_SUMMARY_SCHEMA = """Return JSON with exactly these keys:
{
  "summary": "<=2 sentence start->date narrative of this SIP's progress",
  "latest_status": "<short label for the most recent state, e.g. ON TRACK | AT RISK | STALLED | COMPLETED>"
}
Output ONLY the JSON object — no prose, no code fences."""


def _sip_summary_hash(sip: dict) -> str:
    txt = "\n".join((u.get("datetime", "") + "|" + (u.get("note") or ""))
                    for u in (sip.get("updates") or []))
    return hashlib.sha256((str(sip.get("ticket_id")) + "\n" + txt).encode("utf-8")).hexdigest()


def summarize_sips(sips: list, cached_sips: list = None, force: bool = False) -> list:
    """Attach an AI `summary` + `latest_status` to each ACTIVE SIP (mutates + returns
    `sips`). Reuses a cached summary when the SIP's notes are unchanged (keyed by
    ticket_id + notes hash). Closed SIPs and SIPs with no notes are left as-is.
    Never raises — a failed call falls back to no summary (the card still shows the
    status badge + date range + raw updates)."""
    sips = sips or []
    prev = {c.get("ticket_id"): c for c in (cached_sips or [])}
    for s in sips:
        if s.get("status_class") == "closed" or not s.get("updates"):
            continue
        h = _sip_summary_hash(s)
        p = prev.get(s.get("ticket_id"))
        if (not force and p and p.get("_sum_hash") == h and p.get("summary")
                and p.get("_sum_model") == config.AI_MODEL):
            s["summary"], s["latest_status"] = p.get("summary"), p.get("latest_status")
            s["_sum_hash"], s["_sum_model"] = h, config.AI_MODEL
            continue
        # oldest->newest so the narrative reads as a journey
        ups = sorted(s.get("updates"), key=lambda u: u.get("datetime") or "")
        body = "\n\n".join(
            f"[{(u.get('datetime') or '')[:10]}] {_truncate(u.get('note'), 1200)}" for u in ups)
        user = (f"{SIP_SUMMARY_SCHEMA}\n\n---\nSIP: {s.get('subject')} "
                f"(status: {s.get('status') or s.get('status_label')})\n\n{body}")
        try:
            out = _grok_call(SIP_SUMMARY_SYSTEM, user)
            s["summary"] = (out.get("summary") or "").strip() or None
            s["latest_status"] = (out.get("latest_status") or "").strip() or None
        except Exception as e:
            s["summary"], s["latest_status"] = None, None
            s["_sum_error"] = str(e)[:200]
        s["_sum_hash"], s["_sum_model"] = h, config.AI_MODEL
    return sips
