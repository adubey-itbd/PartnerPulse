"""AI churn-analysis layer (Azure Foundry gpt-5.4).

Consumes a partner's unified cache (the dict from build_partner.build) and returns
structured churn insight: a risk score + band, the drivers behind it, proactive
remediation, extracted action items, and sentiment trend. Designed to be merged
back into the partner JSON under the `ai` key and rolled up on the portfolio view.
"""
import hashlib
import json

from openai import AzureOpenAI

from . import config

# Bump when the cached-result shape/semantics change so old caches are invalidated
# (a cached result whose `_schema_version` differs is treated as stale and re-run).
CACHE_SCHEMA_VERSION = 2

# Keys an AI result must carry to be considered a usable cached value.
_REQUIRED_KEYS = ("risk_score", "risk_band", "summary", "drivers",
                  "remediation", "action_items")

# Network hardening for the Azure OpenAI client.
_REQUEST_TIMEOUT_S = 120
_MAX_RETRIES = 2

_client = None


def _client_singleton() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            api_version=config.AZURE_OPENAI_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_KEY,
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
Provide 2-5 drivers, 2-5 remediation steps, and extract concrete action_items from the notes/decks."""


def _truncate(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + " …[truncated]"


def build_context(data: dict) -> str:
    """Compact, churn-relevant context from a partner cache (keeps tokens sane)."""
    c = data.get("client", {})
    parts = [f"# PARTNER: {c.get('name')} (Halo client {c.get('id')})"]

    parts.append("\n## Account team risk flags (ground truth)")
    for k in ("rag", "cancel_risk", "health_reason", "next_step", "sip_ticket", "service_line", "vip"):
        parts.append(f"- {k}: {c.get(k)}")

    cs = data.get("csat_stats", {})
    parts.append(f"\n## CSAT stats: {cs}")
    negs = [r for r in data.get("csat_comments", []) if r.get("rating") in ("Negative", "Neutral")]
    if negs:
        parts.append("Negative/neutral CSAT comments (most recent first):")
        for r in negs[:12]:
            parts.append(f'- [{r.get("rating")}] {r.get("date","")[:10]} {r.get("contact")}: "{_truncate(r.get("comment"), 240)}"')

    parts.append(f"\n## NPS stats: {data.get('nps_stats', {})}")
    for r in data.get("nps_comments", [])[:10]:
        parts.append(f'- score {r.get("score")} ({r.get("category")}) {r.get("respondent")}: "{_truncate(r.get("comment"), 240)}"')

    calls = data.get("historical_calls", [])
    if calls:
        parts.append("\n## Recent service-review meeting notes")
        for call in calls[:4]:
            parts.append(f"### {call.get('summary')} ({str(call.get('date'))[:10]})")
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
    txs = data.get("transcripts", [])
    if txs:
        parts.append("\n## Service-call transcripts")
        for t in txs[:4]:
            parts.append(f"### Transcript: {t.get('filename')} ({str(t.get('date'))[:10]})")
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
        "_model": config.AZURE_OPENAI_DEPLOYMENT,
        "_schema_version": CACHE_SCHEMA_VERSION,
        "_input_hash": input_hash,
    }


def analyze(data: dict, cached_ai: dict = None, force: bool = False) -> dict:
    """Run gpt-5.4 churn analysis for one partner. Returns the insight dict (with
    an `_error` key if the call/parse failed).

    Incremental: the LLM input (`build_context`) is hashed into `_input_hash`. When
    `cached_ai` carries the same hash and a valid prior result, that result is reused
    verbatim — no LLM call. This makes a full rebuild skip the expensive, score-drifting
    gpt-5.4 call for any partner whose inputs are unchanged. Pass `force=True` to override.
    """
    context = build_context(data)
    input_hash = hashlib.sha256(context.encode("utf-8")).hexdigest()
    cache_ok = (
        cached_ai
        and cached_ai.get("_input_hash") == input_hash
        and cached_ai.get("_schema_version") == CACHE_SCHEMA_VERSION
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
            model=config.AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{SCHEMA_HINT}\n\n---\n{context}"},
            ],
            max_completion_tokens=4000,
            response_format={"type": "json_object"},
        )
        insight = json.loads(resp.choices[0].message.content)
        insight["_model"] = config.AZURE_OPENAI_DEPLOYMENT
        insight["_input_hash"] = input_hash
        insight["_schema_version"] = CACHE_SCHEMA_VERSION
        return insight
    except Exception as e:
        return {"_error": str(e), "risk_score": None, "risk_band": "Unknown",
                "summary": "AI analysis unavailable.", "drivers": [],
                "remediation": [], "action_items": []}
