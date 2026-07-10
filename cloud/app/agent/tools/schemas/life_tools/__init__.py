"""Daily-life tools (shopping/habits/expenses/journal/books/reading/focus/scenes),
split by domain. Public surface is unchanged: import LIFE_TOOLS or any
handler from app.agent.tools.schemas.life_tools as before.
"""
from app.agent.tools.schemas.life_tools.shopping import (
    shopping_add,
    shopping_list,
    shopping_check,
    shopping_remove,
)
from app.agent.tools.schemas.life_tools.habits import (
    habit_add,
    habit_checkin,
    habit_list,
)
from app.agent.tools.schemas.life_tools.expenses import (
    expense_add,
    expense_summary,
)
from app.agent.tools.schemas.life_tools.journal import (
    journal_add,
    journal_show,
    journal_search,
)
from app.agent.tools.schemas.life_tools.books import (
    book_add,
    book_list,
    book_status,
    book_meta,
    book_note,
    book_quote,
    reading_goal,
    reading_start,
    reading_pause,
    reading_stop,
)
from app.agent.tools.schemas.life_tools.focus import (
    focus_start,
    focus_stop,
    focus_check,
    focus_sound,
    focus_goal,
    focus_review,
)
from app.agent.tools.schemas.life_tools.scenes import (
    scene_apply,
    actuate_scene_actions,
    scene_list,
)


