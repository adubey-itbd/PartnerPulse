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

# --- Azure OpenAI (gpt-5.4 on Azure Foundry) ---------------------------------
AZURE_OPENAI_ENDPOINT = _env("AZURE_OPENAI_ENDPOINT", "https://leonwisoky.cognitiveservices.azure.com/")
AZURE_OPENAI_KEY = _secret(
    "AZURE_OPENAI_KEY",
    "***REMOVED***",
)
AZURE_OPENAI_DEPLOYMENT = _env("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4")
AZURE_OPENAI_API_VERSION = _env("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
