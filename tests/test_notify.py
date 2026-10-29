"""What a task found is delivered once (`app/notify`): kept for the app and «صباح الخير» under
its user, then handed to each channel (email comes in session B; Apple pushes later)."""
from __future__ import annotations

from brain_fakes import A, B, brain_db  # noqa: F401

from app import notify
from app.utils.user_profiles import active_user_profile_context


def test_a_result_is_kept_for_its_user_and_handed_to_each_channel(brain_db, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(notify, "CHANNELS", [lambda r: seen.append(("one", r["title"])),
                                            lambda r: seen.append(("two", r["body"]))])
    with active_user_profile_context(A):
        rid = notify.deliver("t1", "New projects", "Two new ones", "en")
        assert [r["id"] for r in notify.unseen()] == [rid]
    with active_user_profile_context(B):
        assert notify.unseen() == []
    assert seen == [("one", "New projects"), ("two", "Two new ones")]


def test_a_channel_that_breaks_never_loses_the_result(brain_db, monkeypatch):  # noqa: F811
    def broken(r):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(notify, "CHANNELS", [broken])
    with active_user_profile_context(A):
        notify.deliver("t1", "عنوان", "نص", "ar")
        assert len(notify.unseen()) == 1


def test_seen_results_are_not_shown_again(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(notify, "CHANNELS", [])
    with active_user_profile_context(A):
        rid = notify.deliver("t1", "x", "y", "en")
        notify.mark_seen([rid])
        assert notify.unseen() == []
