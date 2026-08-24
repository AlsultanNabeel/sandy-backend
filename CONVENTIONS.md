# Sandy Engineering Conventions

Rules every change in this codebase follows. Tasks in `PLAN/` cite these by number.

## C1 — Error handling: make problems louder, not quieter
- Never write `except Exception: pass`. If you truly must continue, log first:
  `logger.warning("[area] what failed: %s", exc)` — or `logger.exception(...)`
  inside a background worker (it captures the traceback).
- Catch the **narrowest** exception you can. Use broad `except Exception` only
  at true boundaries (a background thread, a request handler, an external API
  call). Everywhere else, let unexpected errors propagate.
- Distinguish **expected** failures (network down, key missing → degrade
  gracefully, log at `warning`) from **unexpected** ones (a bug → log at
  `error`/`exception`, surface it).
- Never use `print(...)` for diagnostics. Use the module `logger`.

## C2 — Logging
- One `logger = logging.getLogger(__name__)` per module.
- Prefix messages with the area: `[router]`, `[auth]`, `[voice]`, etc.
- Use `%s` lazy formatting (`logger.info("x=%s", x)`), not f-strings, in log calls.

## C3 — Concurrency: one path for background work
- All fire-and-forget work goes through `submit_background(...)` from
  `app.utils.thread_pool`. Do NOT spawn raw `threading.Thread(...)` for
  fire-and-forget tasks. (Long-lived loops and the MQTT listener are exempt.)

## C4 — External clients: build once, reuse
- SDK clients (OpenAI, AzureOpenAI, Gemini, MongoDB) are created once at module
  or app scope and reused. Never construct a client inside a per-request or
  per-message function.

## C5 — Multi-tenancy: never assume who the user is
- The user's display name is resolved with `resolve_display_name(...)` from
  `app.utils.user_profiles`. Never hardcode a person's name in logic or
  prompts to address the user.
- EXCEPTION: Sandy's **creator** identity ("نبيل السلطان" as her developer in
  persona text) is product copy, not a user-addressing assumption — leave it.

## C6 — Config
- Read env vars only in `app.config`. Other modules import the named constant.
- Critical-but-missing config fails fast at boot (see `validate_config`);
  optional-but-missing config only disables its own feature.

## C7 — User-facing copy
- Arabic strings shown to users are product copy. Do not edit, "improve," or
  translate them unless a task explicitly asks. Keep them byte-for-byte.

## C8 — Command understanding (anti-hallucination)
- Do not infer the user's intent from raw substring/keyword matching on free
  text (e.g. `"امتحان" in message`). Keyword matching fires on words that
  appear inside stories, quotes, or negations. Intent comes from the model's
  function-calling decision; keyword lists may only *rank* or *tie-break*
  already-structured data, never trigger an action on their own.

## C9 — Inline imports
Function-level imports exist to break real circular dependencies and are
acceptable where that's the reason. For NEW code, prefer module-top imports;
only drop an import inside a function when a module-top import would create a
cycle, and add a one-line comment saying so. Do not mass-hoist existing inline
imports — they are load-bearing.

## C10 — A handler result answers three questions, not one
`handled` — "this handler owns the turn and here is its answer".
`ok` — "the change the user asked for actually happened".
`error` — "the tool itself broke".

A refusal is `{"handled": True, "ok": False}`: it ran, and the answer is no. A
handler that catches its own exception adds `error`, because a friendly failure
sentence is still a failure — `_guard` in `executor/dispatch.py` is the model to
copy.

Set `ok=False` when the handler is **finished** and the request did not take
effect: a refusal, a not-found target of a change, an input it gave up on, a
failed write, a no-op with nothing to act on. Do **not** set it when:
- a read or search legitimately found nothing — the request took effect and the
  answer is an empty list;
- the requested end state already holds (pausing what is paused);
- **a pending action is still live.** A confirmation prompt or a re-ask that
  keeps the pending alive is the flow continuing, not ending, and marking it
  makes the next turn look like a failure to a model that is mid-conversation.

An ask that stores **no** pending is finished, and is marked: `task_create` with
no title asks "شو المهمة اللي بدك أضيفها؟" and nothing carries that forward, so
without the mark the adapter above it wrote "سجّلتها ✅" over the question.

Read `ok` with `app.agent.tool_result.result_ok` at any site that renders a
success sentence. Read breakage with `result_failed`, which is `error` and
nothing else:
- `tool_health` uses `result_failed`, never `ok`. A refusal is not flakiness,
  and the counter is process-global and keyed by tool name, so three customers
  each mistyping an item once would otherwise be enough to tell the owner his
  shopping tool is broken.
- `handled: False` is **not** breakage either. It is a routing signal —
  `task_update` returns it for "say which field you want changed" — and scoring
  it as failure marks a healthy tool degraded after three clarifications.
- The voice path marks **everything** that did not happen, because an unmarked
  refusal is what Gemini reads as success and confirms to the user. It marks
  them differently: `[فشل التنفيذ]` for breakage — raised, not found
  (`handled: False`), or `error` set — and `[لم يُنفَّذ]` for a refusal.
  Calling "ما لقيت جهاز بهالاسم، أي واحد تقصد؟" a failed execution makes her
  abandon a disambiguation the user is halfway through.

Never read `result["handled"]` to decide whether something worked. Omitting `ok`
means `ok == handled`, so an un-migrated handler keeps its old behaviour; that
default is a migration aid, not a licence to skip it — and it is why a site that
overwrites a reply with a success sentence must check `ok`, not `handled`.

An adapter that replaces a handler's reply must not destroy what the handler
alone knows. `task_create` swaps in a persona-toned sentence; the scheduling
conflict warning travels beside it as `alert` so the swap stops costing it.
