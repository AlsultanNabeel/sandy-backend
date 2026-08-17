"""Deterministic destructive-action guard (dispatcher chokepoint).

Locks the safety property that previously had zero coverage: the five
immediate destructive tools never run without an explicit confirmation, while
task_delete / reminder_delete keep their own confirmation (excluded here so they
are not double-confirmed).
"""

import unittest
from unittest.mock import patch

from app.agent.tools.setup import register_all_tools
from app.agent.tools.dispatcher import (
    DispatchContext,
    ToolDispatcher,
    _GUARDED_DESTRUCTIVE,
    _GUARD_CONFIRMED_FLAG,
)


def _ctx(session):
    return DispatchContext(
        user_message="", normalized_message="", session=session,
        state={"chat_id": "c1"}, mongo_db=None,
    )


class TestDestructiveGuard(unittest.TestCase):

    def setUp(self):
        register_all_tools()

    def test_the_guard_covers_real_loss_and_nothing_else(self):
        """Only things you cannot get back.

        This set used to include device_control, scene_apply and
        shopping_remove. None of them destroys anything: a lamp is un-turned-on
        by saying the opposite, and a shopping line is re-added in one sentence.
        Guarding them cost an extra round trip before every simple command —
        "turn on the flash" answered with "are you sure?" — which is the
        difference between an assistant and an obstacle.

        What is left genuinely loses data.
        """
        self.assertEqual(
            set(_GUARDED_DESTRUCTIVE),
            {"delete_photo", "brainstorm_delete"},
        )

    def test_switching_something_on_is_not_guarded(self):
        for tool in ("device_control", "scene_apply", "shopping_remove"):
            self.assertNotIn(tool, _GUARDED_DESTRUCTIVE, tool)

    def test_self_confirming_tools_are_excluded(self):
        # They run their own confirmation; guarding them would double-ask.
        self.assertNotIn("task_delete", _GUARDED_DESTRUCTIVE)
        self.assertNotIn("reminder_delete", _GUARDED_DESTRUCTIVE)

    def test_fresh_pick_holds_for_confirmation_without_running_handler(self):
        session = {}
        # If the real handler ran, the photo would be gone; the guard must
        # short-circuit before that and only set a pending.
        #
        # This used to test shopping_remove, which is no longer guarded — taking
        # a line off a shopping list is not data loss. A photo is.
        with patch(
            "app.agent.tools.schemas.photo_tools.delete_photo"
        ) as real_handler:
            result = ToolDispatcher().dispatch(
                "delete_photo", {"name": "صورة البيت"}, _ctx(session)
            )
            real_handler.assert_not_called()

        self.assertTrue(result["handled"])
        self.assertIn("متأكد", result["reply"])
        pending = session["pending_action"]
        self.assertEqual(pending["type"], "tool_guard")
        self.assertEqual(pending["action"], "execute")
        self.assertEqual(pending["tool"], "delete_photo")
        self.assertEqual(pending["args"], {"name": "صورة البيت"})

    def test_confirm_flag_lets_the_tool_run(self):
        # With the guard flag set (re-dispatch after the user confirmed), the
        # dispatcher must invoke the real handler instead of asking again.
        session = {_GUARD_CONFIRMED_FLAG: True}
        with patch.object(
            ToolDispatcher, "_guard_destructive"
        ) as guard, patch(
            "app.agent.tools.registry.ToolRegistry.get_tool"
        ) as get_tool:
            handler = get_tool.return_value
            handler.handler.return_value = {"handled": True, "reply": "تم"}
            result = ToolDispatcher().dispatch(
                "device_control", {"device": "lamp"}, _ctx(session)
            )
            guard.assert_not_called()
        self.assertEqual(result["reply"], "تم")

    def test_confirm_path_re_dispatches_with_flag(self):
        from app.agent.executor.pending.dispatch import _exec_guarded_tool
        pending = {
            "type": "tool_guard", "action": "execute",
            "tool": "device_control", "args": {"device": "lamp"},
            "chat_id": "c1",
        }
        with patch.object(ToolDispatcher, "dispatch") as dispatch:
            dispatch.return_value = {"handled": True, "reply": "تم"}
            _exec_guarded_tool(pending, None)
            name, args, ctx = dispatch.call_args[0]
        self.assertEqual(name, "device_control")
        self.assertEqual(args, {"device": "lamp"})
        self.assertTrue(ctx.session.get(_GUARD_CONFIRMED_FLAG))


if __name__ == "__main__":
    unittest.main()
