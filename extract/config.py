"""Configuration & secrets.

Env-first: every value can be overridden by an environment variable (or a local
.env file). The fallback defaults are the SOP-documented test credentials so the
engine runs locally out-of-the-box. For the Firebase / Cloud Functions deploy,
set these via Secret Manager and DO NOT rely on the in-code fallbacks.
"""
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


_warned_fallbacks = set()


def _secret(key: str, default: str = "") -> str:
    """Like _env, but warns ONCE (ASCII stderr) when the env var is unset and the
    in-repo baked default is used, so a cloud misconfig / missing Secret Manager
    value is visible in logs. Never prints the secret value itself."""
    val = os.environ.get(key)
    if val is None and key not in _warned_fallbacks:
        _warned_fallbacks.add(key)
        sys.stderr.write(
            "WARNING: env var %s is unset; using in-repo baked default "
            "credential (local-dev fallback). Set it via Secret Manager / "
            "environment for any non-local deploy.\n" % key
        )
    return val if val is not None else default


# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = Path(_env("PARTNERPULSE_TRANSCRIPTS", str(ROOT / "Transcripts")))
DATA_DIR = Path(_env("PARTNERPULSE_DATA", str(ROOT / "data")))
DECKS_DIR = DATA_DIR / "decks"          # downloaded deck PDFs + converted .md

# --- HaloPSA (OAuth2 client_credentials, read-only) --------------------------
HALO_BASE_URL = _env("HALO_BASE_URL", "https://itbd.halopsa.com")
HALO_CLIENT_ID = _secret("HALO_CLIENT_ID", "***REMOVED***")
HALO_CLIENT_SECRET = _secret("HALO_CLIENT_SECRET", "***REMOVED***")
HALO_SCOPE = _env("HALO_SCOPE", "all")

# --- TeamGPS Open API --------------------------------------------------------
TEAMGPS_BASE_URL = _env("TEAMGPS_BASE_URL", "https://api.team-gps.net/open-api/v1")
TEAMGPS_API_KEY = _secret(
    "TEAMGPS_API_KEY",
    "***REMOVED***",
)

# --- Claude churn analysis (Claude Agent SDK, subscription-billed) -----------
# Swapped from Azure Foundry gpt-5.4 on 2026-06-18. The Agent SDK authenticates
# through the local Claude Code OAuth login (`claude setup-token` / `claude
# login`) and bills the operator's Claude subscription — there is NO API key.
# `extract/ai.py` strips ANTHROPIC_API_KEY from the environment so a stray key
# cannot silently route spend to pay-as-you-go API billing. Because subscription
# auth is for individual interactive use, this runs MANUALLY on a laptop, not as
# the (retired) unattended cloud nightly Job. Override the model with CLAUDE_MODEL.
CLAUDE_MODEL = _env("CLAUDE_MODEL", "claude-sonnet-4-6")
