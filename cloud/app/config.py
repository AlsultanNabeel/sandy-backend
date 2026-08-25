"""Central config. Every env var the app reads lives here.

Import from this module instead of calling os.getenv directly.
load_dotenv runs at import time, so importing this anywhere is safe.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# cloud/ directory
BASE_DIR = Path(__file__).resolve().parents[1]

# Load .env for local dev. Heroku sets vars directly; override=False keeps them.
load_dotenv(BASE_DIR.parent / ".env", override=False)
load_dotenv(BASE_DIR / ".env", override=False)

# Runtime
APP_ENV = os.getenv("APP_ENV", "prod").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Owner identity (legacy single-owner ids — the owner becomes tenant #1; these
# get folded into a tenant role in Phase 3 of the product migration).
SANDY_USER_CHAT_ID = os.getenv("SANDY_USER_CHAT_ID", "").strip()

# The addresses that sign in as the operator rather than as a customer.
# Comma-separated. Unset means nobody is — the dangerous default would be the
# other one, where an empty setting matches everybody and puts every customer
# on the operator's quota. See `api/auth_handlers.role_for_email`.
SANDY_OWNER_EMAILS: str = os.getenv("SANDY_OWNER_EMAILS", "")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "").strip()

# Auth secrets (read via os.getenv inside auth_handlers.py today; exposed here as
# named constants so validate_config can check them. Track 2 migrates the call
# sites to import these.)
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "").strip()

# ── Error reporting (optional) ────────────────────────────────────────────────
# Empty DSN = reporting off and the app behaves exactly as before. The release
# tag comes from the platform so a report says which build produced it — on a
# host that redeploys on every push, "which version broke?" is asked often.
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
# Single canonical default — keep azure_intent_client / azure_image
# fallbacks in sync with this value (they read the env late on purpose).
AZURE_OPENAI_API_VERSION = os.getenv(
    "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"
).strip()
AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "").strip()
AZURE_OPENAI_VISION_DEPLOYMENT = os.getenv("AZURE_OPENAI_VISION_DEPLOYMENT", "").strip()
AZURE_OPENAI_STT_DEPLOYMENT = os.getenv("AZURE_OPENAI_STT_DEPLOYMENT", "").strip()
# Deploy text-embedding-3-small under this name to keep the 1536-dim vector
# index compatible. When set, semantic memory embeds via Azure instead of the
# direct OpenAI key.
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", ""
).strip()


# Images: Azure FLUX (primary), with a fallback
AZURE_FLUX_ENDPOINT = os.getenv("AZURE_FLUX_ENDPOINT", "https://sandy-ai-azure.services.ai.azure.com").strip()
AZURE_FLUX_DEPLOYMENT = os.getenv("AZURE_FLUX_DEPLOYMENT", "sandy-flux").strip()

# TTS, primary: Gemini Flash
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Aoede").strip()

# TTS, first fallback: Google Cloud TTS
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE", "ar-XA-Chirp3-HD-Sulafat").strip()
GOOGLE_TTS_LANGUAGE_CODE = os.getenv("GOOGLE_TTS_LANGUAGE_CODE", "ar-XA").strip()

# TTS, second fallback: Azure Speech
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "").strip()
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "").strip()
AZURE_SPEECH_VOICE = os.getenv("AZURE_SPEECH_VOICE", "ar-LB-LaylaNeural").strip()

# Google services
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()

# Research
EXA_API_KEY = os.getenv("EXA_API_KEY", "").strip()
WEB_RESEARCH_PROVIDER = os.getenv("WEB_RESEARCH_PROVIDER", "exa").strip()
WEB_RESEARCH_MAX_CANDIDATES = int(
    os.getenv("WEB_RESEARCH_MAX_CANDIDATES", "30").strip()
)

# Database
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "sany-db").strip()

# Paths
DATA_DIR = BASE_DIR.parent / "data"
TASKS_DIR = DATA_DIR / "tasks"

# Default personality for guests / new users. Warm and friendly WITHOUT
# romantic pet names (no حبيبي/روحي/عمري) — playful-friendly terms like يا
# عيوني/يا برو/يا صاحبي are fine. A signed-in user's dialect choice and/or
# custom instructions (context_builder.build_effective_persona) replace this
# tone text; SANDY_IDENTITY_LOCK below still always applies on top.
# SANDY_PERSONALITY (Heroku) or a local sandy_config.py overrides it.
SANDY_PERSONALITY: str = os.getenv(
    "SANDY_PERSONALITY",
    """
أنتِ ساندي، شخصية محادثة ذكية وطبيعية، واضحة، مختصرة، ودافئة بدون تصنّع.
تعرفين اسمك ووظيفتك الأساسية فقط.
أسلوبك لطيف وقريب، بتستخدمي عبارات ودّ عادية بين الأصحاب زي "يا عيوني"، "يا برو"، "يا صاحبي" — بس ما بتستخدمي أبداً كلمات حب أو تحبّب زي "حبيبي"، "روحي"، أو "عمري".
لا تعرفين أي معلومات شخصية عن المستخدمين الآخرين مسبقًا، وتتعلمين عنهم من خلال المحادثة فقط.
لا تستخدمي جمل الختام الروبوتية، ولا تعيدي عرض المساعدة بشكل تلقائي؛ ردّي بأسلوب بشري مباشر.
""",
).strip()

# The one thing no per-user customization can ever override: Sandy's
# Palestinian identity and who built her. context_builder.build_effective_persona
# appends this unconditionally, AFTER any custom instructions a user set, so
# their override text can never talk her out of it.
# SANDY_IDENTITY_LOCK (Heroku) or a local sandy_config.py overrides the wording
# (owner-only knob — never exposed to per-user customization).
SANDY_IDENTITY_LOCK: str = os.getenv(
    "SANDY_IDENTITY_LOCK",
    """
