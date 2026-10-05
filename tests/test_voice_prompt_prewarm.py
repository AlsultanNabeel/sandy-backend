"""«الصفّ المشترك غايب» — كاش بارد بالتصميم، مش بالصدفة.

    [voice_ws] instruction rebuilt (version 165, shared row absent)
    [voice_ws] seed context: 4900ms
    [voice_ws] session open: seed=5664ms ... cached=no

التعليمات مكيّشة ومفتاحها نسخة المستأجر، والإبطال صح — بس آخر إشي بتعمله أي
مكالمة هو إنها بتحفظ اللي انحكى وبتستخرج منه حقائق، والحفظ بيحرّك النسخة. يعني
كل مكالمة بتبرّد كاش اللي بعدها، وما بيصير في «إصابة» ولا مرّة.

فالبناء انتقل لوقت الكتابة، بالخلفية.
"""
from __future__ import annotations

import mongomock
import pytest


@pytest.fixture()
def db():
    import app.db as appdb

    database = mongomock.MongoClient()["t"]
    appdb.configure(database)
    try:
        yield database
    finally:
        appdb.reset()


@pytest.fixture()
def inline(monkeypatch):
    """شغّل شغل الخلفية بنفس الخيط، وبلا استنّى."""
    import app.utils.prompt_prewarm as pw
    import app.utils.thread_pool as tp

    monkeypatch.setattr(pw, "_DELAY_S", 0.0)
    monkeypatch.setattr(tp, "submit_background",
                        lambda fn, *a, _label=None, **k: fn(*a, **k))
    pw._pending.clear()
    return pw


def test_a_write_builds_the_next_call_s_instruction(db, inline, monkeypatch):
    import app.api.voice_ws.tools as vt
    from app.utils.tenant_version import bump_for

    built: list[str] = []
    monkeypatch.setattr(vt, "_build_cached_instruction", built.append)
    monkeypatch.setattr(vt, "tenant_uses_voice", lambda t: True)

    bump_for("u1", collection="sandy_entries")

    assert built == ["u1"], (
        "الكتابة حرّكت النسخة وما بنت التعليمات — المكالمة الجاية بتدفعها هي")


def test_a_tenant_who_never_called_is_not_warmed(db, inline, monkeypatch):
    """زبون بيضيف مهام وما فتح مكالمة بحياته ما بدّو تعليمات صوت كل كتابة."""
    import app.api.voice_ws.tools as vt
    from app.utils.tenant_version import bump_for

    built: list[str] = []
    monkeypatch.setattr(vt, "_build_cached_instruction", built.append)

    bump_for("silent-user", collection="sandy_entries")
    assert built == []

    # أول مكالمة بتحطّ العلامة، وبعدها بيتسخّن زي غيره.
    vt._shared_put("silent-user", 1, False, "التعليمات")
    bump_for("silent-user", collection="sandy_entries")
    assert built == ["silent-user"]


def test_a_burst_of_writes_builds_once(db, inline, monkeypatch):
    """الدور الواحد بيكتب أكتر من مرّة — مهمّة، تفضيل، ملخّص."""
    import app.api.voice_ws.tools as vt
    from app.utils.tenant_version import bump_for

    built: list[str] = []

    def _slow(tenant):
        # بيتجدوَل بناء تاني وإحنا جوّا الأوّل — لازم يمرق، مش ينلغي.
        built.append(tenant)

    monkeypatch.setattr(vt, "_build_cached_instruction", _slow)
    monkeypatch.setattr(vt, "tenant_uses_voice", lambda t: True)
    inline._pending.add("u2")          # بناء مجدوَل أصلاً

    bump_for("u2", collection="sandy_entries")
    assert built == [], "بناءين ع نفس المستأجر بنفس اللحظة"


def test_the_background_build_reads_the_new_version_not_the_turn_s(db, inline,
                                                                   monkeypatch):
    """المهمّة بتورث سياق الدور، وفيه رقم النسخة وقت ما بلّش الدور.

    بلا نسيان الذاكرة هاي، التسخين بيحفظ تحت الرقم القديم — مفتاح ما حدا رح
    يسأل عنه — والمفتاح الصحيح بيضلّ بارد. نفس الأعراض بالضبط، بس أبعد.
    """
    import app.api.voice_ws.tools as vt
    from app.utils.tenant_version import bump_for, turn_scope, version_for

    seen: list[int] = []
    monkeypatch.setattr(vt, "tenant_uses_voice", lambda t: True)
    monkeypatch.setattr(vt, "_build_cached_instruction",
                        lambda t: seen.append(version_for(t)))

    with turn_scope():
        assert version_for("u3") == 0        # بتتخزّن بذاكرة الدور
        bump_for("u3", collection="sandy_entries")

    assert seen == [1], f"التسخين بنى ع نسخة {seen} والقاعدة عندها واحد"


