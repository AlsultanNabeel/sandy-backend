"""Shared imports and helpers for the task_handlers package."""


from app.agent.pending import create_pending_action




def _format_task_choices(choices) -> str:
    """'المهمة 1: ...\\nالمهمة 2: ...' — the shared enumerated choice list."""
    return "\n".join(
        f"المهمة {i}: {t.get('text', '')}" for i, t in enumerate(choices, 1)
    )


def _ambiguous_choice_reply(
    result, *, target_action, session, session_file, mongo_db, save_session_fn,
) -> str:
    """Build the shared 'multiple matches → pick one' pending + reply.
    Returns the reply text (identical wording to the previous inline copies)."""
    choices = [
        {"id": t.get("id", ""), "text": t.get("text", "")}
        for t in result.get("matches", [])[:5]
        if t.get("id")
    ]
    session["pending_action"] = create_pending_action({
        "type": "task",
        "action": "clarify_task_choice",
        "target_action": target_action,
        "choices": choices,
        "confirmation_status": "clarification",
    })
    save_session_fn(session, session_file=session_file, mongo_db=mongo_db)
    return (
        "لقيت أكثر من مهمة مطابقة:\n"
        + _format_task_choices(choices)
        + "\nاختار واحدة: الأولى، الثانية، أو رقم المهمة."
    )
