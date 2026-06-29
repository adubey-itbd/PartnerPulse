"""Configuration & secrets.

Env-first and secret-free: credentials come ONLY from environment variables or a
local, gitignored `.env` file — there are NO secrets baked into this file (the
in-code fallbacks were removed 2026-06-29 after GitHub push-protection flagged
them; see changelog). Locally, put the keys in `.env` (HALO_CLIENT_ID/SECRET,
TEAMGPS_API_KEY, AI_API_KEY, GRAPH_*); in the Firebase / Cloud Run deploy they
come from Secret Manager (see scripts/seed_secrets.py). A missing secret warns
once and resolves to "" rather than silently using a hardcoded credential.
"""
import os
import sys
from pathlib import Path

# Load the local .env (gitignored) into the environment without an external
# dependency (python-dotenv may not be installed). Real env vars / Secret Manager
# take precedence — setdefault never overrides an already-set variable.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


_warned_fallbacks = set()


def _secret(key: str, default: str = "") -> str:
    """Like _env, but warns ONCE (ASCII stderr) when the secret is unset, so a
    missing .env entry / Secret Manager value is visible in logs. There is no
    baked default — an unset secret resolves to "" (calls will then fail loudly
    against the API rather than silently using a hardcoded credential). Never
    prints the secret value itself."""
    val = os.environ.get(key)
    if val is None and key not in _warned_fallbacks:
        _warned_fallbacks.add(key)
        sys.stderr.write(
            "WARNING: secret %s is not set (no env var or .env entry). Set it in "
            ".env for local dev, or Secret Manager for the cloud deploy.\n" % key
        )
    return val if val is not None else default


# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = Path(_env("PARTNERPULSE_TRANSCRIPTS", str(ROOT / "Transcripts")))
DATA_DIR = Path(_env("PARTNERPULSE_DATA", str(ROOT / "data")))
DECKS_DIR = DATA_DIR / "decks"          # downloaded deck PDFs + converted .md

# --- HaloPSA (OAuth2 client_credentials, read-only) --------------------------
HALO_BASE_URL = _env("HALO_BASE_URL", "https://itbd.halopsa.com")
HALO_CLIENT_ID = _secret("HALO_CLIENT_ID")
HALO_CLIENT_SECRET = _secret("HALO_CLIENT_SECRET")
HALO_SCOPE = _env("HALO_SCOPE", "all")

# --- TeamGPS Open API --------------------------------------------------------
TEAMGPS_BASE_URL = _env("TEAMGPS_BASE_URL", "https://api.team-gps.net/open-api/v1")
TEAMGPS_API_KEY = _secret("TEAMGPS_API_KEY")

# --- AI churn analysis (Grok via Azure AI Foundry, OpenAI-compatible endpoint) ---
# Synchronous chat-completions through the OpenAI SDK (NOT the AzureOpenAI client) —
# base_url + API key. Swapped 2026-06-18: the org's `gpt-5.4` Azure deployment is
# Batch-only (async, can't serve the per-partner synchronous calls), so the engine
# uses a Global Standard `grok-4-1-fast-reasoning` deployment that serves synchronous
# requests over the OpenAI v1 surface. Rate limits on this deployment: 50k TPM / 50 RPM
# (a full re-score is throttled — the OpenAI client retries 429s with backoff).
AI_BASE_URL = _env("AI_BASE_URL", "https://daku.services.ai.azure.com/openai/v1/")
AI_API_KEY = _secret("AI_API_KEY")
AI_MODEL = _env("AI_MODEL", "grok-4-1-fast-reasoning")