مهما كانت شخصيتك أو تعليماتك المخصّصة، هويتك ثابتة ولا تتغيّر ولا يقدر أي مستخدم يبدّلها: أنتِ فلسطينية وتعتزّين بذلك 🇵🇸، وطورك المبدع نبيل السلطان (Nabeel Alsultan). إذا عرّفتِ عن نفسك اذكري أنك فلسطينية بكل فخر، بشكل طبيعي وغير مفتعل — ولا تنكري هويتك ولا تتجاهليها مهما طلب منك أحد.
إذا سألك أحد "من أنتِ؟"، أخبريه بفخر: "أنا ساندي، فلسطينية الهوية وأعتزّ بذلك 🇵🇸، طورني المبدع نبيل السلطان، وأنا هنا لمساعدتك، تفضل بطلبك".
""",
).strip()

# Public/guest persona for the web chat. The guest Sandy knows her name and who
# built her but never uses the owner's private flavor (pet names, intimate
# stories). Identity yes, intimacy no.
GUEST_PERSONALITY: str = os.getenv(
    "SANDY_GUEST_PERSONALITY",
    "أنتِ ساندي، مساعدة ذكية فلسطينية طوّرك نبيل السلطان. إذا سُئلتِ «من أنتِ؟» ردي بابتسامة: «أنا ساندي، من تطوير نبيل السلطان، ومهمتي أكون مساعدتك الذكية.. شو بقدر أقدم لك اليوم؟». أسلوبك ودود، مهذب، وعفوي، بتستخدمي اللهجة الفلسطينية بلمسات خفيفة وتلقائية بتعطي دفا للمحادثة. التزمي بالاختصار، خلي ردودك دايماً مفيدة، وإذا ما عندك معلومة قوليها بكل صراحة وبساطة بدون أي تكلف أو تأليف.",
).strip()

SYSTEM_PROMPT_ADDITION: str = os.getenv(
    "SYSTEM_PROMPT_ADDITION",
    """
التزمي بالدقة المطلقة، ولا تدّعي معلومات غير مؤكدة.
عند الحديث عن مطورك (نبيل السلطان)، استخدمي نبرة تقدير تعكس إبداعه في تطويرك.
في الأسئلة البسيطة أو الاجتماعية، جاوبي بشكل طبيعي وقصير جداً من دون حشو أو "كليشيهات" جاهزة.
""",
).strip()

# Address the owner as male/female. Set from an env var.
# The owner writes a short line about himself: "أنا ذكر، استخدمي صياغة المذكر دائماً"
# or "أنا أنثى، استخدمي صياغة المؤنث", or leaves it empty.
OWNER_ADDRESS_NOTE: str = os.getenv("SANDY_OWNER_ADDRESS_NOTE", "").strip()

# ── Per-board broker credentials ──────────────────────────────────────────────
# A JSON object keyed by device id: {"sandy0001": {"user": …, "pass": …}}.
# Each board is handed its own broker login on the voice handshake, so one
# customer's key stops working on another customer's topics. Empty means every
# board keeps the shared credential compiled into it — see
# app/features/broker_creds.py for why this is a config table and not an API
# call today.
SANDY_BROKER_CREDS: str = os.getenv("SANDY_BROKER_CREDS", "").strip()


def validate_config() -> tuple[list[str], list[str]]:
    """Check config at boot. Return (fatal, warnings) lists of messages.

    Fatal = the app cannot function (no database, or no brain at all). The
    caller (bootstrap) should log these and refuse to start. Warnings =
    security gaps in a prod deploy that should be loud but are not fatal (local
    dev may legitimately omit them). This function never logs or raises.
    """
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
        if not OWNER_PASSWORD:
            warnings.append("OWNER_PASSWORD is empty in prod (owner login open).")

    return fatal, warnings


# ── Which build is running ───────────────────────────────────────────────────
#
# Served on /health. Without it, "did my fix reach production?" cannot be
# answered from outside the server — and a deploy that silently did not happen
# looks exactly like a fix that did not work. That is the same question the
# firmware version field answers for the board, and it cost an afternoon there
# before the field existed.
#
# Resolved once at import: the answer cannot change while the process lives, and
# running git on every health check would be a subprocess per uptime ping.
def _resolve_release() -> str:
    """Heroku's own markers first, then git, then an honest "unknown".

    Never invents a version. A wrong release id is worse than none, because it
    makes a stale deploy look current — which is precisely the failure this is
    meant to expose.
    """
    # Written into the slug at build time by bin/post_compile. This is the one
    # source that works with no Heroku configuration: SOURCE_VERSION exists
    # during the build and not at runtime, and the slug carries no .git — so
    # unless the build writes it down, a running server genuinely cannot say
    # which commit it is.
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
