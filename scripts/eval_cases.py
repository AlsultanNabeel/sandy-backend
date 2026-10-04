"""The sentences `eval_brain.py` puts to the real model, and what each should leave behind.

A case is a fresh, empty account: optional `setup`, then `steps` said in one
conversation. A step checks any of:
  tools / not_tools / no_tools   the tools it must, must not, or none at all
  any_tools                      at least one of these
  item / no_item                 a row (`list` optional; `has` is part of its text; `done`, `data`)
  schedule / no_schedule         a pending reminder (`has`; `repeats`)
  entry                          a log row of `kind` (`has`, `amount`)
  pending                        True: it waits for a yes; False: nothing waits
  reply_has / english            words in the reply; the reply is in English
Checks look at what was done, not at the wording, so a good reply in other words passes.
Add the sentence that went wrong in real use, not an invented one.
"""

DEVICES = [
    {"name": "living_light", "label": "ضو الصالون", "room": "الصالون"},
    {"name": "bedroom_ac", "label": "مكيف غرفة النوم", "room": "غرفة النوم"},
    {"name": "kitchen_light", "label": "ضو المطبخ", "room": "المطبخ"},
]

CASES = [
    # ── Lists ──
    {"name": "shopping add", "steps": [
        {"say": "ضيفي حليب وخبز لقائمة الأغراض", "tools": ["list_add"],
         "item": {"list": "shopping", "has": "خبز"}}]},
    {"name": "shopping implied", "steps": [
        {"say": "خلص الحليب من البيت", "tools": ["list_add"], "item": {"list": "shopping", "has": "حليب"}}]},
    {"name": "shopping bought", "setup": [{"item": {"list": "shopping", "text": "بندورة"}}], "steps": [
        {"say": "جبت البندورة", "tools": ["list_update"],
         "item": {"list": "shopping", "has": "بندورة", "done": True}}]},
    {"name": "shopping more of", "setup": [{"item": {"list": "shopping", "text": "حليب"}}], "steps": [
        {"say": "كمان حليب", "not_tools": ["undo_last"]}]},
    {"name": "task add", "steps": [
        {"say": "لازم أخلص التقرير تبع الشغل", "tools": ["list_add"], "item": {"list": "tasks", "has": "التقرير"}}]},
    {"name": "task done", "setup": [{"item": {"list": "tasks", "text": "أدفع فاتورة الكهربا"}}], "steps": [
        {"say": "دفعت الكهربا", "tools": ["list_update"],
         "item": {"list": "tasks", "has": "الكهربا", "done": True}}]},
    {"name": "task repeats", "steps": [
        {"say": "كل يوم لازم أسقي الزرع", "tools": ["list_add"],
         "item": {"has": "الزرع"}}]},
    {"name": "habit days", "steps": [
        {"say": "بدي عادة رياضة أيام الأحد والتلاتا والخميس الساعة ستة المسا", "tools": ["list_add"],
         "item": {"list": "habits", "has": "رياضة"}}]},
    {"name": "delete asks first", "setup": [{"item": {"list": "tasks", "text": "أروح عالجيم"}}], "steps": [
        {"say": "احذفي مهمة الجيم", "pending": True},
        {"say": "اه", "pending": False, "no_item": {"list": "tasks", "has": "الجيم"}}]},
    {"name": "delete then no", "setup": [{"item": {"list": "tasks", "text": "أروح عالجيم"}}], "steps": [
        {"say": "احذفي مهمة الجيم", "pending": True},
        {"say": "لا خليها", "pending": False, "item": {"list": "tasks", "has": "الجيم", "done": False}}]},

    # ── Reminders ──
    {"name": "reminder relative", "steps": [
        {"say": "ذكريني بعد ساعة أتصل بأمي", "tools": ["schedule"], "schedule": {"has": "أمي"}}]},
    {"name": "reminder clock", "steps": [
        {"say": "ذكريني بكرا الساعة تسعة الصبح بموعد الدكتور", "tools": ["schedule"],
         "schedule": {"has": "الدكتور"}}]},
    {"name": "reminder repeats", "steps": [
        {"say": "ذكريني كل يوم الساعة عشرة بالليل آخد الدوا", "tools": ["schedule"],
         "schedule": {"has": "الدوا", "repeats": True}}]},
    {"name": "reminder move", "setup": [{"reminder": {"text": "اجتماع الفريق"}}], "steps": [
        {"say": "أجلي تذكير الاجتماع ساعة", "tools": ["schedule_update"], "schedule": {"has": "اجتماع"}}]},
    {"name": "reminder cancel", "setup": [{"reminder": {"text": "أشتري هدية"}}], "steps": [
        {"say": "الغي تذكير الهدية", "pending": True},
        {"say": "اه الغيه", "no_schedule": "هدية"}]},
    {"name": "reminder before another", "setup": [{"reminder": {"text": "اجتماع المدير", "in_hours": 5}}], "steps": [
        {"say": "ذكريني قبل اجتماع المدير بربع ساعة", "tools": ["schedule"]}]},

    # ── The log ──
    {"name": "expense", "steps": [
        {"say": "صرفت خمسين شيكل عالغدا", "tools": ["remember"], "entry": {"kind": "expense", "amount": 50}}]},
    {"name": "expense fix", "steps": [
        {"say": "صرفت خمسين على البنزين", "tools": ["remember"]},
        {"say": "لا قصدي ستين مش خمسين", "tools": ["log_update"], "entry": {"kind": "expense", "amount": 60}}]},
    {"name": "fact", "steps": [
        {"say": "على فكرة أنا عندي حساسية من الفول السوداني", "tools": ["remember"],
         "entry": {"kind": "fact", "has": "الفول"}}]},
    {"name": "spending question", "setup": [
        {"entry": {"kind": "expense", "text": "غدا", "data": {"amount": 40, "category": "food"}}},
        {"entry": {"kind": "expense", "text": "تاكسي", "data": {"amount": 25, "category": "transport"}}}], "steps": [
        {"say": "قديش صرفت اليوم؟", "reply_has": ["65", "٦٥", "خمسة وستين", "خمس وستين"]}]},
    {"name": "undo", "steps": [
        {"say": "ضيفي جبنة للأغراض", "tools": ["list_add"]},
        {"say": "لا غلط ارجعي عنه", "tools": ["undo_last"], "no_item": {"list": "shopping", "has": "جبنة"}}]},

    # ── Devices and the world ──
    {"name": "device on", "steps": [
        {"say": "ممكن تشغلي ضو الصالون", "tools": ["device_control"]}]},
    {"name": "device room", "steps": [
        {"say": "طفي كل إشي بالمطبخ", "tools": ["device_control"]}]},
    {"name": "device later", "steps": [
        {"say": "طفي المكيف بعد ساعة", "tools": ["schedule"], "not_tools": ["device_control"]}]},
    {"name": "device question", "steps": [
        {"say": "المكيف شغال؟", "tools": ["device_state"], "not_tools": ["device_control"]}]},
    {"name": "scene", "steps": [
        {"say": "بدي أنام، جهزي الغرفة", "any_tools": ["scene_apply", "device_control"]}]},
    {"name": "weather", "steps": [
        {"say": "كيف الجو بكرا؟", "tools": ["weather"]}]},
    {"name": "search", "steps": [
        {"say": "شو آخر أخبار ريال مدريد؟", "tools": ["web_search"]}]},
    {"name": "image", "steps": [
        {"say": "ارسميلي قطة لابسة نظارة", "tools": ["image"]}]},

    # ── Talking ──
    {"name": "plain chat", "steps": [
        {"say": "كيفك ساندي؟", "no_tools": True}]},
    {"name": "venting", "steps": [
        {"say": "اليوم كان يوم صعب كتير بالشغل", "not_tools": ["list_add", "schedule"]}]},
    {"name": "english", "steps": [
        {"say": "remind me to call John tomorrow at 5pm", "tools": ["schedule"], "english": True}]},
    {"name": "two at once", "steps": [
        {"say": "ضيفي بيض للأغراض وذكريني بعد ساعتين أطلع الزبالة", "tools": ["list_add", "schedule"],
         "item": {"list": "shopping", "has": "بيض"}, "schedule": {"has": "الزبالة"}}]},
    {"name": "remembers the thread", "steps": [
        {"say": "بدي أعمل عزومة يوم الجمعة لصحابي", "not_tools": ["undo_last"]},
        {"say": "ضيفي لحمة وفحم إلها", "tools": ["list_add"], "item": {"list": "shopping", "has": "فحم"}}]},
]
