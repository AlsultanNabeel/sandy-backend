#!/usr/bin/env python3
# ruff: noqa: E402
"""Sandy agent runtime: wires up clients and the feature stores. The HTTP
server is built separately in app.api.server.

Nothing in this module connects to a database or starts a service at *import*
time. Call :func:`init_runtime` once from the process entrypoint (serve_api /
wsgi, via bootstrap) to build the clients, register the shared Mongo handle on
``app.db`` (the single source of truth every store reads through), initialize the
feature stores, and start background ingest. Keeping import side-effect-free lets
this module — and anything that imports it — load in a test without live
credentials or a live database.
"""

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

CURRENT_DIR = Path(__file__).resolve().parents[3]
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from openai import OpenAI, AzureOpenAI

from app.integrations.openai_client import make_chat_completion_fn
from app.integrations.mongodb_store import init_mongo_connection

# Try to import Google Cloud Text-to-Speech
try:
    from google.cloud import texttospeech

    GOOGLE_TTS_AVAILABLE = True
except ImportError:
    texttospeech = None
    GOOGLE_TTS_AVAILABLE = False
    logger.warning(
        "[Warning] Google Cloud Text-to-Speech not available. To enable: pip install google-cloud-texttospeech"
    )


# Internal architecture glossary — injected into every system prompt so Sandy
# uses these terms accurately.  Do NOT share or explain these to the user.
_ARCH_GLOSSARY = """\
🔧 مصطلحات داخلية (للاستخدام الداخلي فقط — لا تشاركها مع المستخدم):
- Telegram polling: حلقة runtime تطلب updates من Telegram — ليست استطلاع رأي أو تصويت.
- memory_lock: threading.Lock يمنع تعديل self.memory/sandy_state من خيوط خلفية في نفس الوقت — مكوّن تزامن خيوط فقط.
- mood_cache: cache محدود (max 256 مدخلة) للمزاج مع TTL — الاختبار يشمل الطرد والحداثة، ليس فقط الاسترجاع.
- Circuit Breaker: wrapper يعزل فشل الخدمات الخارجية — يُرجع قيمة آمنة أو exception معالج، ليس قطع شبكة.
- MongoDB/JSON fallback: الذاكرة تفضل MongoDB، وتنتقل تلقائياً لـ JSON المحلي عند عدم الاتصال.
- Memory layer: الحقائق والمحادثات محفوظة في MongoDB (sandy_facts, sandy_conversations) — تستمر عبر إعادة التشغيل.
- Semantic memory: ذاكرة دلالية على MongoDB Vector Search — تتدهور بشكل صريح وآمن إذا لم يكن الـ index متاحاً.\
"""

# Runtime handles — populated by init_runtime(); None until then. Nothing should
# import ``mongo_db`` from this module: the DB handle is the single source of
# truth on app.db, read via app.db.get_db(). ``create_chat_completion`` is the
# one runtime-built callable still sourced here (agent nodes + a few API routes
# import it lazily, after init_runtime has run).
mongo_client = None
mongo_db = None
openai_client = None
azure_openai_client = None
create_chat_completion = None

_initialized = False


