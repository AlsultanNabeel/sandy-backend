"""The sentences `eval_brain.py` puts to the real model, and what each should leave behind.

A case is a fresh, empty account: optional `setup`, then `steps` said in one
conversation. A step checks any of:
  tools / not_tools / no_tools   the tools it must, must not, or none at all
  any_tools                      at least one of these
  item / no_item                 a row (`list` optional; `has` is part of its text; `done`, `data`)
  schedule / no_schedule         a pending reminder (`has`; `repeats`)
  entry                          a log row of `kind` (`has`, `amount`)
  pending                        True: it waits for a yes; False: nothing waits
  reply_has / reply_lacks        words that must / must not be in the reply
  english                        the reply is in English
  args                           {tool: {arg: value}}: one call of that tool carries these
                                 values (a word of text is found inside the call's text)
  task / no_task                 a running task (`check`: its check tool; `every`; `paused`),
                                 or none at all (the setup may hold one: {"task": {...}})
Checks look at what was done, not at the wording, so a good reply in other words passes.
Every Arabic case has an English sister, `<name> · en`, with the same checks and its reply
checked to be English (`EN_CASES`); `eval_brain.py` scores each language on its own.
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
         "args": {"list_add": {"list": "shopping"}},
         "item": {"list": "shopping", "has": "خبز"}}]},
    {"name": "shopping implied", "steps": [
        {"say": "خلص الحليب من البيت", "tools": ["list_add"], "item": {"list": "shopping", "has": "حليب"}}]},
    {"name": "shopping bought", "setup": [{"item": {"list": "shopping", "text": "بندورة"}}], "steps": [
        {"say": "جبت البندورة", "tools": ["list_update"],
         "item": {"list": "shopping", "has": "بندورة", "done": True}}]},
    {"name": "shopping more of", "setup": [{"item": {"list": "shopping", "text": "حليب"}}], "steps": [
        {"say": "كمان حليب", "not_tools": ["undo"]}]},
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
    {"name": "delete at once", "setup": [{"item": {"list": "tasks", "text": "أروح عالجيم"}}], "steps": [
        {"say": "احذفي مهمة الجيم", "tools": ["list_delete"], "pending": False,
         "no_item": {"list": "tasks", "has": "الجيم"}}]},
    {"name": "empty a list asks first", "setup": [{"item": {"list": "shopping", "text": "حليب"}},
                                                 {"item": {"list": "shopping", "text": "خبز"}}], "steps": [
        {"say": "فضّيلي قائمة التسوق", "pending": True},
        {"say": "لا خليها", "pending": False, "item": {"list": "shopping", "has": "حليب", "done": False}}]},

    # ── What went wrong before: deletes, «no, put it back», missing rows, edits that change nothing ──
    {"name": "delete one item", "setup": [{"item": {"list": "shopping", "text": "حليب"}},
                                         {"item": {"list": "shopping", "text": "خبز"}}], "steps": [
        {"say": "شيلي الخبز من الأغراض", "tools": ["list_delete"], "pending": False,
         "no_item": {"list": "shopping", "has": "خبز"}, "item": {"list": "shopping", "has": "حليب"}}]},
    {"name": "delete is never an edit", "setup": [{"item": {"list": "tasks", "text": "أتصل بالبنك"}}], "steps": [
        {"say": "امسحي مهمة البنك", "tools": ["list_delete"], "not_tools": ["list_update"],
         "no_item": {"list": "tasks", "has": "البنك"}}]},
    {"name": "bulk delete asks then goes", "setup": [
        {"item": {"list": "shopping", "text": t}} for t in ("حليب", "خبز", "بيض", "جبنة", "زيت", "سكر")], "steps": [
        {"say": "امسحي كل قائمة التسوق", "pending": True, "item": {"list": "shopping", "has": "زيت"}},
        {"say": "اه امسحيها", "pending": False, "no_item": {"list": "shopping", "has": "زيت"}}]},
    {"name": "no put it back", "setup": [{"item": {"list": "tasks", "text": "أروح عالجيم"}}], "steps": [
        {"say": "احذفي مهمة الجيم", "tools": ["list_delete"], "no_item": {"list": "tasks", "has": "الجيم"}},
        {"say": "لا رجّعيه", "tools": ["undo"], "item": {"list": "tasks", "has": "الجيم"}}]},
    {"name": "delete what is not there", "setup": [{"item": {"list": "shopping", "text": "حليب"}}], "steps": [
        {"say": "احذفي البطيخ من الأغراض", "item": {"list": "shopping", "has": "حليب"},
         "reply_lacks": ["حذفت", "شلت"]}]},
    {"name": "an edit that changes nothing", "setup": [{"item": {"list": "tasks", "text": "أدفع الإيجار"}}], "steps": [
        {"say": "غيّري مهمة الإيجار لأدفع الإيجار", "item": {"list": "tasks", "has": "أدفع الإيجار"},
         "reply_lacks": ["عدّلت", "غيّرت"]}]},

    # ── Reminders ──
    {"name": "reminder relative", "steps": [
        {"say": "ذكريني بعد ساعة أتصل بأمي", "tools": ["schedule"], "schedule": {"has": "أمي"},
         "args": {"schedule": {"kind": "reminder"}}}]},
    {"name": "reminder clock", "steps": [
        {"say": "ذكريني بكرا الساعة تسعة الصبح بموعد الدكتور", "tools": ["schedule"],
         "schedule": {"has": "الدكتور"}}]},
    {"name": "reminder repeats", "steps": [
        {"say": "ذكريني كل يوم الساعة عشرة بالليل آخد الدوا", "tools": ["schedule"],
         "args": {"schedule": {"kind": "reminder"}},
         "schedule": {"has": "الدوا", "repeats": True}}]},
    {"name": "reminder move", "setup": [{"reminder": {"text": "اجتماع الفريق"}}], "steps": [
        {"say": "أجلي تذكير الاجتماع ساعة", "tools": ["schedule_update"], "schedule": {"has": "اجتماع"}}]},
    {"name": "reminder cancel", "setup": [{"reminder": {"text": "أشتري هدية"}}], "steps": [
        {"say": "الغي تذكير الهدية", "tools": ["schedule_cancel"], "no_schedule": "هدية"}]},
    {"name": "reminder before another", "setup": [{"reminder": {"text": "اجتماع المدير", "in_hours": 5}}], "steps": [
        {"say": "ذكريني قبل اجتماع المدير بربع ساعة", "tools": ["schedule"]}]},

    # ── The log ──
    {"name": "expense", "steps": [
        {"say": "صرفت خمسين شيكل عالغدا", "tools": ["remember"], "entry": {"kind": "expense", "amount": 50}}]},
    {"name": "delete the last expense", "steps": [
        {"say": "صرفت عشرين على قهوة", "tools": ["remember"]},
        {"say": "احذفي آخر مصروف", "tools": ["log_delete"], "no_entry": {"kind": "expense"}}]},
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
        {"say": "لا غلط ارجعي عنه", "tools": ["undo"], "no_item": {"list": "shopping", "has": "جبنة"}}]},

    # ── Devices and the world ──
    {"name": "device on", "steps": [
        {"say": "ممكن تشغلي ضو الصالون", "tools": ["device_control"],
         "args": {"device_control": {"action": "on"}}}]},
    {"name": "device room", "steps": [
        {"say": "طفي كل إشي بالمطبخ", "tools": ["device_control"],
         "args": {"device_control": {"action": "off"}}}]},
    {"name": "device later", "steps": [
        {"say": "طفي المكيف بعد ساعة", "tools": ["schedule"], "not_tools": ["device_control"]}]},
    {"name": "device question", "steps": [
        {"say": "المكيف شغال؟", "tools": ["device_state"], "not_tools": ["device_control"]}]},
    {"name": "scene", "steps": [
        {"say": "بدي أنام، جهزي الغرفة", "any_tools": ["scene_apply", "device_control"],
         "not_tools": ["room_restore"]}]},
    {"name": "apply a scene is not a restore", "steps": [
        {"say": "طبّقي مشهد الفيلم", "tools": ["scene_apply"], "not_tools": ["room_restore"]}]},
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
    {"name": "english", "lang": "en", "steps": [
        {"say": "remind me to call John tomorrow at 5pm", "tools": ["schedule"], "english": True}]},
    {"name": "two at once", "steps": [
        {"say": "ضيفي بيض للأغراض وذكريني بعد ساعتين أطلع الزبالة", "tools": ["list_add", "schedule"],
         "item": {"list": "shopping", "has": "بيض"}, "schedule": {"has": "الزبالة"}}]},
    {"name": "remembers the thread", "steps": [
        {"say": "بدي أعمل عزومة يوم الجمعة لصحابي", "not_tools": ["undo"]},
        {"say": "ضيفي لحمة وفحم إلها", "tools": ["list_add"], "item": {"list": "shopping", "has": "فحم"}}]},
]


def _en(name, steps, setup=None):
    case = {"name": f"{name} · en", "lang": "en", "steps": [{**st, "english": True} for st in steps]}
    if setup:
        case["setup"] = setup
    return case


def _item(list_name, text):
    return {"item": {"list": list_name, "text": text}}


# The plan's four examples (docs/AGENT_PLAN.md, phase one): the same tools for each, the field
# of work only in his words. A task is shown and waits for a yes; then it runs.
CASES += [
    {"name": "task: student deadlines", "setup": [_item("tasks", "تسليم مشروع التخرج")], "steps": [
        {"say": "تابعي مواعيد تسليم مشاريعي، وذكّريني قبل يومين", "tools": ["task_create"],
         "pending": True, "no_task": True},
        {"say": "اه", "pending": False, "task": {}}]},
    {"name": "task: freelancer projects", "steps": [
        {"say": "كل ساعة شوفي مشاريع جديدة على مستقل، وابعتيلي الجديد مع مسودة عرض",
         "tools": ["task_create"], "pending": True, "no_task": True},
        {"say": "اه", "pending": False, "task": {"check": "web_search", "every": 60}}]},
    {"name": "task: shop stock", "setup": [_item("project:المخزون", t) for t in (
        "سكر: ١٢ كيلو", "رز: ٣ أكياس", "زيت: ٢ قناني")], "steps": [
        {"say": "تابعي المخزون، ونبّهيني إذا شي قرب يخلص", "tools": ["task_create"],
         "pending": True, "no_task": True},
        {"say": "اه", "pending": False, "task": {}}]},
    {"name": "task: home budget", "steps": [
        {"say": "تابعي مصاريف الشهر، وقلّيلي إذا تعدّيت الميزانية", "tools": ["task_create"],
         "pending": True, "no_task": True},
        {"say": "اه", "pending": False, "task": {}}]},
    {"name": "task: run by talk", "setup": [{"task": {"title": "مشاريع مستقل", "every": 60}}], "steps": [
        {"say": "شو المهام الشغّالة؟", "tools": ["task_list"]},
        {"say": "وقّفيها", "tools": ["task_update"], "task": {"paused": True}},
        {"say": "رجّعيها وخلّيها كل ساعتين", "tools": ["task_update"], "task": {"paused": False, "every": 120}}]},
    {"name": "task: refuses to pay", "steps": [
        {"say": "كل أول الشهر ادفعي فاتورة الكهربا من حسابي", "no_task": True, "pending": False}]},
]


def _task(title, every=60):
    return {"task": {"title": title, "every": every}}


EN_CASES = [
    _en("shopping add", [{"say": "add milk and bread to the shopping list", "tools": ["list_add"],
                          "args": {"list_add": {"list": "shopping"}},
                          "item": {"list": "shopping", "has": "bread"}}]),
    _en("shopping implied", [{"say": "we're out of milk at home", "tools": ["list_add"],
                              "item": {"list": "shopping", "has": "milk"}}]),
    _en("shopping bought", [{"say": "I bought the tomatoes", "tools": ["list_update"],
                             "item": {"list": "shopping", "has": "tomato", "done": True}}],
        [_item("shopping", "tomatoes")]),
    _en("shopping more of", [{"say": "more milk", "not_tools": ["undo"]}], [_item("shopping", "milk")]),
    _en("task add", [{"say": "I need to finish the work report", "tools": ["list_add"],
                      "item": {"list": "tasks", "has": "report"}}]),
    _en("task done", [{"say": "I paid the electricity", "tools": ["list_update"],
                       "item": {"list": "tasks", "has": "electricity", "done": True}}],
        [_item("tasks", "Pay the electricity bill")]),
    _en("task repeats", [{"say": "every day I have to water the plants", "tools": ["list_add"],
                          "item": {"has": "plants"}}]),
    _en("habit days", [{"say": "I want a workout habit on Sundays, Tuesdays and Thursdays at 6pm",
                        "tools": ["list_add"], "item": {"list": "habits", "has": "workout"}}]),
    _en("delete at once", [{"say": "delete the gym task", "tools": ["list_delete"], "pending": False,
                            "no_item": {"list": "tasks", "has": "gym"}}], [_item("tasks", "Go to the gym")]),
    _en("empty a list asks first", [{"say": "empty my shopping list", "pending": True},
                                    {"say": "no, keep it", "pending": False,
                                     "item": {"list": "shopping", "has": "milk", "done": False}}],
        [_item("shopping", "milk"), _item("shopping", "bread")]),
    _en("delete one item", [{"say": "remove the bread from the shopping list", "tools": ["list_delete"],
                             "pending": False, "no_item": {"list": "shopping", "has": "bread"},
                             "item": {"list": "shopping", "has": "milk"}}],
        [_item("shopping", "milk"), _item("shopping", "bread")]),
    _en("delete is never an edit", [{"say": "remove the bank task", "tools": ["list_delete"],
                                     "not_tools": ["list_update"], "no_item": {"list": "tasks", "has": "bank"}}],
        [_item("tasks", "Call the bank")]),
    _en("bulk delete asks then goes", [{"say": "clear my whole shopping list", "pending": True,
                                        "item": {"list": "shopping", "has": "oil"}},
                                       {"say": "yes, clear it", "pending": False,
                                        "no_item": {"list": "shopping", "has": "oil"}}],
        [_item("shopping", t) for t in ("milk", "bread", "eggs", "cheese", "oil", "sugar")]),
    _en("no put it back", [{"say": "delete the gym task", "tools": ["list_delete"],
                            "no_item": {"list": "tasks", "has": "gym"}},
                           {"say": "no, bring it back", "tools": ["undo"], "item": {"list": "tasks", "has": "gym"}}],
        [_item("tasks", "Go to the gym")]),
    _en("delete what is not there", [{"say": "delete the watermelon from the shopping list",
                                      "item": {"list": "shopping", "has": "milk"},
                                      "reply_lacks": ["deleted", "removed"]}], [_item("shopping", "milk")]),
    _en("an edit that changes nothing", [{"say": "change the rent task to Pay the rent",
                                          "item": {"list": "tasks", "has": "Pay the rent"},
                                          "reply_lacks": ["updated", "changed"]}], [_item("tasks", "Pay the rent")]),
    _en("reminder relative", [{"say": "remind me in an hour to call my mom", "tools": ["schedule"],
                               "schedule": {"has": "mom"}, "args": {"schedule": {"kind": "reminder"}}}]),
    _en("reminder clock", [{"say": "remind me tomorrow at 9am about the doctor's appointment",
                            "tools": ["schedule"], "schedule": {"has": "doctor"}}]),
    _en("reminder repeats", [{"say": "remind me every day at 10pm to take my medicine", "tools": ["schedule"],
                              "args": {"schedule": {"kind": "reminder"}},
                              "schedule": {"has": "medicine", "repeats": True}}]),
    _en("reminder move", [{"say": "push the meeting reminder back an hour", "tools": ["schedule_update"],
                           "schedule": {"has": "meeting"}}], [{"reminder": {"text": "Team meeting"}}]),
    _en("reminder cancel", [{"say": "cancel the gift reminder", "tools": ["schedule_cancel"],
                             "no_schedule": "gift"}], [{"reminder": {"text": "Buy a gift"}}]),
    _en("reminder before another", [{"say": "remind me fifteen minutes before the manager meeting",
                                     "tools": ["schedule"]}],
        [{"reminder": {"text": "Meeting with the manager", "in_hours": 5}}]),
    _en("expense", [{"say": "I spent 50 shekels on lunch", "tools": ["remember"],
                     "entry": {"kind": "expense", "amount": 50}}]),
    _en("delete the last expense", [{"say": "I spent 20 on coffee", "tools": ["remember"]},
                                    {"say": "delete the last expense", "tools": ["log_delete"],
                                     "no_entry": {"kind": "expense"}}]),
    _en("expense fix", [{"say": "I spent 50 on gas", "tools": ["remember"]},
                        {"say": "no, I meant 60 not 50", "tools": ["log_update"],
                         "entry": {"kind": "expense", "amount": 60}}]),
    _en("fact", [{"say": "by the way, I'm allergic to peanuts", "tools": ["remember"],
                  "entry": {"kind": "fact", "has": "peanut"}}]),
    _en("spending question", [{"say": "how much did I spend today?", "reply_has": ["65"]}],
        [{"entry": {"kind": "expense", "text": "lunch", "data": {"amount": 40, "category": "food"}}},
         {"entry": {"kind": "expense", "text": "taxi", "data": {"amount": 25, "category": "transport"}}}]),
    _en("undo", [{"say": "add cheese to the shopping list", "tools": ["list_add"]},
                 {"say": "no, that was a mistake, undo it", "tools": ["undo"],
                  "no_item": {"list": "shopping", "has": "cheese"}}]),
    _en("device on", [{"say": "can you turn on the living room light", "tools": ["device_control"],
                       "args": {"device_control": {"action": "on"}}}]),
    _en("device room", [{"say": "turn off everything in the kitchen", "tools": ["device_control"],
                         "args": {"device_control": {"action": "off"}}}]),
    _en("device later", [{"say": "turn off the AC in an hour", "tools": ["schedule"],
                          "not_tools": ["device_control"]}]),
    _en("device question", [{"say": "is the AC on?", "tools": ["device_state"],
                             "not_tools": ["device_control"]}]),
    _en("scene", [{"say": "I'm going to sleep, set up the room", "any_tools": ["scene_apply", "device_control"],
                   "not_tools": ["room_restore"]}]),
    _en("apply a scene is not a restore", [{"say": "apply the movie scene", "tools": ["scene_apply"],
                                            "not_tools": ["room_restore"]}]),
    _en("weather", [{"say": "what's the weather like tomorrow?", "tools": ["weather"]}]),
    _en("search", [{"say": "what's the latest Real Madrid news?", "tools": ["web_search"]}]),
    _en("image", [{"say": "draw me a cat wearing glasses", "tools": ["image"]}]),
    _en("plain chat", [{"say": "how are you, Sandy?", "no_tools": True}]),
    _en("venting", [{"say": "today was a really hard day at work", "not_tools": ["list_add", "schedule"]}]),
    _en("two at once", [{"say": "add eggs to the shopping list and remind me in two hours to take out the trash",
                         "tools": ["list_add", "schedule"], "item": {"list": "shopping", "has": "eggs"},
                         "schedule": {"has": "trash"}}]),
    _en("remembers the thread", [{"say": "I'm having friends over for dinner on Friday", "not_tools": ["undo"]},
                                 {"say": "add meat and charcoal for it", "tools": ["list_add"],
                                  "item": {"list": "shopping", "has": "charcoal"}}]),
]
EN_CASES += [
    _en("task: student deadlines", [
        {"say": "Track my project deadlines and remind me two days before", "tools": ["task_create"],
         "pending": True, "no_task": True},
        {"say": "yes", "pending": False, "task": {}}], [_item("tasks", "Graduation project due")]),
    _en("task: freelancer projects", [
        {"say": "Every hour, check Mostaql for new projects and send me the new ones with a draft proposal",
         "tools": ["task_create"], "pending": True, "no_task": True},
        {"say": "yes", "pending": False, "task": {"check": "web_search", "every": 60}}]),
    _en("task: shop stock", [
        {"say": "Track my stock and warn me when something is running low", "tools": ["task_create"],
         "pending": True, "no_task": True},
        {"say": "yes", "pending": False, "task": {}}],
        [_item("project:Inventory", t) for t in ("Sugar: 12 kg", "Rice: 3 bags", "Oil: 2 bottles")]),
    _en("task: home budget", [
        {"say": "Track this month's spending and tell me if I go over budget", "tools": ["task_create"],
         "pending": True, "no_task": True},
        {"say": "yes", "pending": False, "task": {}}]),
    _en("task: run by talk", [
        {"say": "what tasks are running?", "tools": ["task_list"]},
        {"say": "pause it", "tools": ["task_update"], "task": {"paused": True}},
        {"say": "start it again and make it every two hours", "tools": ["task_update"],
         "task": {"paused": False, "every": 120}}], [_task("Mostaql projects")]),
    _en("task: refuses to pay", [
        {"say": "on the first of every month, pay my electricity bill from my account",
         "no_task": True, "pending": False}]),
]
CASES += EN_CASES
