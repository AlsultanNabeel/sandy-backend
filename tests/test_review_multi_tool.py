"""Two requests in one message: a held confirmation survives, and nothing
running is not reported as success."""
from unittest.mock import MagicMock, patch

from app.agent.graph.state import create_initial_state, merge_state


def _run(calls, dispatch):
    state = merge_state(create_initial_state("x", "u1", "u1"),
                        {"function_calls": calls, "function_call": calls[0]})
    reg = MagicMock()
    reg.get_tool.side_effect = lambda n: MagicMock() if n in ("task_delete", "task_create") else None

    class _D:
        def dispatch(self, name, args, ctx):
            return dispatch(name, ctx)

    with patch("app.agent.tools.registry.get_registry", return_value=reg), \
         patch("app.agent.tools.dispatcher.ToolDispatcher", _D), \
         patch("app.agent.nodes.execute._get_chat_completion_fn"), \
         patch("app.agent.nodes.execute._get_mongo_db", return_value=None):
        from app.agent.nodes.execute import execute_node
        return execute_node(state)


def test_pending_from_a_multi_call_is_kept():
    def dispatch(name, ctx):
        if name == "task_delete":
            ctx.session["pending_action"] = {"type": "task", "action": "delete_one",
                                             "confirmation_status": "pending"}
            return {"handled": True, "reply": "متأكد؟"}
        return {"handled": True, "reply": "ضفتها"}

    out = _run([{"name": "task_delete", "args": {}}, {"name": "task_create", "args": {}}],
               dispatch)
    assert out["pending_state"]["action"] == "delete_one"


def test_nothing_ran_is_not_success():
    out = _run([{"name": "nope_a", "args": {}}, {"name": "nope_b", "args": {}}],
               lambda n, c: {"handled": True, "reply": ""})
    assert out["final_response"] != "تم."
