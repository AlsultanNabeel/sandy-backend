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

    bump_for("u1", collection="sandy_memories")

    assert built == ["u1"], (
        "الكتابة حرّكت النسخة وما بنت التعليمات — المكالمة الجاية بتدفعها هي")


def test_a_tenant_who_never_called_is_not_warmed(db, inline, monkeypatch):
    """زبون بيضيف مهام وما فتح مكالمة بحياته ما بدّو تعليمات صوت كل كتابة."""
    import app.api.voice_ws.tools as vt
    from app.utils.tenant_version import bump_for

    built: list[str] = []
    monkeypatch.setattr(vt, "_build_cached_instruction", built.append)

    bump_for("silent-user", collection="sandy_tasks")
    assert built == []

    # أول مكالمة بتحطّ العلامة، وبعدها بيتسخّن زي غيره.
    vt._shared_put("silent-user", 1, "التعليمات")
    bump_for("silent-user", collection="sandy_tasks")
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

    bump_for("u2", collection="sandy_memories")
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
        bump_for("u3", collection="sandy_memories")

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
