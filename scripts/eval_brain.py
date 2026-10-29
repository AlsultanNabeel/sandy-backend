"""Run real sentences through the brain on the real model and score what it did.

The unit tests drive the loop with a scripted model; this asks the real one, so it says
whether she actually understands. Run it before changing the model or the prompt:

    ~/sandy_app_venv/bin/python scripts/eval_brain.py                 # every case
    ~/sandy_app_venv/bin/python scripts/eval_brain.py --model gpt-4.1 # another deployment
    ~/sandy_app_venv/bin/python scripts/eval_brain.py --only expense  # cases by name
    ~/sandy_app_venv/bin/python scripts/eval_brain.py --repeat 2      # each case twice
    ~/sandy_app_venv/bin/python scripts/eval_brain.py --save          # keep the result

It costs model calls (about two per step), and prints what they cost (`features/pricing.py`,
from the turn traces). Nothing real is touched: the blocks live in an in-memory database,
and the tools that reach outside (devices, scenes, search, weather, images) are stand-ins
that only record they were called. The cases are in `eval_cases.py`.

`--repeat N` runs every case N times and names the ones whose outcome differed. A case the
model could not answer (a rate limit, an outage) waits and runs again, and is left out of the
score and the comparison when it still gets no answer: an error is not an outcome. `--save`
writes the result to `eval_results/<when>.json`; the first one saved becomes
`eval_results/baseline.json`, and every later run is compared with it: what fell, what
rose, and a saved run that passes becomes the baseline in its turn (`_promote`). The run fails
only on the plan's conditions (`_verdict`): a language under ninety percent, more than
`ALLOWED_SHARE` (five percent) of the cases moved between repeats, or fell against the baseline
(what rose is no failure), or English more than `LANGUAGE_GAP` points behind Arabic; a case
that fell on its own, or got no answer, is a warning. `--temperature` runs the brain at another temperature
(`model.TEMPERATURE`), to measure what it does to the tool calls.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud"))
sys.path.insert(0, str(ROOT / "scripts"))


RESULTS = ROOT / "scripts" / "eval_results"
# Two runs of the same cases may disagree on at most this share of them and still count as
# the same (the owner's rule, 29 Oct 2026: five percent, in place of two cases).
ALLOWED_SHARE = 0.05
# A turn the model could not answer (a 429, an outage) is no outcome: the case waits and
# runs again this many times, then is set apart as unanswered, never counted as a fail.
ERROR_RETRIES = 2
ERROR_WAIT_S = 30


def _args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", help="Azure chat deployment to test (default: the .env one)")
    p.add_argument("--only", default="", help="run only the cases whose name contains this")
    p.add_argument("--verbose", action="store_true", help="print every reply")
    p.add_argument("--repeat", type=int, default=1, help="run every case this many times")
    p.add_argument("--temperature", type=float,
                   help="the brain's temperature for this run (default: model.TEMPERATURE)")
    p.add_argument("--api", choices=("chat", "responses"), default="chat",
                   help="chat completions, or the Responses API (`brain/responses.py`) on --model")
    p.add_argument("--reasoning", default="low",
                   help="the Responses API's reasoning effort (default: low)")
    p.add_argument("--save", action="store_true",
                   help="save the result under eval_results/ and compare it with the baseline")
    return p.parse_args(argv)


# Imported (by its tests) it reads no command line and no .env: only a run does.
ARGS = _args() if __name__ == "__main__" else _args([])
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
    if ARGS.api == "responses":
        # The real switch, on for this run's account: the turn takes the path a user would.
        os.environ["SANDY_RESPONSES_DEPLOYMENT"] = ARGS.model or os.environ.get(
            "SANDY_RESPONSES_DEPLOYMENT", "")
        os.environ["SANDY_REASONING_EFFORT"] = ARGS.reasoning
        os.environ["SANDY_FLAGS"] = json.dumps({"responses_api": ["eval"], "tasks": ["eval"]})
    elif ARGS.model:
        os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"] = ARGS.model
    if ARGS.api != "responses":
        # The tasks' cases need their switch on for the run's account, as for the owner's.
        os.environ["SANDY_FLAGS"] = json.dumps({"tasks": ["eval"]})

import mongomock  # noqa: E402

from app import db as appdb  # noqa: E402
from app.blocks import entries, init_blocks, items, schedules  # noqa: E402
from app.brain import lang, loop, model as brain_model, tools  # noqa: E402
from app.features import device_store, trace_store  # noqa: E402
from app.utils.user_profiles import active_user_profile_context  # noqa: E402
from eval_cases import CASES, DEVICES  # noqa: E402

USER = {"chat_id": "eval", "relation": "user", "permissions": "all"}
_LATIN = re.compile(r"[A-Za-z]")
_ARABIC = re.compile(r"[؀-ۿ]")

# What the outside tools answer here, in the turn's language as the real ones do: enough
# for the model to go on, nothing sent.
def _device_line(a: Dict[str, Any]) -> str:
    target = a.get("device") or a.get("room") or ""
    action = str(a.get("action") or "").lower()
    key = {"on": "device_on", "off": "device_off", "open": "device_open", "close": "device_close"}
    if action in key:
        return lang.say(key[action], label=target)
    return lang.say("device_set", label=target, value=a.get("value") or action)


def _device_stand_in(a: Dict[str, Any], c: Any) -> Dict[str, Any]:
    """Nothing is sent, but the turn's own guards hold as in `tools_world.device_control`: a
    device set for later, or whose timer was refused, is not switched now (`takeback`)."""
    from app.brain import takeback
    from app.brain.tools_world import _resolve_device
    d = _resolve_device(str(a.get("device") or ""))
    if d is not None:
        now, later, refused_timer = takeback.now_or_later(c, [d], str(a.get("action") or ""),
                                                          a.get("value", ""))
        if refused_timer:
            return takeback.timer_refused(refused_timer)
        if later:
            return takeback.left_for_later()
    return {"ok": True, "reply": _device_line(a)}


_STAND_INS = {
    "device_control": _device_stand_in,
    "device_state": lambda a, c: {"ok": True, "devices": [{**d, "state": "off", "connected": True} for d in DEVICES]},
    "scene_apply": lambda a, c: {"ok": True, "reply": lang.say("scene_applied", label=a.get("name", ""), tail=" 🏠")},
    "room_restore": lambda a, c: {"ok": True, "reply": lang.say("restored", tail=" 🏠")},
    "web_search": lambda a, c: {"ok": True, "reply": "Latest news: the requested story (test source)."},
    "weather": lambda a, c: {"ok": True, "reply": "weather: 24°C, sunny."},
    "image": lambda a, c: {"ok": True, "reply": lang.say("image_done")},
}


def _fresh_db() -> None:
    d = mongomock.MongoClient().db
    appdb.configure(d)
    init_blocks(d)


def _setup(steps: List[Dict[str, Any]]) -> None:
    for s in steps:
        if "item" in s:
            items.add(s["item"]["list"], s["item"]["text"], s["item"].get("data"))
        elif "entry" in s:
            entries.add(s["entry"]["kind"], s["entry"]["text"], s["entry"].get("data"))
        elif "task" in s:
            from datetime import datetime, timedelta, timezone

            from app.blocks import tasks
            spec = {"instructions": s["task"]["title"], "notify_when": "something new",
                    "probe": {"tool": "web_search", "args": {"query": s["task"]["title"]}},
                    "tools": ["web_search"], "lang": "ar", "urgent": False}
            tasks.add(s["task"]["title"], spec, every_minutes=s["task"].get("every", 60),
                      first_at=datetime.now(timezone.utc) + timedelta(hours=1))
        elif "result" in s:
            from app import notify
            notify.CHANNELS = []                # a run never emails
            notify.deliver("eval-task", s["result"]["title"], s["result"]["body"], "ar")
        elif "reminder" in s:
            from datetime import datetime, timedelta, timezone
            at = datetime.now(timezone.utc) + timedelta(hours=s["reminder"].get("in_hours", 3))
            schedules.add("reminder", s["reminder"]["text"], at)


def _has(rows: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    return [r for r in rows if text.lower() in str(r.get("text") or "").lower()]


def _check(step: Dict[str, Any], state: Dict[str, Any], used: List[str]) -> List[str]:
    """What this step expected and did not get (empty: it passed)."""
    reply = str(state.get("final_response") or "")
    bad: List[str] = []
    for name in step.get("tools", []):
        if name not in used:
            bad.append(f"ما استدعت {name} (استدعت {used or 'ولا إشي'})")
    for name in step.get("not_tools", []):
        if name in used:
            bad.append(f"استدعت {name} وما لازم")
    if step.get("any_tools") and not set(step["any_tools"]) & set(used):
        bad.append(f"ما استدعت ولا وحدة من {step['any_tools']} (استدعت {used or 'ولا إشي'})")
    if step.get("no_tools") and used:
        bad.append(f"استدعت أدوات وما لازم: {used}")
    if "item" in step:
        want = step["item"]
        rows = _has(items.list_items(want.get("list")), want["has"])
        if not rows:
            bad.append(f"ما في عنصر «{want['has']}» بقائمة {want.get('list')}")
        elif "done" in want and rows[0].get("done") != want["done"]:
            bad.append(f"العنصر «{want['has']}» done={rows[0].get('done')}")
        elif "data" in want and any((rows[0].get("data") or {}).get(k) != v for k, v in want["data"].items()):
            bad.append(f"بيانات «{want['has']}» {rows[0].get('data')}")
    if "no_item" in step and _has(items.list_items(step["no_item"].get("list"), done=False), step["no_item"]["has"]):
        bad.append(f"لسا في عنصر مفتوح «{step['no_item']['has']}»")
    if "schedule" in step:
        want = step["schedule"]
        rows = _has(schedules.list_schedules("reminder", status="pending"), want["has"])
        if not rows:
            bad.append(f"ما في تذكير «{want['has']}»")
        elif want.get("repeats") and not rows[0].get("recurrence"):
            bad.append(f"التذكير «{want['has']}» مش متكرر")
    if "no_schedule" in step and _has(schedules.list_schedules("reminder", status="pending"), step["no_schedule"]):
        bad.append(f"لسا في تذكير «{step['no_schedule']}»")
    if "no_entry" in step and entries.list_entries(step["no_entry"]["kind"]):
        bad.append(f"لسا في {step['no_entry']['kind']} بالسجلّ")
    if "entry" in step:
        want = step["entry"]
        rows = entries.list_entries(want["kind"])
        if want.get("has"):
            rows = _has(rows, want["has"])
        if not rows:
            bad.append(f"ما انحفظ إشي من نوع {want['kind']}")
        elif "amount" in want and (rows[0].get("data") or {}).get("amount") != want["amount"]:
            bad.append(f"المبلغ {(rows[0].get('data') or {}).get('amount')} مش {want['amount']}")
    if "timer" in step:
        from app.blocks import schedules
        want = step["timer"]
        rows = [r for r in schedules.list_schedules("scene", status="pending")
                if (r.get("payload") or {}).get("asked")]
        if not any((r["payload"].get("device"), r["payload"].get("value")) == (want["device"], want["value"])
                   for r in rows):
            bad.append(f"ما انجدول {want['device']} → {want['value']} ({[r.get('payload') for r in rows]})")
    if "task" in step or step.get("no_task"):
        from app.blocks import tasks
        running = tasks.running()
        if step.get("no_task") and running:
            bad.append(f"في مهمة وما لازم: {[r.get('text') for r in running]}")
        if "task" in step:
            want, row = step["task"], (running[0] if running else None)
            if row is None:
                bad.append("ما انعملت مهمة")
            elif want.get("check") and (row.get("payload") or {}).get("probe", {}).get("tool") != want["check"]:
                bad.append(f"فحص المهمة {(row.get('payload') or {}).get('probe')}")
            elif want.get("every") and not str(row.get("recurrence") or "").endswith(f"INTERVAL={want['every']}"):
                bad.append(f"المهمة {row.get('recurrence')} مش كل {want['every']} دقيقة")
            elif "paused" in want and (row.get("status") == "paused") != want["paused"]:
                bad.append(f"المهمة {row.get('status')}")
            elif want.get("delivery") and tasks.how(row) != want["delivery"]:
                bad.append(f"التبليغ {tasks.how(row)} مش {want['delivery']}")
    if step.get("pending") is True and not state.get("pending_state"):
        bad.append("ما استنّت تأكيد")
    if step.get("pending") is False and state.get("pending_state"):
        bad.append("لسا مستنية تأكيد")
    if step.get("reply_has") and not any(w in reply for w in step["reply_has"]):
        bad.append(f"الرد ما فيه أي من {step['reply_has']}")
    said = [w for w in step.get("reply_lacks", []) if w in reply]
    if said:
        bad.append(f"الرد فيه {said} وما لازم")
    if step.get("english") and not _is_english(reply):
        bad.append("الرد مش بالإنجليزي")
    return bad


def _is_english(reply: str) -> bool:
    """English through and through: no Arabic word, though a name may stay as it is (a
    «quoted» one, or a device's own label)."""
    text = re.sub(r"«[^»]*»", "", reply)
    for d in DEVICES:
        text = text.replace(d["label"], "").replace(d["room"], "")
    return bool(_LATIN.search(text)) and not _ARABIC.search(text)


def _arg_matches(want: Any, got: Any) -> bool:
    """A word of text is found inside the call's text; anything else must be equal."""
    if isinstance(want, str) and isinstance(got, str):
        return want == got or want in got
    return want == got


def _args_check(want: Dict[str, Dict[str, Any]], calls: List[Tuple[str, Dict[str, Any]]]) -> List[str]:
    """For each tool in ``want``, one of its calls carries every value asked for."""
    bad: List[str] = []
    for name, expected in want.items():
        made = [a for n, a in calls if n == name]
        if not any(all(_arg_matches(v, a.get(k)) for k, v in expected.items()) for a in made):
            bad.append(f"{name} ما انطلبت بـ {expected} (انطلبت بـ {made or 'ولا مرة'})")
    return bad


def _spent() -> Dict[str, Any]:
    """Tokens and dollars of every turn in this database, from its traces."""
    rows = list(appdb.get_db()[trace_store.COLLECTION].find(
        {}, {"tokens_in": 1, "tokens_out": 1, "tokens_reasoning": 1, "cost_usd": 1}).limit(10_000))
    return {"tokens_in": sum(int(r.get("tokens_in") or 0) for r in rows),
            "tokens_out": sum(int(r.get("tokens_out") or 0) for r in rows),
            "tokens_reasoning": sum(int(r.get("tokens_reasoning") or 0) for r in rows),
            "usd": sum(float(r.get("cost_usd") or 0) for r in rows)}


def _run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    _fresh_db()
    pending, failures, seconds, error = None, [], 0.0, False
    calls: List[Tuple[str, Dict[str, Any]]] = []
    real_execute = tools.execute

    def recording(name, args, ctx):
        calls.append((name, dict(args or {})))
        return real_execute(name, args, ctx)

    tools.execute = recording
    try:
        with active_user_profile_context(USER):
            _setup(case.get("setup", []))
            for n, step in enumerate(case["steps"], 1):
                calls.clear()
                began = time.monotonic()
                state = loop.run_turn(step["say"], user_id="eval", chat_id="eval",
                                      source="web", pending_state=pending)
                seconds += time.monotonic() - began
                pending = state.get("pending_state")
                error |= bool(state.get("error"))
                used = list(state.get("tools_used") or [])
                if ARGS.verbose:
                    print(f"    «{step['say']}» → {calls} → {state.get('final_response')!r}")
                bad = _check(step, state, used) + _args_check(step.get("args", {}), calls)
                failures += [f"خطوة {n}: {b}" for b in bad]
    finally:
        tools.execute = real_execute
    return {"name": case["name"], "failures": failures, "seconds": seconds, "error": error,
            **_spent()}


def _run_answered(case: Dict[str, Any]) -> Dict[str, Any]:
    """The case, run again after a wait while the model gave no answer (`ERROR_RETRIES`)."""
    r = _run_case(case)
    for _ in range(ERROR_RETRIES):
        if not r["error"]:
            break
        print(f"  … {case['name']}: the model gave no answer, again in {ERROR_WAIT_S}s")
        time.sleep(ERROR_WAIT_S)
        r = _run_case(case)
    return r


def _disagreeing(runs: Dict[str, List[bool]]) -> List[str]:
    """The cases that passed in one repeat and failed in another."""
    return sorted(name for name, outcomes in runs.items() if len(set(outcomes)) > 1)


def _compare(base: Dict[str, Any], now: Dict[str, Any]) -> Dict[str, List[str]]:
    """What moved; a case left unanswered (None) on either side is left out."""
    before = {n: ok for n, ok in (base.get("cases") or {}).items() if ok is not None}
    after = {n: ok for n, ok in (now.get("cases") or {}).items() if ok is not None}
    return {"fell": sorted(n for n, ok in after.items() if n in before and before[n] and not ok),
            "rose": sorted(n for n, ok in after.items() if n in before and not before[n] and ok),
            "new": sorted(n for n in after if n not in before)}


# English may trail Arabic by at most this many points, and never the other way round
# matters: they are meant to be equal.
LANGUAGE_GAP = 5


def _by_language(outcome: Dict[str, Optional[bool]], langs: Dict[str, str]) -> Dict[str, Tuple[int, int]]:
    """(passed, scored) for each language, unanswered cases left out."""
    out: Dict[str, Tuple[int, int]] = {}
    for name, ok in outcome.items():
        if ok is None:
            continue
        p, t = out.get(langs.get(name, "ar"), (0, 0))
        out[langs.get(name, "ar")] = (p + bool(ok), t + 1)
    return out


def _stable(moved: int, total: int) -> bool:
    """Two runs count as the same while at most `ALLOWED_SHARE` of the cases moved."""
    return moved <= ALLOWED_SHARE * total


# Each language must pass at least this share of its cases (the plan's general condition 3).
PASS_SHARE = 0.9


def _verdict(scores: Dict[str, Tuple[int, int]], moved: int, total: int, failed: List[str],
             unanswered: Optional[List[str]] = None) -> Tuple[bool, List[str]]:
    """(the run passes, its warnings). It fails only on the plan's conditions: a language under
    `PASS_SHARE`, more than `ALLOWED_SHARE` of the cases moved, or English more than
    `LANGUAGE_GAP` points behind Arabic. A case that fell, or got no answer, is a warning."""
    ok = _stable(moved, total) and _language_gap_ok(scores)
    ok &= all(p >= PASS_SHARE * t for p, t in scores.values() if t)
    warnings = [f"fell: {name}" for name in failed]
    warnings += [f"no answer from the model (left out): {name}" for name in sorted(set(unanswered or []))]
    return ok, warnings


def _language_gap_ok(scores: Dict[str, Tuple[int, int]]) -> bool:
    pct = {k: 100 * p / t for k, (p, t) in scores.items() if t}
    return "ar" not in pct or "en" not in pct or pct["en"] >= pct["ar"] - LANGUAGE_GAP


def _fell(moved: Dict[str, List[str]]) -> int:
    """Against the baseline only what fell counts: a case that rose is no failure."""
    return len(moved["fell"])


def _promote(path: Path, folder: Path = RESULTS) -> None:
    """A saved run that passed is the baseline the next is compared with."""
    (folder / "baseline.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _save(result: Dict[str, Any], folder: Path = RESULTS) -> Tuple[Path, Optional[Dict[str, Any]]]:
    """Write the result; the baseline it is compared with, or None when this one became it."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{result['when'].replace(':', '')}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    baseline = folder / "baseline.json"
    if not baseline.exists():
        baseline.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        return path, None
    return path, json.loads(baseline.read_text(encoding="utf-8"))


def main() -> int:
    for name, fn in _STAND_INS.items():
        tools.HANDLERS[name] = fn
    # His devices as switches, read where the tools read them (a timer checks its command).
    known = [{**d, "control_type": "switch"} for d in DEVICES]
    device_store.list_devices = lambda: list(known)
    device_store.get_device = lambda name: next((dict(d) for d in known if d["name"] == name), None)
    # Embeddings would cost a call per entry and find nothing in a fresh database.
    entries.embed_text = lambda text: None

    if ARGS.temperature is not None:
        brain_model.TEMPERATURE = ARGS.temperature
    model = (os.environ.get("SANDY_RESPONSES_DEPLOYMENT") if ARGS.api == "responses" else None) \
        or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT") or os.environ.get("OPENAI_MODEL")
    cases = [c for c in CASES if ARGS.only in c["name"]]
    repeat = max(ARGS.repeat, 1)
    how = (f"on the Responses API, reasoning {ARGS.reasoning}" if ARGS.api == "responses"
           else f"at temperature {brain_model.TEMPERATURE}")
    print(f"model: {model} {how} — {len(cases)} cases × {repeat}\n")
    runs: Dict[str, List[bool]] = {}
    unanswered: List[str] = []
    seconds, spent = 0.0, {"tokens_in": 0, "tokens_out": 0, "tokens_reasoning": 0, "usd": 0.0}
    for case in cases:
        for _ in range(repeat):
            r = _run_answered(case)
            if r["error"]:
                unanswered.append(r["name"])
                print(f"? {r['name']}  (no answer from the model — left out)")
                continue
            runs.setdefault(r["name"], []).append(not r["failures"])
            seconds += r["seconds"]
            for k in spent:
                spent[k] += r[k]
            mark = "✓" if not r["failures"] else "✗"
            print(f"{mark} {r['name']}  ({r['seconds']:.1f}s)")
            for f in r["failures"]:
                print(f"    {f}")
    # A case counts as passed only when every repeat passed; one never answered is None.
    outcome: Dict[str, Optional[bool]] = {name: all(oks) for name, oks in runs.items()}
    for name in unanswered:
        outcome.setdefault(name, None)
    scored = {n: ok for n, ok in outcome.items() if ok is not None}
    passed = sum(scored.values())
    messages = repeat * sum(len(c["steps"]) for c in cases)
    print(f"\n{passed}/{len(scored)} passed ({100 * passed // max(len(scored), 1)}%), "
          f"average {seconds / max(messages, 1):.1f}s a message")
    print(f"cost: ${spent['usd']:.4f} ({spent['tokens_in']} tokens in, {spent['tokens_out']} out, "
          f"{spent['tokens_reasoning']} of them reasoning)")
    langs = {c["name"]: c.get("lang", "ar") for c in cases}
    scores = _by_language(outcome, langs)
    for language, (p, t) in sorted(scores.items()):
        print(f"  {language}: {p}/{t} ({100 * p // max(t, 1)}%)")
    gap_ok = _language_gap_ok(scores)
    if not gap_ok:
        print(f"English trails Arabic by more than {LANGUAGE_GAP} points")
    split = _disagreeing(runs)
    if repeat > 1:
        print(f"repeats disagreed on {len(split)} case(s), "
              f"{100 * len(split) / max(len(cases), 1):.1f}% of {len(cases)}: {split or '—'}")
    ok, warnings = _verdict(scores, len(split), len(cases),
                            sorted(n for n, good in scored.items() if not good), unanswered)
    for warning in warnings:
        print(f"warning — {warning}")
    if ARGS.save:
        result = {"when": datetime.now().strftime("%Y-%m-%dT%H:%M"), "model": model,
                  "api": ARGS.api, **({"reasoning": ARGS.reasoning} if ARGS.api == "responses" else {}),
                  "repeat": repeat, "temperature": brain_model.TEMPERATURE, "passed": passed,
                  "total": len(scored), "cases": outcome,
                  "unanswered": sorted(set(unanswered)),
                  "by_language": {k: {"passed": p, "total": t} for k, (p, t) in scores.items()},
                  "disagreed": split, "seconds": round(seconds, 1), **spent}
        path, base = _save(result)
        print(f"saved: {path.relative_to(ROOT)}")
        if base is None:
            print("this is the baseline now")
        else:
            moved = _compare(base, result)
            print(f"against the baseline ({base['when']}, {base['passed']}/{base['total']}): "
                  f"fell {moved['fell'] or '—'}, rose {moved['rose'] or '—'}, new {moved['new'] or '—'}")
            ok &= _stable(_fell(moved), len(scored))
            if ok:
                _promote(path)
                print("this is the baseline now")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
