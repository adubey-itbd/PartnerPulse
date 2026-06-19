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
NOT marked "[HISTORICAL …]" — HISTORICAL-tagged meetings are background for the relationship trend
only; their action items are old and likely already resolved, so do NOT list them as open. When a
recent meeting conflicts with an older one, trust the most recent.
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
    try:
        resp = _client_singleton().chat.completions.create(
            model=config.AI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{SCHEMA_HINT}\n\n---\n{context}"},
            ],
            max_completion_tokens=_MAX_COMPLETION_TOKENS,
            response_format={"type": "json_object"},
        )
        insight = _extract_json(resp.choices[0].message.content)
        insight["_model"] = config.AI_MODEL
        insight["_input_hash"] = input_hash
        insight["_schema_version"] = CACHE_SCHEMA_VERSION
        return insight
    except Exception as e:
        # Graceful degradation: a transient AI outage (auth/rate-limit/timeout) must
        # NOT wipe a partner's existing score to 0. If a usable prior result is
        # available, keep it (flagged `_stale`) rather than regressing to None -- this
        # is what zeroed 28 partners on 2026-06-18 when the Azure key was revoked. Only
        # emit the error placeholder when there was never a good score to fall back to.
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