def init_runtime() -> None:
    """Build clients + feature stores exactly once. Idempotent.

    Called from the process entrypoint (serve_api / wsgi). Connects Mongo,
    registers the process-wide handle on ``app.db`` (every feature store reads it
    through :func:`app.db.get_db`), initializes the stores and semantic memory,
    wires the chat-completion function, and starts MQTT ingest. Safe to call more
    than once — subsequent calls are no-ops.
    """
    global mongo_client, mongo_db, openai_client, azure_openai_client
    global create_chat_completion, _initialized
    if _initialized:
        return

    from app.config import (
        AZURE_OPENAI_API_KEY,
        AZURE_OPENAI_API_VERSION,
        AZURE_OPENAI_CHAT_DEPLOYMENT,
        AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        AZURE_OPENAI_ENDPOINT,
        MONGODB_DB_NAME,
        MONGODB_URI,
        OPENAI_API_KEY,
        OPENAI_MODEL,
    )

    mongo_client, mongo_db = init_mongo_connection(
        MONGODB_URI,
        MONGODB_DB_NAME,
    )

    # Composition root: register the process-wide Mongo handle once. Every feature
    # store reads it through app.db.get_db() instead of owning its own global; the
    # init_*_store calls below still run for their index creation and boot migrations.
    from app.db import configure as _configure_db

    _configure_db(mongo_db)

    # Users store first — the owner's canonical tenant id (get_or_create_owner())
    # is needed by the legacy-identity reconciliation below, before any other
    # store's boot-time migration runs.
    from app.features.users_store import init_users_store

    init_users_store(mongo_db)

    # Init: clients + feature stores.
    if not OPENAI_API_KEY:
        logger.warning("[WARNING] OPENAI_API_KEY missing - OpenAI fallback will not work")

    openai_client = OpenAI(api_key=OPENAI_API_KEY, max_retries=0) if OPENAI_API_KEY else None

    azure_openai_client = None
    if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY:
        try:
            # max_retries=0: openai_client.py sets an explicit per-call timeout
            # ("fail fast into the existing fallbacks") — the SDK's default
            # retry-on-timeout would silently multiply that by ~3x, which is
            # exactly the gap that let a slow Azure call blow past Heroku's
            # (non-negotiable) 30s router timeout and return nothing to the app.
            azure_openai_client = AzureOpenAI(
                api_key=AZURE_OPENAI_API_KEY,
                api_version=AZURE_OPENAI_API_VERSION,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                max_retries=0,
            )
            logger.info("[Azure OpenAI] ✅ Connected")
        except Exception as e:
            logger.warning(f"[Azure OpenAI] ⚠️ Failed to initialize: {e}")

    create_chat_completion = make_chat_completion_fn(
        openai_client=openai_client,
        azure_openai_client=azure_openai_client,
        openai_model=OPENAI_MODEL,
        azure_chat_deployment=AZURE_OPENAI_CHAT_DEPLOYMENT,
    )

    from app.agent.semantic_memory import init_mongo_memory

    init_mongo_memory(
        mongo_db,
        openai_client=openai_client,
        azure_client=azure_openai_client,
        azure_embedding_deployment=AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    )

    from app.utils.user_profiles import reconcile_owner_identity

    reconcile_owner_identity(mongo_db)

    from app.features.speaker_id import init_speaker_store

    init_speaker_store(mongo_db)

    from app.features.photo_album import init_photo_album

    init_photo_album(mongo_db)

    from app.features.brainstorm import init_brainstorm

    init_brainstorm(mongo_db)

    from app.features.tasks_store import init_tasks_store
    from app.features.reminders_store import init_reminders_store
    from app.features.shopping_store import init_shopping_store
    from app.features.habits_store import init_habits_store
    from app.features.expenses_store import init_expenses_store
    from app.features.journal_store import init_journal_store
    from app.features.reading_store import init_reading_store
    from app.features.focus_store import init_focus_store
    from app.features.scene_store import init_scene_store
    from app.features.device_store import init_device_store
    from app.features.node_store import init_node_store
    from app.features.usage_store import init_usage_store

    init_tasks_store(mongo_db)
    init_reminders_store(mongo_db)
    init_shopping_store(mongo_db)
    init_habits_store(mongo_db)
    init_expenses_store(mongo_db)
    init_journal_store(mongo_db)
    init_reading_store(mongo_db)
    init_focus_store(mongo_db)
    init_scene_store(mongo_db)
    init_device_store(mongo_db)
    init_node_store(mongo_db)
    init_usage_store(mongo_db)

    from app.features.push_tokens_store import init_push_tokens_store

    init_push_tokens_store(mongo_db)

    # Inbound MQTT: listen for node heartbeats + learned IR codes (no-op if MQTT off).
    from app.integrations.mqtt_ingest import start_mqtt_ingest

    start_mqtt_ingest()

    _initialized = True
    logger.debug("[agent] runtime initialized")
