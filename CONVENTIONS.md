# Sandy Engineering Conventions

Rules every change in this codebase follows. Tests and code comments cite them by number.

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

### C8b — The one deterministic route, and the four conditions on it

`brain/fast_path.py` picks a tool without asking a model. That is the shape C8
exists to stop, so it is written down here rather than argued in a commit
message, and it is allowed **only** while all four of these hold. Anything that
wants to join it satisfies all four or it does not go in.

1. **The candidates are structured, per-tenant data.** Not a phrase list in the
   source — the caller's own `sandy_devices` rows, and their actions as
   `device_store.command_payload` validates them. This is the "rank or tie-break
   already-structured data" that C8 already permits; a phrase the fast path can
   match does not exist until a user registers the device it names.
2. **The match consumes the whole utterance.** A verb and a device label are
   removed and *nothing may be left*. This is the condition that answers C8's own
   objection: a keyword search finds "شغل الضو" inside a story about somebody
   else saying it, and a whole-utterance match does not, because the other
   eleven words have nowhere to go.
3. **It only picks; it never acts.** It returns the tool call the model would
   have made and the brain's own `device_control` runs it — `command_payload`,
   `tenant_owns_topic`. It can be wrong about intent and still cannot be wrong
   about permission. It names `device_control` and nothing else, so nothing that
   deletes or cancels is reachable, and no device whose real-world effect is not
   a closed reversible set (`ir`, `text`, `enum`) is either.
4. **It fails open.** Every uncertainty — a leftover word, two devices matching
   the same label, an action the device refuses, any exception — returns `None`
   and the model decides. A route that fails *closed* would be C8's failure mode
   with extra steps.

The kill switch is `SANDY_FAST_PATH=0` (`app/config.py`), so it can be ruled out
in one variable while diagnosing something else.

## C9 — Inline imports
Function-level imports exist to break real circular dependencies and are
acceptable where that's the reason. For NEW code, prefer module-top imports;
only drop an import inside a function when a module-top import would create a
cycle, and add a one-line comment saying so. Do not mass-hoist existing inline
imports — they are load-bearing.

## C3b — What "fire-and-forget" means
C3 bans raw `threading.Thread` for fire-and-forget work. Two shapes are outside
it and must say so where they sit:

- **A long-lived singleton** started once for the life of the process — the MQTT
  reconnect watchdog, the one-shot speaker-model warm-up.
- **Work the request waits on.** `/api/agent/stream` runs the turn on a
  thread and streams what it produces; the request ends when that thread ends.
  Putting it on the shared background pool would let ten concurrent streams hold
  every worker for the length of a turn and starve everything genuinely
  fire-and-forget. Its thread count is already bounded by gunicorn's.

Everything else goes through `utils/thread_pool.submit_background`, which also
carries the caller's tenant context — a raw thread does not, so background work
started that way reads and writes nothing and says nothing about it.

## C10 — A tool result says whether it happened

A brain tool (`app/brain/tools_*.py`) returns a dict the model reads as JSON:

- `ok` — the change the user asked for actually happened. A refusal, a not-found
  target of a change, a failed write, an input it gave up on: `ok: False`, with
  `error` saying why, and `reply` when there is a sentence the user should hear.
- `broke` — the tool itself raised (`tools.execute` catches it and says so). A
  refusal is not breakage: it ran, and the answer is no.
- `needs_confirmation` / `needs_choice` — the tool will not act without a yes, or
  without being told which row. The loop holds the call and asks; this is the flow
  continuing, not a failure.

A read or search that legitimately found nothing is `ok: True` with no rows; the
request took effect.

Never write a success sentence without `ok`. The voice path marks everything that
did not happen (`brain/voice.py::_tagged`), because an unmarked refusal is what
Gemini reads as success and confirms to the user — and it marks them differently:
`[فشل التنفيذ]` for breakage, `[لم يُنفَّذ]` for a refusal. Calling «ما لقيت
جهاز بهالاسم، أي واحد تقصد؟» a failed execution makes her abandon a
disambiguation the user is halfway through.
