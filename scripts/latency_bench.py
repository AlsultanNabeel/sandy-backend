"""Time the two model calls a chat turn waits on, and check the router's picks.

The Heroku `[turn]` line says where one real turn's time went. This answers
the question that comes after it — *what would change it* — without a deploy:
the router with its real system prompt and its real eighty-tool catalogue,
timed against a labelled set of the owner's own kind of sentence, and the chat
reply's time to first token. Run from the repo root, with the same `.env` the
voice probe reads:

    python scripts/latency_bench.py
    python scripts/latency_bench.py --gemini gemini-flash-lite-latest
    python scripts/latency_bench.py --reps 3

`--gemini` times `integrations/gemini_router` on the same set, beside Azure, so
switching router backends is a decision made from two columns of numbers — speed
*and* correct picks — rather than from a model's reputation. The first call of
each backend is reported separately: it pays connection setup, and a warm
number is what every message after the first one pays.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "cloud")]

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# (message, acceptable tool names). An empty set means "chat": the router may
# call chat_respond / chat_emotional or answer in plain text.
_CASES: list[tuple[str, set[str]]] = [
    ("ذكريني بكرا الساعة تسعة الصبح اتصل بالدكتور", {"reminder_create"}),
    ("ضيفي مهمة أخلص التقرير", {"task_create"}),
    ("شو مهامي اليوم؟", {"task_list"}),
    ("احذفي مهمة التقرير", {"task_delete", "request_confirmation"}),
    ("طفّي ضو الصالة", {"device_control"}),
    ("شغّلي وضع النوم", {"scene_apply"}),
    ("خلصت جلسة التركيز", {"focus_stop"}),
    ("ضيفي حليب لقائمة التسوق", {"shopping_add"}),
    ("كيف الطقس بكرا؟", {"get_weather"}),
    ("دوريلي على مطعم شاورما قريب", {"research_places", "research_web"}),
    ("كيفك اليوم؟", set()),
    ("تعبت كتير اليوم", set()),
]
_CHAT = {"chat_respond", "chat_emotional"}

_CHAT_PROMPTS = ["كيفك اليوم؟", "احكيلي نكتة قصيرة", "شو رأيك نروح مشوار العصر؟"]


def _correct(expected: set[str], picked: list[str]) -> bool:
    if not expected:
        return not picked or set(picked) <= _CHAT
    return bool(set(picked) & expected)


def _router_inputs():
    from app.agent.agents.fc_router import (
        _META_TOOL_SPECS,
        _ROUTER_SYSTEM,
        _build_native_tools,
    )
    from app.agent.command_rules import DISAMBIGUATION_RULES_AR
    from app.agent.tools.registry import get_registry
    from app.agent.tools.setup import register_all_tools

    register_all_tools()
    decl = get_registry().get_function_declarations()
    system = _ROUTER_SYSTEM + "\n\n" + DISAMBIGUATION_RULES_AR
    return system, decl, _build_native_tools(decl), list(decl) + _META_TOOL_SPECS


def _azure_route(system, tools, message) -> list[str]:
    from app.agent.agents.fc_router import _parse_tool_message
    from app.integrations.azure_intent_client import AzureIntentClient

    msg = AzureIntentClient().complete_with_tools(system, f"رسالة المستخدم: {message}", tools)
    return [c["name"] for c in _parse_tool_message(msg)]


def _gemini_route(system, specs, message) -> list[str]:
    from app.integrations.gemini_router import route_with_gemini

    calls = route_with_gemini(system, f"رسالة المستخدم: {message}", specs)
    if calls is None:
        raise RuntimeError("gemini router failed — see the log line above")
    return [c["name"] for c in calls]


def _bench(label, fn, reps) -> None:
    print(f"\n── router: {label}")
    times, ok, first = [], 0, None
    for rep in range(reps):
        for message, expected in _CASES:
            t = time.perf_counter()
            try:
                picked = fn(message)
            except Exception as exc:  # noqa: BLE001 — report and keep measuring
                print(f"   ERROR {message!r}: {exc}")
                continue
            ms = (time.perf_counter() - t) * 1000
            if first is None:
                first = ms
            else:
                times.append(ms)
            if rep == 0:
                good = _correct(expected, picked)
                ok += good
                print(f"   {ms:6.0f}ms  {'✓' if good else '✗'}  {message}  → {picked}")
    if times:
        print(f"   first call {first:.0f}ms · warm median {statistics.median(times):.0f}ms "
              f"· p90 {sorted(times)[int(len(times) * 0.9) - 1]:.0f}ms · "
              f"correct {ok}/{len(_CASES)}")


def _bench_chat() -> None:
    from app.agent.nodes.execute import _CHAT_BEHAVIOR_RULES, _get_chat_completion_fn
    from app.config import SANDY_PERSONALITY

    fn = _get_chat_completion_fn()
    system = (SANDY_PERSONALITY or "أنتِ ساندي.") + "\n" + _CHAT_BEHAVIOR_RULES
    print("\n── chat reply (streamed, as /api/agent/stream does)")
    for prompt in _CHAT_PROMPTS:
        t = time.perf_counter()
        ttft = None
        text = ""
        stream = fn(messages=[{"role": "system", "content": system},
                              {"role": "user", "content": prompt}],
                    max_tokens=400, temperature=0.7, stream=True)
        for chunk in stream:
            delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if delta and ttft is None:
                ttft = time.perf_counter() - t
            text += delta
        total = time.perf_counter() - t
        print(f"   first token {(ttft or total) * 1000:5.0f}ms · whole reply {total * 1000:5.0f}ms"
              f" · {len(text)} chars  ({prompt})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gemini", default="", help="also time the Gemini router with this model")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--no-chat", action="store_true")
    args = ap.parse_args()
    if args.gemini:
        # gemini_router reads its model at import; set it before that happens.
        os.environ["GEMINI_ROUTER_MODEL"] = args.gemini

    from app.integrations.azure_intent_client import DEFAULT_AZURE_INTENT_DEPLOYMENT

    system, decl, tools, specs = _router_inputs()
    print(f"tools: {len(decl)} · router system prompt: {len(system)} chars · "
          f"azure deployment: {DEFAULT_AZURE_INTENT_DEPLOYMENT}")

    _bench(f"azure ({DEFAULT_AZURE_INTENT_DEPLOYMENT})",
           lambda m: _azure_route(system, tools, m), args.reps)
    if args.gemini:
        _bench(f"gemini ({args.gemini})", lambda m: _gemini_route(system, specs, m), args.reps)
    if not args.no_chat:
        _bench_chat()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
