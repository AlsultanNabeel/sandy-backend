"""Shared command-disambiguation rules for Sandy's two understanding brains.

The text path (`agents/fc_router.py`, `_FC_SYSTEM_TEMPLATE`) and the voice path
(`api/voice_ws.py`, `_build_system_instruction`) are deliberately separate
brains — voice needs Gemini Live for speed — but the cross-domain
disambiguation rules must not drift between them. This is the single source for
those rules; both prompts import the constant below.

The Arabic wording is the existing canonical phrasing relocated verbatim from
the text prompt (CONVENTIONS C7 — relocate user/model copy, don't reword).
"""

DISAMBIGUATION_RULES_AR = """\
⚠️ جهاز مفرد مقابل مشهد مقابل جلسة (أخطاء شائعة — انتبه):
  • أمر على **جهاز مفرد** ('ضوّي/نوري الضو'، 'طفّي المروحة'، 'افتح الستارة', 'المكيف ٢٢') → device_control. «ضوّي/نوري»=on، «طفّي»=off. device لازم من الأجهزة المسجّلة بالبرومبت؛ ما في جهاز مطابق → استدعِ device_control برضه (بترجّع القائمة وتسأل)، لا تخترع اسم.
  • 'شغّلي وضع/جو X (دراسة/فيلم/راحة...)' = مشهد كامل متعدّد الأجهزة → scene_apply.
  • 'خلصت/وقّفي/ألغي الجلسة أو التركيز أو البومودورو' → focus_stop فقط.
  ❌ ممنوع scene_apply لأمر جهاز مفرد، وممنوع تطبيق مشهد عكس الطلب (إطفاء لمّا يطلب تشغيل).
- "غيّري الموعد" (object=موعد)         → reminder_update (ليس image_edit)
- "غيّري الصورة" (object=صورة)         → image_edit (ليس reminder_update)"""
