"""AI churn-analysis layer (Azure Foundry gpt-5.4).

Consumes a partner's unified cache (the dict from build_partner.build) and returns
structured churn insight: a risk score + band, the drivers behind it, proactive
remediation, extracted action items, and sentiment trend. Designed to be merged
back into the partner JSON under the `ai` key and rolled up on the portfolio view.
"""
import json

from openai import AzureOpenAI

from . import config

_client = None


def _client_singleton() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            api_version=config.AZURE_OPENAI_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_KEY,
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

    return "\n".join(str(p) for p in parts)


def analyze(data: dict) -> dict:
    """Run gpt-5.4 churn analysis for one partner. Returns the insight dict (with
    an `_error` key if the call/parse failed)."""
    context = build_context(data)
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
        return insight
    except Exception as e:
        return {"_error": str(e), "risk_score": None, "risk_band": "Unknown",
                "summary": "AI analysis unavailable.", "drivers": [],
                "remediation": [], "action_items": []}
