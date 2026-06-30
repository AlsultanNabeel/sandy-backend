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
