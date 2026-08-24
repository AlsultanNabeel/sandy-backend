"""focus tools."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from app.agent.tools.dispatcher import DispatchContext


def focus_start(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.focus_store import start_focus

    r = start_focus(
        focus_min=int(args.get("minutes", 25) or 25),
        label=str(args.get("label", "")),
        break_min=int(args.get("break_min", 0) or 0),
        cycles=int(args.get("cycles", 1) or 1),
        scene=str(args.get("scene", "")),
        end_scene=str(args.get("end_scene", "")),
    )
    if r.get("ok"):
        # وشّها بيتغيّر لمركّز ونغمة البداية بتعزف والإضاءة بتهدا.
        # النغمة اسمها `focus_start` وموجودة باللوح من زمان — وما حدا كان
        # بيناديها، فجلسة التركيز كانت بتبلّش بسطر نصّ وبس.
        from app.features.robot_expression import focus_begin
        focus_begin()
        bits = [f"🎯 جلسة تركيز {r['focus_min']} دقيقة بلشت"]
        if r.get("cycles", 1) > 1:
            bits.append(f"— {r['cycles']} دورات، راحة {r['break_min']} دقيقة بين كل وحدة")
        if r.get("scene"):
            bits.append(f"· مشهد «{r['scene']}»" + (" شغّلته بالغرفة 🏠" if r.get("scene_online") else " (الغرفة مش متصلة)"))
        return {"handled": True, "reply": " ".join(bits) + ". ركّز! 💪"}
    if r.get("error") == "already_active":
        return {"handled": True, "reply": "في جلسة تركيز شغالة أصلاً — قول «خلصت» أو «الغي التركيز»."}
    return {"handled": True, "ok": False, "reply": "ما قدرت أبلش الجلسة."}


def focus_stop(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.focus_store import stop_focus

    completed = not bool(args.get("cancel"))
    r = stop_focus(completed=completed)
    if not r.get("ok"):
        return {"handled": True, "ok": False, "reply": "ما في جلسة تركيز شغالة."}
    from app.features.robot_expression import focus_end
    focus_end()
    if completed:
        return {"handled": True, "reply": f"🎉 برافو! ركزت {r['minutes']} دقيقة" + (f" على {r['label']}" if r.get("label") else "") + "."}
    return {"handled": True, "reply": "ألغيت جلسة التركيز — ولا يهمك."}


def focus_check(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.focus_store import focus_status

    s = focus_status()
    if not s.get("active"):
        return {"handled": True, "reply": "ما في جلسة تركيز شغالة 🎯"}
    phase = "راحة 😌" if s.get("phase") == "break" else "تركيز 🎯"
    cyc = f" · دورة {s['cycle_idx']}/{s['cycles']}" if s.get("cycles", 1) > 1 else ""
    return {
        "handled": True,
        "reply": f"{phase}{cyc} — ضايل {s['remaining_min']} دقيقة.",
    }


def focus_sound(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.focus_store import get_focus_sounds, set_focus_sound

    event = str(args.get("event", "")).strip().lower()
    melody = str(args.get("melody", "")).strip().lower()
    if not event or not melody:
        s = get_focus_sounds()
        return {"handled": True,
                "reply": f"🔔 أصوات التركيز — بداية: {s['start']} · راحة: {s['break']} · نهاية: {s['end']}"}
    r = set_focus_sound(event, melody)
    if r.get("ok"):
        word = {"start": "بداية التركيز", "break": "الراحة", "end": "نهاية التركيز"}.get(r["event"], r["event"])
        return {"handled": True, "reply": f"🔔 غيّرت صوت {word} لـ «{r['melody']}»."}
    if r.get("error") == "bad_melody":
        return {"handled": True, "ok": False, "reply": "النغمة مش موجودة. المتاح: " + "، ".join(r.get("choices", []))}
    return {"handled": True, "ok": False, "reply": "حدّد بداية/راحة/نهاية ونغمة صحيحة."}


_GOAL_AR = {"day": "اليومي", "week": "الأسبوعي", "month": "الشهري", "year": "السنوي"}
_PERIOD_AR = {"day": "اليوم", "week": "هالأسبوع", "month": "هالشهر", "year": "هالسنة"}


def focus_goal(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.focus_store import get_focus_goals, focus_stats, set_focus_goal

    period = str(args.get("period", "")).strip().lower()
    minutes = args.get("minutes")
    if not period or minutes in (None, ""):
        goals, st = get_focus_goals(), focus_stats()
        parts = [f"{_GOAL_AR[k]}: {st[k]['minutes']}/{goals[k]} دقيقة"
                 for k in ("day", "week", "month", "year") if goals.get(k)]
        if not parts:
            return {"handled": True, "reply": "ما في أهداف تركيز محددة. قل مثلاً «هدفي اليومي ساعتين تركيز»."}
        return {"handled": True, "reply": "🎯 أهدافك — " + " · ".join(parts)}
    r = set_focus_goal(period, int(minutes or 0))
    if r.get("ok"):
        return {"handled": True, "reply": f"🎯 ظبطت هدفك {_GOAL_AR.get(period, period)} على {r['minutes']} دقيقة تركيز."}
    return {"handled": True, "reply": "حدّد المدة (يومي/أسبوعي/شهري/سنوي) وعدد الدقايق."}


def focus_review(args: Dict[str, Any], ctx: "DispatchContext") -> Dict[str, Any]:
    from app.features.focus_store import focus_stats

    st = focus_stats()
    parts = []
    for k in ("day", "week", "month", "year"):
        seg = f"{_PERIOD_AR[k]}: {st[k]['minutes']} دقيقة"
        if st[k]["goal_min"]:
            seg += f" ({st[k]['pct']}٪ من الهدف)"
        parts.append(seg)
    return {"handled": True, "reply": "📊 تركيزك — " + " · ".join(parts)}


# ── مشاهد الغرفة ──────────────────────────────────────────────────────────────
