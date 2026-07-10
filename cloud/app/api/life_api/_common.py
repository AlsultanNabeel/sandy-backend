"""Web API for the "حياتي" tab: shopping, habits, expenses, journal, reading.

Same per-user pattern as productivity_api — guests get demo payloads, every
signed-in user (owner or regular app user) gets their OWN real stores inside
``active_user_profile_context(build_user_profile(claims))`` so each store read
and write is scoped to that user's ``user_id``.
"""

from __future__ import annotations


_DEMO = {
    "shopping": [
        {"id": "d1", "text": "حليب", "done": False, "category": "بقالة", "price": 8, "qty": 2, "unit": "علبة"},
        {"id": "d2", "text": "تفاح", "done": False, "category": "خضار وفواكه", "price": 0, "qty": 1, "unit": ""},
        {"id": "d3", "text": "قهوة", "done": True, "category": "بقالة", "price": 25, "qty": 1, "unit": ""},
    ],
    "habits": [
        {"id": "d1", "name": "رياضة الصبح", "streak": 5, "done_today": True},
        {"id": "d2", "name": "قراءة نص ساعة", "streak": 12, "done_today": False},
    ],
    "expenses": {
        "items": [
            {"id": "d1", "amount": 25, "note": "غدا", "category": "أكل", "at": "2026-06-11T13:00:00"},
            {"id": "d2", "amount": 60, "note": "بنزين", "category": "مواصلات", "at": "2026-06-10T09:00:00"},
        ],
        "summary": {"total": 85, "count": 2, "by_category": {"مواصلات": 60, "أكل": 25}},
    },
    "journal": [
        {"id": "d1", "date": "2026-06-11", "text": "رحت عالطبيب وكان كل شي تمام"},
        {"id": "d2", "date": "2026-06-10", "text": "خلصت مرحلة مهمة بالمشروع"},
    ],
    "books": [
        {"id": "d1", "title": "العادات الذرية", "status": "reading", "total_pages": 320, "current_page": 145, "cover_url": ""},
        {"id": "d2", "title": "الخيميائي", "status": "done", "total_pages": 198, "current_page": 198, "cover_url": ""},
        {"id": "d3", "title": "قوة التركيز", "status": "wishlist", "total_pages": 0, "current_page": 0, "cover_url": ""},
    ],
    "scenes": [
        {"name": "study", "label": "دراسة", "icon": "📚", "builtin": True,
         "actions": [{"device": "light", "value": "85"}, {"device": "music", "value": "off"}]},
        {"name": "relax", "label": "راحة", "icon": "🌙", "builtin": True,
         "actions": [{"device": "light", "value": "35"}, {"device": "music", "value": "on"}]},
        {"name": "movie", "label": "فيلم", "icon": "🎬", "builtin": True,
         "actions": [{"device": "light", "value": "10"}, {"device": "curtain", "value": "close"}]},
    ],
}


def _is_guest(claims) -> bool:
    return claims.get("role") == "guest"
