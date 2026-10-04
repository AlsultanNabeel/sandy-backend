"""Run real sentences through the brain on the real model and score what it did.

The unit tests drive the loop with a scripted model; this asks the real one, so it says
whether she actually understands. Run it before changing the model or the prompt:

    ~/sandy_app_venv/bin/python scripts/eval_brain.py                 # every case
    ~/sandy_app_venv/bin/python scripts/eval_brain.py --model gpt-4.1 # another deployment
    ~/sandy_app_venv/bin/python scripts/eval_brain.py --only expense  # cases by name

It costs model calls (about two per step). Nothing real is touched: the blocks live in
an in-memory database, and the tools that reach outside (devices, scenes, search,
weather, images) are stand-ins that only record they were called. The cases are in
`eval_cases.py`.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud"))
sys.path.insert(0, str(ROOT / "scripts"))


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", help="Azure chat deployment to test (default: the .env one)")
    p.add_argument("--only", default="", help="run only the cases whose name contains this")
    p.add_argument("--verbose", action="store_true", help="print every reply")
    return p.parse_args()


ARGS = _args()
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)
if ARGS.model:
    os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"] = ARGS.model

import mongomock  # noqa: E402

from app import db as appdb  # noqa: E402
from app.blocks import entries, init_blocks, items, schedules  # noqa: E402
from app.brain import loop, tools  # noqa: E402
from app.features import device_store  # noqa: E402
from app.utils.user_profiles import active_user_profile_context  # noqa: E402
from eval_cases import CASES, DEVICES  # noqa: E402

USER = {"chat_id": "eval", "relation": "user", "permissions": "all"}
_LATIN = re.compile(r"[A-Za-z]")
_ARABIC = re.compile(r"[؀-ۿ]")

# What the outside tools answer here: enough for the model to go on, nothing sent.
_STAND_INS = {
    "device_control": lambda a, c: {"ok": True, "reply": f"تم: {a.get('device') or a.get('room')} {a.get('action', '')}"},
    "device_state": lambda a, c: {"ok": True, "devices": [{**d, "state": "off", "connected": True} for d in DEVICES]},
    "scene_apply": lambda a, c: {"ok": True, "reply": f"✨ طبّقت مشهد «{a.get('name', '')}» 🏠"},
    "room_restore": lambda a, c: {"ok": True, "reply": "رجّعت الغرفة زي ما كانت 🏠"},
    "web_search": lambda a, c: {"ok": True, "reply": "حسب آخر الأخبار: الخبر المطلوب (مصدر تجريبي)."},
    "weather": lambda a, c: {"ok": True, "reply": "الطقس: ٢٤ درجة، مشمس."},
    "image": lambda a, c: {"ok": True, "reply": "جهزت الصورة."},
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
        elif "reminder" in s:
            from datetime import datetime, timedelta, timezone
            at = datetime.now(timezone.utc) + timedelta(hours=s["reminder"].get("in_hours", 3))
            schedules.add("reminder", s["reminder"]["text"], at)


def _has(rows: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    return [r for r in rows if text in str(r.get("text") or "")]


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
    if "entry" in step:
        want = step["entry"]
        rows = entries.list_entries(want["kind"])
        if want.get("has"):
            rows = _has(rows, want["has"])
        if not rows:
            bad.append(f"ما انحفظ إشي من نوع {want['kind']}")
        elif "amount" in want and (rows[0].get("data") or {}).get("amount") != want["amount"]:
            bad.append(f"المبلغ {(rows[0].get('data') or {}).get('amount')} مش {want['amount']}")
    if step.get("pending") is True and not state.get("pending_state"):
        bad.append("ما استنّت تأكيد")
    if step.get("pending") is False and state.get("pending_state"):
        bad.append("لسا مستنية تأكيد")
    if step.get("reply_has") and not any(w in reply for w in step["reply_has"]):
        bad.append(f"الرد ما فيه أي من {step['reply_has']}")
    if step.get("english") and len(_LATIN.findall(reply)) <= len(_ARABIC.findall(reply)):
        bad.append("الرد مش بالإنجليزي")
    return bad


def _run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    _fresh_db()
    pending, failures, seconds = None, [], 0.0
    with active_user_profile_context(USER):
        _setup(case.get("setup", []))
        for n, step in enumerate(case["steps"], 1):
            began = time.monotonic()
            state = loop.run_turn(step["say"], user_id="eval", chat_id="eval",
                                  source="web", pending_state=pending)
            seconds += time.monotonic() - began
            pending = state.get("pending_state")
            used = list(state.get("tools_used") or [])
            if ARGS.verbose:
                print(f"    «{step['say']}» → {used} → {state.get('final_response')!r}")
            failures += [f"خطوة {n}: {b}" for b in _check(step, state, used)]
    return {"name": case["name"], "failures": failures, "seconds": seconds}


def main() -> int:
    for name, fn in _STAND_INS.items():
        tools.HANDLERS[name] = fn
    device_store.list_devices = lambda: list(DEVICES)
    # Embeddings would cost a call per entry and find nothing in a fresh database.
    entries.embed_text = lambda text: None

    cases = [c for c in CASES if ARGS.only in c["name"]]
    print(f"model: {os.environ.get('AZURE_OPENAI_CHAT_DEPLOYMENT') or os.environ.get('OPENAI_MODEL')}"
          f" — {len(cases)} cases\n")
    results = []
    for case in cases:
        r = _run_case(case)
        results.append(r)
        mark = "✓" if not r["failures"] else "✗"
        print(f"{mark} {r['name']}  ({r['seconds']:.1f}s)")
        for f in r["failures"]:
            print(f"    {f}")
    passed = sum(not r["failures"] for r in results)
    total_s = sum(r["seconds"] for r in results)
    print(f"\n{passed}/{len(results)} passed ({100 * passed // max(len(results), 1)}%), "
          f"average {total_s / max(sum(len(c['steps']) for c in cases), 1):.1f}s a message")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