def test_the_working_live_model_outlives_the_process(db, monkeypatch):
    """أربعة أسماء ماتوا مع بعض مرّة، وكل مكالمة دفعت محاولاتهم.

    التثبيت كان بالذاكرة: عامل جديد = من أوّل القائمة من جديد، وهيروكو بيشغّل
    عاملين وبيعيد تشغيلهم كل يوم.
    """
    import app.api.voice_ws._config as cfg
    import app.utils.thread_pool as tp

    monkeypatch.setattr(tp, "submit_background",
                        lambda fn, *a, _label=None, **k: fn(*a, **k))
    cfg._reset_live_model_cache()
    cfg.remember_live_model("gemini-live-that-works")

    # عامل تاني، عمليّة تانية، نفس القاعدة.
    cfg._reset_live_model_cache()
    assert cfg.live_model_candidates()[0] == "gemini-live-that-works"

    # وأول ما يفشل، بينشال — وإلا العامل الجاي بيرجع يثبّتو.
    cfg.forget_live_model("gemini-live-that-works")
    cfg._reset_live_model_cache()
    assert cfg.live_model_candidates()[0] != "gemini-live-that-works"
    cfg._reset_live_model_cache()


def test_writes_during_a_call_build_once_when_it_ends(db, inline, monkeypatch):
    """كل دور بالمكالمة بيحفظ ذاكرة، وكان كل حفظ بيطلق بناء — بنصّ المكالمة،
    ع نفس السيرفر، لمكالمة لسا ما صارت."""
    import app.api.voice_ws.tools as vt
    from app.utils.tenant_version import bump_for

    built: list[str] = []
    monkeypatch.setattr(vt, "_build_cached_instruction", built.append)
    monkeypatch.setattr(vt, "tenant_uses_voice", lambda t: True)

    inline.hold("u4")
    for _ in range(3):
        bump_for("u4", collection="sandy_entries")
    assert built == [], "بنى بنصّ المكالمة"

    inline.release("u4")
    assert built == ["u4"], "المكالمة خلصت وما انبنى إشي للجاية"

    # مكالمة بلا كتابات: ما في شي يتبنى.
    inline.hold("u4")
    inline.release("u4")
    assert built == ["u4"]


def test_a_corrected_or_forgotten_fact_is_never_served_from_an_older_instruction(db, monkeypatch):
    """«انسي…» or a corrected fact used to stay in the voice instruction for up to six
    hours: any older instruction was good enough while the new one was built."""
    from datetime import timedelta

    import app.api.voice_ws.tools as vt
    from app.blocks import _base, entries
    from app.utils.user_profiles import active_user_profile_context

    # Only the instruction rows this test writes: no build behind the writes.
    monkeypatch.setattr("app.utils.prompt_prewarm.schedule", lambda tenant: None)
    with active_user_profile_context({"chat_id": "u1"}):
        fact = entries.add("fact", "بيشتغل بالبنك", embed=False)
        spent = entries.add("expense", "قهوة", {"amount": 3}, embed=False)

        def _built_before_the_change():
            db["sandy_prompt_cache"].delete_many({})
            vt._shared_put("u1", 1, False, "تعليمات فيها البنك")
            db["sandy_prompt_cache"].update_many(
                {}, {"$set": {"created_at": _base.now() - timedelta(minutes=5)}})

        _built_before_the_change()
        entries.update(spent, data={"amount": 4})
        assert vt._shared_latest("u1", False), "an edit outside the facts dropped the fast path"

        entries.update(fact, text="بيشتغل بالمدرسة")
        assert vt._shared_latest("u1", False) is None, "a corrected fact was served stale"

        _built_before_the_change()
        entries.delete(fact)
        assert vt._shared_latest("u1", False) is None, "a forgotten fact was served stale"

        again = entries.add("fact", "عنده قطة", embed=False)
        _built_before_the_change()
        _base.undo([{"op": "created", "coll": _base.ENTRIES, "id": again, "before": None}])
        assert vt._shared_latest("u1", False) is None, "an undone fact was served stale"