LIFE_TOOLS = [
    {
        "name": "shopping_add",
        "description": "أضف عنصر أو أكثر لقائمة التسوق — «ضيفي حليب عالتسوق»",
        "parameters": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "عنصر واحد"},
                "items": {"type": "array", "items": {"type": "string"}, "description": "عدة عناصر دفعة واحدة"},
            },
            "required": [],
        },
        "handler": shopping_add,
    },
    {
        "name": "shopping_list",
        "description": "اعرض قائمة التسوق الحالية",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": shopping_list,
    },
    {
        "name": "shopping_check",
        "description": "اشطب عنصر من قائمة التسوق (انشترى) — «اشتريت الحليب»",
        "parameters": {
            "type": "object",
            "properties": {"item": {"type": "string", "description": "اسم العنصر"}},
            "required": ["item"],
        },
        "handler": shopping_check,
    },
    {
        "name": "shopping_remove",
        "description": "احذف عنصر من قائمة التسوق بدون شراء — «شيلي الحليب من القائمة»",
        "parameters": {
            "type": "object",
            "properties": {"item": {"type": "string", "description": "اسم العنصر"}},
            "required": ["item"],
        },
        "handler": shopping_remove,
    },
    {
        "name": "habit_add",
        "description": "أضف عادة يومية جديدة للتتبع — «ضيفي عادة الرياضة»",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "اسم العادة"}},
            "required": ["name"],
        },
        "handler": habit_add,
    },
    {
        "name": "habit_checkin",
        "description": "سجل إنجاز عادة اليوم — «تمرنت اليوم» / «صليت» / «قريت»",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "اسم العادة"}},
            "required": ["name"],
        },
        "handler": habit_checkin,
    },
    {
        "name": "habit_list",
        "description": "اعرض العادات وسلاسل الإنجاز — «وين وصلت بعاداتي»",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": habit_list,
    },
    {
        "name": "expense_add",
        "description": "سجل مصروف — «صرفت عشرين على غدا». المبلغ إجباري",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "المبلغ"},
                "note": {"type": "string", "description": "على شو (غدا، بنزين...)"},
                "category": {"type": "string", "description": "تصنيف اختياري: أكل/مواصلات/فواتير/ترفيه/أخرى"},
            },
            "required": ["amount"],
        },
        "handler": expense_add,
    },
    {
        "name": "expense_summary",
        "description": "ملخص المصاريف — «قديش صرفت هالشهر»",
        "parameters": {
            "type": "object",
            "properties": {"days": {"type": "number", "description": "الفترة بالأيام (افتراضي 30)"}},
            "required": [],
        },
        "handler": expense_summary,
    },
    {
        "name": "journal_add",
        "description": "دوّن باليوميات — «دوني إني رحت عالطبيب اليوم»",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "نص التدوينة"}},
            "required": ["text"],
        },
        "handler": journal_add,
    },
    {
        "name": "journal_show",
        "description": "اعرض اليوميات — «شو دونتيلي اليوم/مبارح»",
        "parameters": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "تاريخ YYYY-MM-DD اختياري — بدونه آخر التدوينات"}},
            "required": [],
        },
        "handler": journal_show,
    },
    {
        "name": "journal_search",
        "description": "فتش باليوميات — «إيمتى آخر مرة رحت عالطبيب؟»",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "كلمة البحث"}},
            "required": ["query"],
        },
        "handler": journal_search,
    },
    {
        "name": "book_add",
        "description": "سجل كتاب — «ضيفي كتاب العادات الذرية لجيمس كلير 300 صفحة». status: reading|done|wishlist",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "اسم الكتاب"},
                "author": {"type": "string", "description": "الكاتب (اختياري)"},
                "category": {"type": "string", "description": "التصنيف/النوع — تطوير ذات، رواية، تاريخ... (اختياري)"},
                "fmt": {"type": "string", "description": "الصيغة: paper | ebook | audio (اختياري)"},
                "status": {"type": "string", "description": "reading (افتراضي) | done | wishlist (ناوي يقراه)"},
                "total_pages": {"type": "number", "description": "عدد الصفحات الكلي (اختياري)"},
                "current_page": {"type": "number", "description": "الصفحة الحالية لو بلش فيه (اختياري)"},
                "cover_url": {"type": "string", "description": "رابط صورة الغلاف (اختياري)"},
            },
            "required": ["title"],
        },
        "handler": book_add,
    },
    {
        "name": "book_meta",
        "description": "حدّث بيانات كتاب: تقييم نجوم/كاتب/تصنيف/صيغة/صفحات — «قيّمي الخيميائي ٥ نجوم» أو «كاتب العادات الذرية جيمس كلير»",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "اسم الكتاب"},
                "rating": {"type": "number", "description": "تقييم 0..5 نجوم"},
                "author": {"type": "string", "description": "الكاتب"},
                "category": {"type": "string", "description": "التصنيف/النوع"},
                "fmt": {"type": "string", "description": "paper | ebook | audio"},
                "total_pages": {"type": "number", "description": "عدد الصفحات الكلي"},
                "current_page": {"type": "number", "description": "الصفحة الحالية"},
            },
            "required": ["title"],
        },
        "handler": book_meta,
    },
    {
        "name": "book_note",
        "description": "ضيف ملاحظة على كتاب — «دوني ملاحظة على العادات الذرية: ...»",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "اسم الكتاب"},
                "text": {"type": "string", "description": "نص الملاحظة"},
            },
            "required": ["title", "text"],
        },
        "handler": book_note,
    },
    {
        "name": "book_quote",
        "description": "احفظ اقتباس من كتاب — «اقتباس من الخيميائي صفحة ٤٢: ...»",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "اسم الكتاب"},
                "text": {"type": "string", "description": "نص الاقتباس"},
                "page": {"type": "number", "description": "رقم الصفحة (اختياري)"},
            },
            "required": ["title", "text"],
        },
        "handler": book_quote,
    },
    {
        "name": "reading_goal",
        "description": "هدف القراءة السنوي أو متابعته — «هدفي ٢٤ كتاب بالسنة» أو «وين وصلت بهدف القراءة؟»",
        "parameters": {
            "type": "object",
            "properties": {
                "books_year": {"type": "number", "description": "عدد الكتب المستهدفة بالسنة (لتعيين الهدف)"},
                "pages_year": {"type": "number", "description": "عدد الصفحات المستهدفة بالسنة (اختياري)"},
            },
            "required": [],
        },
        "handler": reading_goal,
    },
    {
        "name": "book_list",
        "description": "اعرض الكتب — «شو كتبي» / «شو قيد القراءة». فلتر اختياري: reading|done|wishlist",
        "parameters": {
            "type": "object",
            "properties": {"status": {"type": "string", "description": "reading | done | wishlist — فاضي للكل"}},
            "required": [],
        },
        "handler": book_list,
    },
    {
        "name": "book_status",
        "description": "غيّر حالة كتاب — «خلصت كتاب كذا» (done) / «حطيه بقائمة القراءة» (wishlist)",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "اسم الكتاب"},
                "status": {"type": "string", "description": "reading | done | wishlist"},
            },
            "required": ["title", "status"],
        },
        "handler": book_status,
    },
    {
        "name": "reading_start",
        "description": "ابدأ جلسة قراءة — «بديت أقرا» / «بدي أقرا كتاب كذا». بدون اسم بكمل بآخر كتاب قيد القراءة",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "اسم الكتاب (اختياري)"}},
            "required": [],
        },
        "handler": reading_start,
    },
    {
        "name": "reading_pause",
        "description": "توقف مؤقت أو استئناف للقراءة — «توقف مؤقت» / «كمل قراءة» (resume=true)",
        "parameters": {
            "type": "object",
            "properties": {"resume": {"type": "boolean", "description": "true للاستئناف بعد توقف مؤقت"}},
            "required": [],
        },
        "handler": reading_pause,
    },
    {
        "name": "reading_stop",
        "description": "أنهِ جلسة القراءة — «وقفت». بدون رقم صفحة ساندي بتسأل «وين وصلت؟» وبعدها نادِها مع page",
        "parameters": {
            "type": "object",
            "properties": {"page": {"type": "number", "description": "رقم الصفحة اللي وصلها"}},
            "required": [],
        },
        "handler": reading_stop,
    },
    {
        "name": "focus_start",
        "description": "ابدأ جلسة تركيز أو بومودورو — «بدي أركز ساعة عالدراسة» أو «بومودورو ٢٥ تركيز ٥ راحة ٤ دورات». بتقدر تربطها بمشهد غرفة (دراسة/قراءة/عصف ذهني...) فيشتغل تلقائياً",
        "parameters": {
            "type": "object",
            "properties": {
                "minutes": {"type": "number", "description": "مدة التركيز بالدقائق (افتراضي 25)"},
                "label": {"type": "string", "description": "على شو التركيز (اختياري)"},
                "break_min": {"type": "number", "description": "مدة الراحة بين الدورات بالدقائق (0 = بدون بومودورو)"},
                "cycles": {"type": "number", "description": "عدد دورات البومودورو (افتراضي 1)"},
                "scene": {"type": "string", "description": "مشهد غرفة يشتغل عند البدء: study|read|brainstorm|relax|movie|sleep|morning أو اسم مشهد مخصص"},
                "end_scene": {"type": "string", "description": "مشهد يشتغل لما تخلص الجلسة (اختياري؛ بدونه الغرفة بتضل على حالها)"},
            },
            "required": [],
        },
        "handler": focus_start,
    },
    {
        "name": "focus_stop",
        "description": "أنهِ جلسة تركيز/بومودورو شغّالة فقط — «خلصت الجلسة» (إنجاز) أو «ألغي التركيز» (cancel=true). لا تستدعِ هذا لأمر غرفة — «طفّي الضو» مشهد غرفة (scene_apply) مش إنهاء جلسة.",
        "parameters": {
            "type": "object",
            "properties": {"cancel": {"type": "boolean", "description": "true للإلغاء بدون احتفال"}},
            "required": [],
        },
        "handler": focus_stop,
    },
    {
        "name": "focus_check",
        "description": "حالة جلسة التركيز — «قديش ضايل؟»",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": focus_check,
    },
    {
        "name": "focus_sound",
        "description": "غيّر أو اعرض صوت تنبيه التركيز — «خلي صوت بداية التركيز happy» أو «شو أصوات التركيز؟». الأحداث: start|break|end",
        "parameters": {
            "type": "object",
            "properties": {
                "event": {"type": "string", "description": "أي صوت: start (بداية) | break (راحة) | end (نهاية)"},
                "melody": {"type": "string", "description": "النغمة: focus_start|focus_break|focus_end|happy|curious|boot|alert|sad|error"},
            },
            "required": [],
        },
        "handler": focus_sound,
    },
    {
        "name": "focus_goal",
        "description": "حدّد أو اعرض هدف دقايق التركيز لكل فترة — «خلي هدفي اليومي ساعتين تركيز» أو «شو أهداف التركيز؟». الفترات: day|week|month|year",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "الفترة: day (يومي) | week (أسبوعي) | month (شهري) | year (سنوي)"},
                "minutes": {"type": "integer", "description": "عدد دقايق التركيز المستهدفة لهالفترة"},
            },
            "required": [],
        },
        "handler": focus_goal,
    },
    {
        "name": "focus_review",
        "description": "اعرض إحصائيات التركيز (اليوم/الأسبوع/الشهر/السنة) والتقدّم نحو الأهداف — «قديش ركزت هالأسبوع؟» أو «وريني إحصائيات الدراسة»",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": focus_review,
    },
    {
        "name": "scene_apply",
        "description": "شغّل مشهد غرفة (ضو/لون/موسيقى/مروحة...) — «شغّلي وضع الفيلم» أو «جو دراسة». الأوضاع: study|read|brainstorm|relax|movie|sleep|morning|off",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "اسم المشهد: study|read|brainstorm|relax|movie|sleep|morning|off أو مخصص"},
            },
            "required": ["name"],
        },
        "handler": scene_apply,
    },
    {
        "name": "scene_list",
        "description": "اعرض مشاهد الغرفة المتاحة",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": scene_list,
    },
]



__all__ = [
    "shopping_add",
    "shopping_list",
    "shopping_check",
    "shopping_remove",
    "habit_add",
    "habit_checkin",
    "habit_list",
    "expense_add",
    "expense_summary",
    "journal_add",
    "journal_show",
    "journal_search",
    "book_add",
    "book_list",
    "book_status",
    "book_meta",
    "book_note",
    "book_quote",
    "reading_goal",
    "reading_start",
    "reading_pause",
    "reading_stop",
    "focus_start",
    "focus_stop",
    "focus_check",
    "focus_sound",
    "focus_goal",
    "focus_review",
    "scene_apply",
    "actuate_scene_actions",
    "scene_list",
    "LIFE_TOOLS",
]
