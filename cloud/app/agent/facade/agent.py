#!/usr/bin/env python3
# ruff: noqa: E402
"""Sandy agent runtime: wires up clients, the feature stores, and the shared
agent instance. The HTTP server is built separately in app.api.server."""

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CURRENT_DIR = Path(__file__).resolve().parents[3]
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from openai import OpenAI, AzureOpenAI

from app.agent.memory import (
    load_memory,
    load_session,
)
from app.integrations.openai_client import make_chat_completion_fn
from app.integrations.mongodb_store import init_mongo_connection
from app.agent.facade.briefing import build_morning_briefing

# Try to import Azure Speech SDK for text-to-speech
try:
    import azure.cognitiveservices.speech as speechsdk

    AZURE_SPEECH_AVAILABLE = True
except ImportError:
    speechsdk = None
    AZURE_SPEECH_AVAILABLE = False
    print(
        "[Warning] Azure Speech SDK not available. To enable: pip install azure-cognitiveservices-speech"
    )


# Try to import Google Cloud Text-to-Speech
try:
    from google.cloud import texttospeech

    GOOGLE_TTS_AVAILABLE = True
except ImportError:
    texttospeech = None
    GOOGLE_TTS_AVAILABLE = False
    print(
        "[Warning] Google Cloud Text-to-Speech not available. To enable: pip install google-cloud-texttospeech"
    )


from app.config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_CHAT_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
    MEMORY_DIR,
    MONGODB_DB_NAME,
    MONGODB_URI,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    TASKS_DIR,
)

mongo_client, mongo_db = init_mongo_connection(
    MONGODB_URI,
    MONGODB_DB_NAME,
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

MEMORY_FILE = MEMORY_DIR / "sandy_agent_memory.json"
SESSION_FILE = MEMORY_DIR / "sandy_session_memory.json"
TASKS_FILE = TASKS_DIR / "daily_plan.json"


# Init: clients + feature stores.
if not OPENAI_API_KEY:
    print("[WARNING] OPENAI_API_KEY missing - OpenAI fallback will not work")

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

azure_openai_client = None
if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY:
    try:
        azure_openai_client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
        )
        print("[Azure OpenAI] ✅ Connected")
    except Exception as e:
        print(f"[Azure OpenAI] ⚠️ Failed to initialize: {e}")

create_chat_completion = make_chat_completion_fn(
    openai_client=openai_client,
    azure_openai_client=azure_openai_client,
    openai_model=OPENAI_MODEL,
    azure_chat_deployment=AZURE_OPENAI_CHAT_DEPLOYMENT,
)

from app.agent.semantic_memory import init_mongo_memory

init_mongo_memory(mongo_db, openai_client=openai_client)

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
from app.features.users_store import init_users_store
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
init_users_store(mongo_db)
init_usage_store(mongo_db)


class SandyAgent:
    def __init__(
        self,
        *,
        memory_file,
        session_file,
        mongo_db,
        tasks_file,
    ):
        self.memory_file = memory_file
        self.session_file = session_file
        self.mongo_db = mongo_db
        self.tasks_file = tasks_file

        self.memory = load_memory(memory_file=self.memory_file, mongo_db=self.mongo_db)
        self.memory.setdefault("conversations", [])
        self.memory.setdefault("facts", [])
        self.memory.setdefault("sandy_state", {})
        self.session = load_session(
            session_file=self.session_file, mongo_db=self.mongo_db
        )
        self.session.setdefault("pending_action", None)
        self.is_speaking = False
        self.last_activity = datetime.now()
        self.last_briefing_date = self.memory.get("sandy_state", {}).get(
            "last_briefing_date", ""
        )
        # Protects concurrent writes to self.memory["sandy_state"] from background threads
        self._memory_lock = threading.Lock()

    def _build_morning_briefing(self) -> str:
        return build_morning_briefing(
            memory=self.memory,
            mongo_db=self.mongo_db,
            tasks_file=self.tasks_file,
        )



# The shared agent instance, used by the HTTP API (serve_api.py) and the
# agent pipeline. The app's Flask server is built by app.api.server.create_app.
agent = SandyAgent(
    memory_file=MEMORY_FILE,
    session_file=SESSION_FILE,
    mongo_db=mongo_db,
    tasks_file=TASKS_FILE,
)
