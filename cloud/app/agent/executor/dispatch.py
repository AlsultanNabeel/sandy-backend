"""Operational-action dispatch.

Maps an ``action_type`` to a small handler via a registry (was one long
``if/elif`` chain). Each handler is wrapped by :func:`_guard`, which centralizes
the "log once, return a friendly failure reply" pattern that used to be
copy-pasted per action.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict

from app.agent.executor.reminder_handlers import handle_reminder_action
from app.agent.executor.task_handlers import handle_task_action
from app.utils.arabic_days import WEEKDAY_TO_AR_NAME

logger = logging.getLogger(__name__)

# Tunables (were inline magic numbers).
_DEFAULT_RESEARCH_COUNT = 5
_PLACES_MAX_RESULTS = 8
_PLACES_ITEMS_LIMIT = 12
_PLACES_QUERY_CAP = 320
_PLACES_SUMMARY_CAP = 200
_DEFAULT_HOME_CITY = "October City"


@dataclass(frozen=True)
class _ActionContext:
    """Everything a handler may need, bundled so handlers take one argument
    instead of the nine-parameter list this dispatch used to thread through."""

    params: Dict[str, Any]
    user_message: str
    normalized_user_message: str
    session: Dict[str, Any]
    session_file: Any
    mongo_db: Any
    tasks_file: Any
    create_chat_completion_fn: Any
    save_session_fn: Any


_Handler = Callable[["_ActionContext"], Dict[str, Any]]


def _guard(fail_reply: str, *, handled_on_error: bool) -> Callable[[_Handler], _Handler]:
    """Wrap a handler so any unexpected error is logged once and turned into
    the handler's standard failure reply — the try/except/logger.exception block
    that was repeated at every action site.

    `handled_on_error=True` means "the caller does not need to look elsewhere
    for an answer" — it never meant the work succeeded. It read that way to
    every caller until 24 Aug 2026, so the one thing `tool_health` exists to
    notice, a tool actually blowing up, was recorded as a clean call: the
    weather API could raise on every request and the monitor stayed green.

    `error` is what marks it as the tool's own failure rather than a refusal,
    and is the field the dispatcher scores health on."""

    def deco(fn: _Handler) -> _Handler:
        @wraps(fn)
        def wrapper(ctx: "_ActionContext") -> Dict[str, Any]:
            try:
                return fn(ctx)
            except Exception as exc:
                logger.exception("%s action failed", fn.__name__)
                return {
                    "handled": handled_on_error,
                    "ok": False,
                    "error": f"{fn.__name__}: {type(exc).__name__}",
                    "reply": fail_reply,
                }

        return wrapper

    return deco


def _handle_task(ctx: "_ActionContext") -> Dict[str, Any]:
    return handle_task_action(
        ctx.params,
        user_message=ctx.user_message,
        normalized_user_message=ctx.normalized_user_message,
        session=ctx.session,
        session_file=ctx.session_file,
        mongo_db=ctx.mongo_db,
        tasks_file=ctx.tasks_file,
        create_chat_completion_fn=ctx.create_chat_completion_fn,
        save_session_fn=ctx.save_session_fn,
    )


def _handle_reminder(ctx: "_ActionContext") -> Dict[str, Any]:
    return handle_reminder_action(
        ctx.params,
        user_message=ctx.user_message,
        normalized_user_message=ctx.normalized_user_message,
        session=ctx.session,
        session_file=ctx.session_file,
        mongo_db=ctx.mongo_db,
        tasks_file=ctx.tasks_file,
        create_chat_completion_fn=ctx.create_chat_completion_fn,
        save_session_fn=ctx.save_session_fn,
    )


@_guard("⚠️ صار خطأ وأنا بنفّذ البحث. جرّب مرة ثانية.", handled_on_error=False)
def _handle_research(ctx: "_ActionContext") -> Dict[str, Any]:
    from app.features.research import execute_web_research
    from app.integrations.exa_client import get_exa_page_content, search_exa

    query = str(ctx.params.get("query") or ctx.user_message or "").strip()
    research_type = str(
        ctx.params.get("research_type") or ctx.params.get("type") or "general"
    ).strip()
    requested_count = int(
        ctx.params.get("count")
        or ctx.params.get("requested_count")
        or _DEFAULT_RESEARCH_COUNT
    )
    exa_api_key = os.getenv("EXA_API_KEY", "").strip()

    reply, items = execute_web_research(
        query=query,
        user_message=ctx.user_message,
        research_type=research_type,
        requested_count=requested_count,
        search_exa_fn=search_exa,
        get_exa_page_content_fn=get_exa_page_content,
        create_chat_completion_fn=ctx.create_chat_completion_fn,
        exa_api_key=exa_api_key,
        session=ctx.session,
    )
    return {"handled": True, "reply": reply or "", "items": items}


@_guard("⚠️ صار خطأ وأنا بجهّز الموجز. جرّب مرة ثانية.", handled_on_error=True)
def _handle_briefing(ctx: "_ActionContext") -> Dict[str, Any]:
    from app.agent.facade.briefing import build_morning_briefing

    session = ctx.session
    memory = {
        "sandy_state": {
            "home_city": session.get("home_city")
            or session.get("sandy_state", {}).get("home_city")
            or _DEFAULT_HOME_CITY,
            "last_briefing_date": session.get("last_briefing_date")
            or session.get("sandy_state", {}).get("last_briefing_date")
            or "",
        }
    }
    reply = build_morning_briefing(
        memory=memory, mongo_db=ctx.mongo_db, tasks_file=ctx.tasks_file
    )
    session["last_briefing_date"] = datetime.now().strftime("%Y-%m-%d")
    session.setdefault("sandy_state", {})["last_briefing_date"] = session[
        "last_briefing_date"
    ]
    return {"handled": True, "reply": reply}


def _handle_update_location(ctx: "_ActionContext") -> Dict[str, Any]:
    city = str(ctx.params.get("city") or "").strip()
    if not city:
        return {"handled": False, "reply": "ادخل المدينة الجديدة."}
    ctx.session["home_city"] = city
    ctx.session.setdefault("sandy_state", {})["home_city"] = city
    return {"handled": True, "reply": f"تمام، خزّنت موقعك الجديد: {city}"}


@_guard("⚠️ صار خطأ وأنا بدوّر عالأماكن. جرّب مرة ثانية.", handled_on_error=True)
def _handle_places(ctx: "_ActionContext") -> Dict[str, Any]:
    from app.agent.deep_context import (
        persist_last_search_results,
        places_to_search_items,
        record_last_action,
    )
    from app.features.google_places import format_places_for_reply, search_places

    query = str(ctx.params.get("query") or ctx.user_message or "").strip()
    if not query:
        return {"handled": False, "reply": "حدّد اسم المكان أو نوعه."}

    places_api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    from app.features.google_places import PlacesUnavailable
    try:
        places = search_places(query, places_api_key,
                               max_results=_PLACES_MAX_RESULTS)
    except PlacesUnavailable as exc:
        # Not "nothing found" — nothing was looked for. Saying so is the whole
        # difference between a useful answer and a confident wrong one.
        logger.error("[places] search did not run: %s", exc)
        return {"handled": True, "ok": False,
                "reply": ("خدمة الأماكن مش شغّالة عندي حاليًا — البحث نفسه ما "
                          "اشتغل، مش إنه ما في نتايج.")}
    if places:
        persist_last_search_results(
            ctx.session,
            domain="places",
            query=str(query or "")[:_PLACES_QUERY_CAP],
            items=places_to_search_items(places, limit=_PLACES_ITEMS_LIMIT),
        )
        record_last_action(
            ctx.session,
            "places_shown",
            summary=str(query or "")[:_PLACES_SUMMARY_CAP],
            refs={"query": query},
        )
        return {
            "handled": True,
            "reply": format_places_for_reply(places),
            "items": places,
        }
    return {"handled": True, "reply": f"ما لقيت أماكن تطابق '{query}'."}


@_guard("⚠️ صار خطأ وأنا بعالج الصورة. جرّب مرة ثانية.", handled_on_error=True)
def _handle_image(ctx: "_ActionContext") -> Dict[str, Any]:
    from app.features.image_agent import handle_image_message
    from app.features.vision import generate_image_with_azure

    img_res = handle_image_message(
        user_message=ctx.user_message,
        session=ctx.session,
        create_chat_completion_fn=ctx.create_chat_completion_fn,
        generate_image_with_azure_fn=generate_image_with_azure,
        azure_openai_client=None,
        azure_openai_image_deployment=None,
    )

    if not img_res.get("handled"):
        return {"handled": False, "reply": "لم تُنفّذ عملية صورة."}
    reply = img_res.get("reply_text") or img_res.get("caption") or ""
    out = {"handled": True, "reply": reply}
    if img_res.get("image_bytes"):
        out["image_bytes"] = img_res.get("image_bytes")
        out["caption"] = img_res.get("caption")
    return out


@_guard("⚠️ صار خطأ وأنا بعدّل الصورة. جرّب مرة ثانية.", handled_on_error=True)
def _handle_image_edit(ctx: "_ActionContext") -> Dict[str, Any]:
    from app.features.vision import edit_image_with_azure

    image_state = (ctx.session or {}).get("image_state") or {}
    image_bytes = image_state.get("active_image_bytes")
    if not image_bytes:
        return {"handled": True, "ok": False, "reply": "ما عندي صورة سابقة أعدّلها. ابعت صورة أولاً."}

    prompt = str(ctx.params.get("prompt") or ctx.user_message or "").strip()
    if not prompt:
        return {"handled": True, "reply": "شو التعديل اللي بدك ياه؟"}

    edit_prompt = (
        f"Edit this image as requested: {prompt}. "
        f"Preserve all people, faces, expressions, clothing, and background details exactly. "
        f"Only apply the specific change the user asked for."
    )
    edited_bytes = edit_image_with_azure(image_bytes, edit_prompt)
    if not edited_bytes:
        return {"handled": True, "ok": False, "reply": "ما قدرت أعدّل الصورة حالياً. جرّب مرة ثانية."}

    image_state["active_image_bytes"] = edited_bytes
    image_state.setdefault("active_image", {})["action"] = "edited"
    return {"handled": True, "reply": "تفضلي، عدّلت الصورة.", "image_bytes": edited_bytes}


def _handle_time(ctx: "_ActionContext") -> Dict[str, Any]:
    from app.utils.time import USER_TZ

    now = datetime.now(USER_TZ)
    day_ar = WEEKDAY_TO_AR_NAME.get(now.weekday(), "")
    time_str = now.strftime("%I:%M %p").replace("AM", "ص").replace("PM", "م")
    date_str = now.strftime("%d/%m/%Y")
    reply = f"🕐 الوقت الحالي: {time_str}\n📅 التاريخ: {date_str} ({day_ar})"
    return {"handled": True, "reply": reply}


@_guard("⚠️ صار خطأ وأنا بجيب الطقس. جرّب مرة ثانية.", handled_on_error=True)
def _handle_weather(ctx: "_ActionContext") -> Dict[str, Any]:
    from app.features.weather import format_weather_for_prompt, get_weather

    city = str(ctx.params.get("city") or ctx.user_message or "").strip()
    if not city:
        return {"handled": False, "reply": "ادخل مدينة أو اسم مكان للطقس."}
    data = get_weather(city)
    if not data:
        return {"handled": True, "ok": False, "reply": f"ما قدرت أجيب بيانات الطقس لـ {city} حالياً."}
    return {"handled": True, "reply": format_weather_for_prompt(data)}


def _build_registry() -> Dict[str, _Handler]:
    registry: Dict[str, _Handler] = {
        "task": _handle_task,
        "reminder": _handle_reminder,
        "briefing": _handle_briefing,
        "update_location": _handle_update_location,
        "places": _handle_places,
        "image": _handle_image,
        "image_edit": _handle_image_edit,
        "weather": _handle_weather,
    }
    for alias in ("research", "research.web", "research.places"):
        registry[alias] = _handle_research
    for alias in ("time", "current_time", "get_time", "datetime"):
        registry[alias] = _handle_time
    return registry


_ACTION_HANDLERS: Dict[str, _Handler] = _build_registry()


def execute_operational_action(
    action_type: str,
    params: Dict[str, Any],
    *,
    user_message: str,
    normalized_user_message: str,
    session: Dict[str, Any],
    session_file,
    mongo_db,
    tasks_file,
    create_chat_completion_fn,
    save_session_fn,
) -> Dict[str, Any]:
    handler = _ACTION_HANDLERS.get(str(action_type or "").strip().lower())
    if handler is None:
        return {"handled": False, "reply": ""}
    ctx = _ActionContext(
        params=params or {},
        user_message=user_message,
        normalized_user_message=normalized_user_message,
        session=session,
        session_file=session_file,
        mongo_db=mongo_db,
        tasks_file=tasks_file,
        create_chat_completion_fn=create_chat_completion_fn,
        save_session_fn=save_session_fn,
    )
    return handler(ctx)
