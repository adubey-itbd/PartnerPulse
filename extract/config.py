"""Configuration & secrets.

Env-first: every value can be overridden by an environment variable (or a local
.env file). The fallback defaults are the SOP-documented test credentials so the
engine runs locally out-of-the-box. For the Firebase / Cloud Functions deploy,
set these via Secret Manager and DO NOT rely on the in-code fallbacks.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = Path(_env("PARTNERPULSE_TRANSCRIPTS", str(ROOT / "Transcripts")))
DATA_DIR = Path(_env("PARTNERPULSE_DATA", str(ROOT / "data")))
DECKS_DIR = DATA_DIR / "decks"          # downloaded deck PDFs + converted .md

# --- HaloPSA (OAuth2 client_credentials, read-only) --------------------------
HALO_BASE_URL = _env("HALO_BASE_URL", "https://itbd.halopsa.com")
HALO_CLIENT_ID = _env("HALO_CLIENT_ID", "***REMOVED***")
HALO_CLIENT_SECRET = _env("HALO_CLIENT_SECRET", "***REMOVED***")
HALO_SCOPE = _env("HALO_SCOPE", "all")

# --- TeamGPS Open API --------------------------------------------------------
TEAMGPS_BASE_URL = _env("TEAMGPS_BASE_URL", "https://api.team-gps.net/open-api/v1")
TEAMGPS_API_KEY = _env(
    "TEAMGPS_API_KEY",
    "***REMOVED***",
)

# --- Azure OpenAI (gpt-5.4 on Azure Foundry) ---------------------------------
AZURE_OPENAI_ENDPOINT = _env("AZURE_OPENAI_ENDPOINT", "https://leonwisoky.cognitiveservices.azure.com/")
AZURE_OPENAI_KEY = _env(
    "AZURE_OPENAI_KEY",
    "***REMOVED***",
)
AZURE_OPENAI_DEPLOYMENT = _env("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4")
AZURE_OPENAI_API_VERSION = _env("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
