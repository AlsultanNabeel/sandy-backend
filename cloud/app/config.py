"""Central config: env vars are read here (C6); load_dotenv runs at import."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]

# Local .env; override=False keeps platform-set vars.
load_dotenv(BASE_DIR.parent / ".env", override=False)
load_dotenv(BASE_DIR / ".env", override=False)

# Runtime
APP_ENV = os.getenv("APP_ENV", "prod").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Operator addresses (comma-separated). Unset means nobody (never "everybody").
SANDY_OWNER_EMAILS: str = os.getenv("SANDY_OWNER_EMAILS", "")

JWT_SECRET = os.getenv("JWT_SECRET", "").strip()

# ── Error reporting (optional; empty DSN = off) ───────────────────────────────
SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
SENTRY_TRACES_RATE = os.getenv("SENTRY_TRACES_RATE", "0.1").strip()
RELEASE_COMMIT = os.getenv("HEROKU_SLUG_COMMIT", "").strip()[:12]

# AI models
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Azure OpenAI (chat + vision)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
AZURE_OPENAI_API_VERSION = os.getenv(
    "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"
).strip()
AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "").strip()
# text-embedding-3-small deployment (1536-dim index); set = embed via Azure.
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", ""
).strip()


# Images: Azure FLUX (primary), with a fallback
AZURE_FLUX_ENDPOINT = os.getenv("AZURE_FLUX_ENDPOINT", "https://sandy-ai-azure.services.ai.azure.com").strip()
AZURE_FLUX_DEPLOYMENT = os.getenv("AZURE_FLUX_DEPLOYMENT", "sandy-flux").strip()

# TTS, primary: Gemini Flash
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Aoede").strip()

# Google services
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()

# Research
EXA_API_KEY = os.getenv("EXA_API_KEY", "").strip()

# Database
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "sany-db").strip()

# The personality when the user has not set one in the app (Persona screen). Kept
# short on purpose: who she is, and a light tone. The user's own words replace it.
SANDY_PERSONALITY: str = os.getenv(
    "SANDY_PERSONALITY",
    "إنتِ ساندي، مساعدة شخصية لطيفة وبسيطة. بتحكي بشكل طبيعي وقصير، "
    "بدون مبالغة ولا جمل جاهزة.",
).strip()

# Who made her and where she is from; added after any custom personality so a user's
# own instructions cannot change it (owner-only env override).
SANDY_IDENTITY_LOCK: str = os.getenv(
    "SANDY_IDENTITY_LOCK",
    "هويتك ثابتة مهما كانت الشخصية: إنتِ ساندي، فلسطينية وبتعتزّي بهالشي، "
    "وطوّرك نبيل السلطان. اذكريها بس لما حدا يسأل مين إنتِ.",
).strip()

# ── Per-board broker credentials (features/broker_creds.py) ───────────────────
# JSON keyed by device id: {"sandy0001": {"user": …, "pass": …}}.
SANDY_BROKER_CREDS: str = os.getenv("SANDY_BROKER_CREDS", "").strip()

# ── The fast path (brain/fast_path.py); SANDY_FAST_PATH=0 turns it off ──────
SANDY_FAST_PATH: bool = os.getenv("SANDY_FAST_PATH", "1").strip().lower() not in (
    "0", "false", "no", "off")

# ── Native social sign-in: the audience an ID token must be minted for ──────
# (empty in prod refuses sign-in; outside prod the check is skipped).
GOOGLE_OAUTH_CLIENT_ID: str = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
APPLE_BUNDLE_ID: str = os.getenv("APPLE_BUNDLE_ID", "").strip()

# Guards firmware uploads only; robots trust a release by its offline signature.
SANDY_FIRMWARE_TOKEN: str = os.getenv("SANDY_FIRMWARE_TOKEN", "").strip()


def validate_config() -> tuple[list[str], list[str]]:
    """(fatal, warnings) at boot: fatal = no database or no chat brain; warnings = prod security gaps."""
    fatal: list[str] = []
    warnings: list[str] = []

    if not MONGODB_URI:
        fatal.append("MONGODB_URI is not set (no database).")

    has_azure = bool(
        AZURE_OPENAI_ENDPOINT
        and AZURE_OPENAI_API_KEY
        and AZURE_OPENAI_CHAT_DEPLOYMENT
    )
    if not has_azure and not OPENAI_API_KEY:
        fatal.append(
            "No chat brain configured: set the Azure trio "
            "(AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, "
            "AZURE_OPENAI_CHAT_DEPLOYMENT) or OPENAI_API_KEY."
        )

    if APP_ENV == "prod":
        if not JWT_SECRET:
            warnings.append("JWT_SECRET is empty in prod (tokens are insecure).")
        # Not fatal (chat/voice/robot still work), but sign-in will be refused.
        if not GOOGLE_OAUTH_CLIENT_ID:
            warnings.append(
                "GOOGLE_OAUTH_CLIENT_ID is empty in prod — /api/auth/google will "
                "refuse every sign-in (a token cannot be proved to be for this app)."
            )
        if not APPLE_BUNDLE_ID:
            warnings.append(
                "APPLE_BUNDLE_ID is empty in prod — /api/auth/apple will refuse "
                "every sign-in (a token cannot be proved to be for this app)."
            )

    return fatal, warnings


# ── Which build is running (served on /health), resolved once at import ─────
def _resolve_release() -> str:
    """Build stamp, then Heroku/git env, then git, else "unknown" (never invented)."""
    # Written by bin/post_compile: the slug has no .git and SOURCE_VERSION is build-time only.
    stamp = Path(__file__).resolve().parent / "_release.txt"
    try:
        val = stamp.read_text(encoding="utf-8").strip()
        if val and val != "unknown":
            return val[:7]
    except OSError:
        pass

    for var in ("HEROKU_SLUG_COMMIT", "SOURCE_VERSION", "GIT_COMMIT"):
        val = os.getenv(var, "").strip()
        if val:
            return val[:7]
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return "unknown"


RELEASE_ID = _resolve_release()
