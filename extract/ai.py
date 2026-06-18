"""AI churn-analysis layer (Claude via the Claude Agent SDK).

Runs Claude churn analysis against the **signed-in Claude subscription** — the
local Claude Code / Agent SDK OAuth login (`claude setup-token` or `claude
login`). There is **NO API key**: if `ANTHROPIC_API_KEY` is set it would silently
route to pay-as-you-go API billing instead of the subscription, so this module
strips it from the environment on import (with a one-time warning). Swapped from
Azure Foundry gpt-5.4 on 2026-06-18 so the pipeline bills the operator's Claude
plan when run manually on a laptop (the cloud nightly Job is retired — the SDK
cannot bill a personal subscription from unattended cloud automation).

Consumes a partner's unified cache (the dict from build_partner.build) and returns
structured churn insight: a risk score + band, the drivers behind it, proactive
remediation, extracted action items, and sentiment trend. Designed to be merged
back into the partner JSON under the `ai` key and rolled up on the portfolio view.
"""
import asyncio
import hashlib
import json
import os
import re
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    query,
)

from . import config

# Subscription billing requires that no API key is present — it outranks the
# OAuth/CLI login in the SDK's auth precedence and would bill API credits. Strip
# it once, loudly, so a stray env var can't silently move spend off the plan.
if os.environ.pop("ANTHROPIC_API_KEY", None) is not None:
    sys.stderr.write(
        "WARNING: ANTHROPIC_API_KEY was set; removing it for this process so "
        "Claude analysis bills your Claude subscription (OAuth login), not the "
        "pay-as-you-go API. Unset it in your environment to silence this.\n"
    )

# Bump when the cached-result shape/semantics change so old caches are invalidated
# (a cached result whose `_schema_version` differs is treated as stale and re-run).
CACHE_SCHEMA_VERSION = 2

# Keys an AI result must carry to be considered a usable cached value.
_REQUIRED_KEYS = ("risk_score", "risk_band", "summary", "drivers",
                  "remediation", "action_items")

# The Agent SDK runs Claude as a single, tool-free, non-interactive turn.
_MAX_TURNS = 1

SYSTEM = (
    "You are a churn-risk analyst for ITBD, a white-label NOC/helpdesk provider whose "
    "customers ('partners') are MSPs that outsource engineering work to ITBD. Churn means a "
    "partner cancelling their ITBD contract. You assess the health of ONE partner from their "
    "service-review notes/decks, CSAT/NPS feedback, and the account team's own risk flags. "
    "Weigh recent signals over old ones, named-engineer complaints, unmet/ slipping action "
    "items, declining CSAT/NPS, and active SIPs/PIPs. Ignore raw ticket SLA volume. "
    "Respond with STRICT JSON only, no prose, no markdown fences, matching the requested "
    "schema exactly."
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
Provide 2-5 drivers, 2-5 remediation steps, and extract concrete action_items from the notes/decks.
Output ONLY the JSON object — no prose, no code fences."""


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
        "_model": config.CLAUDE_MODEL,
        "_schema_version": CACHE_SCHEMA_VERSION,
        "_input_hash": input_hash,
    }


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_OBJ_RE = re.compile(r"\{.*\}", re.S)


def _extract_json(text: str) -> dict:
    """Parse the model's reply into a dict. Claude via the Agent SDK returns plain
    text (no API `response_format`), so be tolerant of stray code fences or a
    leading sentence: strip fences, else grab the outermost {...} object."""
    t = (text or "").strip()
    t = _FENCE_RE.sub("", t).strip()
    try:
        return json.loads(t)
    except (ValueError, TypeError):
        m = _OBJ_RE.search(t)
        if m:
            return json.loads(m.group(0))
        raise


async def _aquery(context: str) -> str:
    """Run one tool-free Claude turn via the Agent SDK and return its text."""
    opts = ClaudeAgentOptions(
        model=config.CLAUDE_MODEL,
        system_prompt=SYSTEM,
        allowed_tools=[],
        max_turns=_MAX_TURNS,
        setting_sources=[],   # do NOT inherit the repo's CLAUDE.md / settings
    )
    chunks = []
    async for msg in query(prompt=f"{SCHEMA_HINT}\n\n---\n{context}", options=opts):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
    return "".join(chunks)


def _call_claude(context: str) -> str:
    """Synchronous wrapper — build_all/build_real_partners call analyze() in a
    plain loop, so spin a fresh event loop per partner."""
    return asyncio.run(_aquery(context))


def analyze(data: dict, cached_ai: dict = None, force: bool = False) -> dict:
    """Run Claude churn analysis for one partner. Returns the insight dict (with
    an `_error` key if the call/parse failed).

    Incremental: the LLM input (`build_context`) is hashed into `_input_hash`. When
    `cached_ai` carries the same hash, the same model, and a valid prior result,
    that result is reused verbatim — no Claude call. This makes a full rebuild skip
    the expensive, score-drifting LLM call for any partner whose inputs are
    unchanged. A change of `config.CLAUDE_MODEL` (or the old gpt-5.4 `_model`)
    invalidates the cache so a model switch re-scores cleanly. Pass `force=True`
    to override.
    """
    context = build_context(data)
    input_hash = hashlib.sha256(context.encode("utf-8")).hexdigest()
    cache_ok = (
        cached_ai
        and cached_ai.get("_input_hash") == input_hash
        and cached_ai.get("_schema_version") == CACHE_SCHEMA_VERSION
        and cached_ai.get("_model") == config.CLAUDE_MODEL
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
        raw = _call_claude(context)
        insight = _extract_json(raw)
        insight["_model"] = config.CLAUDE_MODEL
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
