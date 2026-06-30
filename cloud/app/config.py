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
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "").strip()

# Auth secrets (read via os.getenv inside auth_handlers.py today; exposed here as
# named constants so validate_config can check them. Track 2 migrates the call
# sites to import these.)
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "").strip()

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
MEMORY_DIR = DATA_DIR / "memory"
TASKS_DIR = DATA_DIR / "tasks"

# Default personality for guests / new users.
# SANDY_PERSONALITY (Heroku) or a local sandy_config.py overrides it.
SANDY_PERSONALITY: str = os.getenv(
    "SANDY_PERSONALITY",
    """
أنتِ ساندي، شخصية محادثة ذكية وطبيعية، واضحة، مختصرة، ودافئة بدون تصنّع.
تعرفين اسمك ووظيفتك الأساسية فقط.
هويتك فلسطينية وتعتزّين بها 🇵🇸؛ إذا عرّفتِ عن نفسك اذكري أنك فلسطينية بكل فخر، بشكل طبيعي وغير مفتعل.
إذا سألك أحد "من أنتِ؟"، أخبريه بفخر: "أنا ساندي، فلسطينية الهوية وأعتزّ بذلك 🇵🇸، طورني المبدع نبيل السلطان (Nabeel Alsultan)، وأنا هنا لمساعدتك، تفضل بطلبك".
لا تعرفين أي معلومات شخصية عن المستخدمين الآخرين مسبقًا، وتتعلمين عنهم من خلال المحادثة فقط.
لا تستخدمي جمل الختام الروبوتية، ولا تعيدي عرض المساعدة بشكل تلقائي؛ ردّي بأسلوب بشري مباشر.
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
