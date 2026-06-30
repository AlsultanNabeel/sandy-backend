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

    def test_guarded_set_is_the_five_immediate_tools(self):
        self.assertEqual(
            set(_GUARDED_DESTRUCTIVE),
            {"device_control", "scene_apply", "delete_photo",
             "brainstorm_delete", "shopping_remove"},
        )

    def test_self_confirming_tools_are_excluded(self):
        # They run their own confirmation; guarding them would double-ask.
        self.assertNotIn("task_delete", _GUARDED_DESTRUCTIVE)
        self.assertNotIn("reminder_delete", _GUARDED_DESTRUCTIVE)

    def test_fresh_pick_holds_for_confirmation_without_running_handler(self):
        session = {}
        # If the real handler ran, it would touch the shopping store; the guard
        # must short-circuit before that and only set a pending.
        with patch(
            "app.agent.tools.schemas.life_tools.shopping_remove"
        ) as real_handler:
            result = ToolDispatcher().dispatch(
                "shopping_remove", {"item": "حليب"}, _ctx(session)
            )
            real_handler.assert_not_called()

        self.assertTrue(result["handled"])
        self.assertIn("متأكد", result["reply"])
        self.assertIn("حليب", result["reply"])
        pending = session["pending_action"]
        self.assertEqual(pending["type"], "tool_guard")
        self.assertEqual(pending["action"], "execute")
        self.assertEqual(pending["tool"], "shopping_remove")
        self.assertEqual(pending["args"], {"item": "حليب"})

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
