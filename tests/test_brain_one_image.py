"""One image a turn: each one is a paid call, and the reply can carry only one."""
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.brain import loop
from app.utils.user_profiles import active_user_profile_context


def _drawn(monkeypatch):
    from app.features import vision

    made = []
    monkeypatch.setattr(vision, "generate_image_with_azure",
                        lambda prompt: made.append(prompt) or b"\x89PNG" + prompt.encode())
    return made


def _turn(model):
    with active_user_profile_context(A):
        return loop.run_turn("ارسمي قطة وكلب", user_id="userA", chat_id="userA",
                             source="web", complete=model)


def test_two_images_asked_in_one_step_draw_one(brain_db, monkeypatch):  # noqa: F811
    made = _drawn(monkeypatch)
    _turn(ScriptedModel(tools_reply(call("image", "c1", prompt="قطة"),
                                    call("image", "c2", prompt="كلب")),
                        text_reply("رسمت وحدة")))
    assert made == ["قطة"]


def test_a_second_image_in_a_later_step_is_not_drawn(brain_db, monkeypatch):  # noqa: F811
    made = _drawn(monkeypatch)
    # With a second tool beside it the model is asked again, and asks for another.
    result = _turn(ScriptedModel(tools_reply(call("image", "c1", prompt="قطة"),
                                             call("recall", "c3", query="قطط")),
                                 tools_reply(call("image", "c2", prompt="كلب")),
                                 text_reply("رسمت وحدة")))
    assert made == ["قطة"]
    assert result["execution_result"]["image_bytes"] == b"\x89PNG" + "قطة".encode()
