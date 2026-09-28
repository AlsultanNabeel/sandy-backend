# cloud/ file justification

Scope: cloud/ only (ios/, firmware/, room-node/, vision-core/ come in later sessions).
`agent/` was not cleaned: it is scheduled for a full rewrite. Only edits forced by merges
elsewhere touched it (imports of the merged utils/session.py and utils/stm_config.py, and
a dropped unused `mongo_db` argument at two `resolve_display_name` call sites).

Totals (.py files in cloud/): 41381 lines before → 35504 after.

file | lines before | lines after | what it does | verdict
---|---|---|---|---
cloud/app/__init__.py | 0 | 0 | package marker | KEEP
cloud/app/agent/__init__.py | 0 | 0 | package marker | SKIPPED: scheduled for rewrite
cloud/app/agent/agents/__init__.py | 8 | 8 | package docstring only | SKIPPED: scheduled for rewrite
cloud/app/agent/agents/fc_router.py | 400 | 400 | function-calling router, picks tools | SKIPPED: scheduled for rewrite
cloud/app/agent/anomaly_detector.py | 59 | 59 | late-night habit anomaly context | SKIPPED: scheduled for rewrite
cloud/app/agent/command_rules.py | 20 | 20 | shared disambiguation prompt text | SKIPPED: scheduled for rewrite
cloud/app/agent/conflict_resolution.py | 354 | 354 | same-day task clash check | SKIPPED: scheduled for rewrite
cloud/app/agent/context_builder.py | 591 | 591 | builds prompt context block | SKIPPED: scheduled for rewrite
cloud/app/agent/deep_context.py | 88 | 88 | recent search results buffer | SKIPPED: scheduled for rewrite
cloud/app/agent/dreams_engine.py | 54 | 54 | goal-deadline reminders in prompt | SKIPPED: scheduled for rewrite
cloud/app/agent/emotional_ltm.py | 103 | 103 | long-term emotional memory | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/__init__.py | 9 | 9 | executor public exports | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/deps.py | 24 | 24 | store re-exports (test patch seam) | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/dispatch.py | 338 | 338 | operational action dispatch | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/helpers.py | 242 | 242 | confirm/cancel text helpers | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/pending/__init__.py | 0 | 0 | package marker | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/pending/dispatch.py | 251 | 251 | routes pending confirmations | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/pending/reminder_pending.py | 171 | 171 | reminder pending confirmation | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/pending/task_pending/__init__.py | 46 | 46 | re-exports task pending handlers | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/pending/task_pending/executors.py | 432 | 432 | apply confirmed task actions | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/pending/task_pending/handlers.py | 434 | 434 | task clarification handlers | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/pending_execution.py | 3 | 3 | backward-compat import shim | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/reminder_handlers.py | 483 | 483 | reminder action handlers | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/__init__.py | 8 | 8 | package public export | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/_common.py | 38 | 38 | shared ambiguous-choice reply | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/_now.py | 91 | 91 | run confirmed action immediately | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/completion.py | 304 | 304 | task complete handlers | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/creation.py | 153 | 153 | task create handlers | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/deletion.py | 203 | 203 | task delete handlers | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/dispatch.py | 303 | 303 | routes task actions | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/due_date.py | 546 | 546 | task due-date handlers | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/listing.py | 67 | 67 | task list handlers | SKIPPED: scheduled for rewrite
cloud/app/agent/executor/task_handlers/notes.py | 223 | 223 | task notes handlers | SKIPPED: scheduled for rewrite
cloud/app/agent/facade/__init__.py | 1 | 1 | package marker | SKIPPED: scheduled for rewrite
cloud/app/agent/facade/agent.py | 181 | 181 | agent runtime wiring | SKIPPED: scheduled for rewrite
cloud/app/agent/facade/briefing.py | 163 | 163 | daily briefing text | SKIPPED: scheduled for rewrite
cloud/app/agent/fast_path.py | 303 | 303 | model-free device command route | SKIPPED: scheduled for rewrite
cloud/app/agent/future_messages.py | 149 | 149 | scheduled messages to future self | SKIPPED: scheduled for rewrite
cloud/app/agent/graph/__init__.py | 0 | 0 | package marker | SKIPPED: scheduled for rewrite
cloud/app/agent/graph/graph.py | 697 | 697 | agent pipeline runner | SKIPPED: scheduled for rewrite
cloud/app/agent/graph/response_templates.py | 95 | 95 | reply templates by intent | SKIPPED: scheduled for rewrite
cloud/app/agent/graph/state.py | 133 | 150 | pipeline state TypedDict | SKIPPED: scheduled for rewrite
cloud/app/agent/guards.py | 38 | 38 | destructive tool set | SKIPPED: scheduled for rewrite
cloud/app/agent/guest_usage.py | 143 | 143 | guest rate limiting | SKIPPED: scheduled for rewrite
cloud/app/agent/health_monitor.py | 178 | 178 | late-night pattern tracking | SKIPPED: scheduled for rewrite
cloud/app/agent/interests_tracker.py | 129 | 129 | tracks user interest topics | SKIPPED: scheduled for rewrite
cloud/app/agent/lessons_memory.py | 95 | 95 | lessons-learned memory | SKIPPED: scheduled for rewrite
cloud/app/agent/life_snapshot.py | 325 | 325 | user facts summary block | SKIPPED: scheduled for rewrite
cloud/app/agent/ltm_crypto.py | 83 | 83 | encrypts sensitive memory fields | SKIPPED: scheduled for rewrite
cloud/app/agent/memory.py | 83 | 83 | legacy per-tenant memory doc | SKIPPED: scheduled for rewrite
cloud/app/agent/model_fallback.py | 106 | 106 | fallback models on API failure | SKIPPED: scheduled for rewrite
cloud/app/agent/nodes/__init__.py | 0 | 0 | package marker | SKIPPED: scheduled for rewrite
cloud/app/agent/nodes/clarify.py | 63 | 63 | clarifying question node | SKIPPED: scheduled for rewrite
cloud/app/agent/nodes/execute.py | 495 | 495 | tool execution node | SKIPPED: scheduled for rewrite
cloud/app/agent/nodes/pending.py | 184 | 184 | pending action node | SKIPPED: scheduled for rewrite
cloud/app/agent/nodes/response.py | 110 | 110 | final reply node | SKIPPED: scheduled for rewrite
cloud/app/agent/nodes/router.py | 85 | 85 | next-node picker | SKIPPED: scheduled for rewrite
cloud/app/agent/nodes/soul.py | 557 | 557 | persona/emotion injection node | SKIPPED: scheduled for rewrite
cloud/app/agent/pending.py | 79 | 79 | pending action builder | SKIPPED: scheduled for rewrite
cloud/app/agent/pending_store.py | 72 | 72 | per-conversation pending persistence | SKIPPED: scheduled for rewrite
cloud/app/agent/proactive_comfort.py | 102 | 102 | comfort message when tired | SKIPPED: scheduled for rewrite
cloud/app/agent/proactive_goals.py | 50 | 50 | stale goal follow-up prompt | SKIPPED: scheduled for rewrite
cloud/app/agent/relationships_memory.py | 127 | 127 | remembers relationship names | SKIPPED: scheduled for rewrite
cloud/app/agent/semantic_memory.py | 552 | 552 | embedding-based long-term memory | SKIPPED: scheduled for rewrite
cloud/app/agent/session_state.py | 63 | 63 | cross-channel session state | SKIPPED: scheduled for rewrite
cloud/app/agent/shared_history.py | 155 | 155 | milestones with dates | SKIPPED: scheduled for rewrite
cloud/app/agent/soul_vault.py | 158 | 158 | persona manager | SKIPPED: scheduled for rewrite
cloud/app/agent/style_memory.py | 69 | 69 | user style preferences memory | SKIPPED: scheduled for rewrite
cloud/app/agent/tool_health.py | 117 | 117 | per-tool failure tracker | SKIPPED: scheduled for rewrite
cloud/app/agent/tool_result.py | 76 | 76 | handled/ok/error result contract | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/__init__.py | 10 | 10 | tools public exports | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/dispatcher.py | 219 | 219 | runs tool calls | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/registry.py | 134 | 134 | tool registry | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/__init__.py | 0 | 0 | package marker | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/brainstorm_tools.py | 261 | 261 | brainstorm/plan tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/content_share_tools.py | 66 | 66 | content suggestion tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/device_tools.py | 168 | 168 | device control tool | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/future_message_tools.py | 94 | 94 | future message tool | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/gift_tools.py | 160 | 160 | digital gifts tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/goal_tools.py | 149 | 149 | goal tracking tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/life_tools/__init__.py | 422 | 422 | life tools registration | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/life_tools/books.py | 180 | 180 | books tool adapters | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/life_tools/expenses.py | 40 | 40 | expenses tool adapters | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/life_tools/focus.py | 119 | 119 | focus tool adapters | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/life_tools/habits.py | 51 | 51 | habits tool adapters | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/life_tools/journal.py | 45 | 45 | journal tool adapters | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/life_tools/scenes.py | 72 | 72 | scenes tool adapters | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/life_tools/shopping.py | 60 | 60 | shopping tool adapters | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/mcp_tools.py | 257 | 257 | memory + web fetch tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/meta_tools.py | 102 | 102 | routing meta-tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/other_tools.py | 145 | 145 | research/image/utility tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/photo_tools.py | 220 | 220 | photo album tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/reminder_tools.py | 101 | 101 | reminder tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/self_awareness_tools.py | 133 | 133 | capabilities report tool | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/schemas/task_tools.py | 286 | 286 | task tools | SKIPPED: scheduled for rewrite
cloud/app/agent/tools/setup.py | 60 | 60 | registers all tools | SKIPPED: scheduled for rewrite
cloud/app/api/__init__.py | 0 | 0 | package marker | KEEP
cloud/app/api/account_api.py | 105 | 74 | account get/reset/delete routes | KEEP
cloud/app/api/auth_handlers.py | 234 | 182 | JWT auth helpers | KEEP
cloud/app/api/conversations_api.py | 528 | 472 | chat conversations routes | KEEP
cloud/app/api/daily_nudge_api.py | 233 | 206 | daily nudge routes | KEEP
cloud/app/api/devices_api.py | 747 | 579 | devices/nodes/camera routes | KEEP
cloud/app/api/email_auth_api.py | 114 | 94 | email register/login routes | KEEP
cloud/app/api/features_api.py | 35 | 24 | feature visibility route | KEEP
cloud/app/api/firmware_api.py | 100 | 93 | firmware OTA routes | KEEP
cloud/app/api/future_messages_api.py | 120 | 109 | future messages routes | ASK OWNER (with future_messages)
cloud/app/api/gifts_api.py | 159 | 126 | gifts routes | ASK OWNER (with gift_tools)
cloud/app/api/goals_api.py | 151 | 137 | goals routes | KEEP
cloud/app/api/insights_api.py | 53 | 45 | weekly insights route | KEEP
cloud/app/api/life_api/__init__.py | 19 | — | registers life routes | MERGED INTO api/life_api.py
cloud/app/api/life_api/_common.py | 69 | — | life routes shared helpers | MERGED INTO api/life_api.py
cloud/app/api/life_api/books.py | 101 | — | books routes | MERGED INTO api/life_api.py
cloud/app/api/life_api/expenses.py | 64 | — | expenses routes | MERGED INTO api/life_api.py
cloud/app/api/life_api/habits.py | 70 | — | habits routes | MERGED INTO api/life_api.py
cloud/app/api/life_api/journal.py | 53 | — | journal routes | MERGED INTO api/life_api.py
cloud/app/api/life_api/scenes.py | 117 | — | scenes/focus routes | MERGED INTO api/life_api.py
cloud/app/api/life_api/shopping.py | 72 | — | shopping routes | MERGED INTO api/life_api.py
cloud/app/api/memory_api.py | 147 | 125 | user memory view routes | KEEP
cloud/app/api/metering.py | 61 | 47 | per-account paid-route quota | KEEP
cloud/app/api/onboarding_api.py | 82 | 66 | onboarding routes | KEEP
cloud/app/api/persona_api.py | 68 | 60 | persona customization routes | KEEP
cloud/app/api/photos_api.py | 262 | 217 | photo album routes | KEEP
cloud/app/api/productivity_api.py | 235 | 213 | reminders/tasks routes | KEEP
cloud/app/api/push_api.py | 41 | 34 | push token routes | KEEP
cloud/app/api/research_api.py | 95 | 81 | web/place search routes | KEEP
cloud/app/api/server.py | 750 | 631 | Flask app, chat/image routes | KEEP
cloud/app/api/share_api.py | 163 | 138 | content share routes | ASK OWNER (with content_share_tools)
cloud/app/api/social_auth_api.py | 285 | 225 | Google/Apple sign-in routes | KEEP
cloud/app/api/studio_api.py | 212 | 198 | brainstorm plans routes | KEEP
cloud/app/api/subscriptions_api.py | 160 | 135 | RevenueCat subscription routes | KEEP
cloud/app/api/timeline_api.py | 101 | 87 | unified activity timeline route | ASK OWNER
cloud/app/api/voice_api.py | 38 | 30 | TTS route | KEEP
cloud/app/api/voice_ws/__init__.py | 7 | 4 | voice WS export | KEEP
cloud/app/api/voice_ws/_config.py | 295 | 177 | voice WS constants | KEEP
cloud/app/api/voice_ws/memory.py | 314 | 204 | voice STM/identity memory | KEEP (tests patch it)
cloud/app/api/voice_ws/session.py | 1789 | 1280 | voice WebSocket session loop | KEEP
cloud/app/api/voice_ws/speaker.py | 116 | 98 | voice speaker identification | KEEP (tests patch it)
cloud/app/api/voice_ws/tools.py | 691 | 477 | voice tools + system prompt | KEEP
cloud/app/api/weather_api.py | 55 | 32 | weather route | KEEP
cloud/app/bootstrap.py | 335 | 271 | startup: indexes, schedulers | KEEP
cloud/app/config.py | 283 | 187 | central env config | KEEP
cloud/app/db.py | 44 | 23 | single Mongo handle | KEEP
cloud/app/errors.py | 89 | 69 | typed error classes | KEEP (unused Auth/Forbidden/NotFound/RateLimit classes are covered by tests; left)
cloud/app/features/__init__.py | 0 | 0 | package marker | KEEP
cloud/app/features/account_delete.py | 279 | 196 | erase a user completely | KEEP
cloud/app/features/brainstorm.py | 415 | 360 | brainstorm/plans store | KEEP
cloud/app/features/broker_creds.py | 123 | 83 | per-board MQTT credentials | KEEP
cloud/app/features/device_keys.py | 153 | 113 | per-board voice keys | KEEP
cloud/app/features/device_store.py | 470 | 387 | device registry store | KEEP
cloud/app/features/expenses_store.py | 144 | 127 | expenses store | KEEP
cloud/app/features/firmware_store.py | 215 | 180 | firmware releases store | KEEP
cloud/app/features/focus_store.py | 429 | 383 | focus/pomodoro store | KEEP
cloud/app/features/google_places.py | 154 | 140 | Google Places search | KEEP
cloud/app/features/habits_store.py | 238 | 211 | habits store | KEEP
cloud/app/features/image_agent.py | 324 | 277 | image generate/edit flow | KEEP
cloud/app/features/image_planner.py | 202 | 189 | LLM image action planner | KEEP
cloud/app/features/insights.py | 401 | 377 | weekly insights compute | KEEP
cloud/app/features/journal_store.py | 116 | 105 | journal store | KEEP
cloud/app/features/node_provision.py | 383 | 271 | node outputs to devices | KEEP
cloud/app/features/node_store.py | 682 | 451 | paired nodes registry | KEEP
cloud/app/features/pair_presence.py | 106 | 94 | pairing proof of presence | KEEP
cloud/app/features/photo_album.py | 279 | 257 | photo album store | KEEP
cloud/app/features/push_tokens_store.py | 121 | 98 | push tokens store | KEEP
cloud/app/features/reading_store.py | 574 | 522 | books/reading sessions store | KEEP
cloud/app/features/reminders_store.py | 422 | 361 | reminders store | KEEP
cloud/app/features/research.py | 289 | 285 | web research orchestration | KEEP
cloud/app/features/research_formatter.py | 168 | 163 | research results to Arabic | KEEP
cloud/app/features/research_intent.py | 287 | — | research query classification | MERGED INTO research.py (only is_research_followup_request was used; the rest was test-only keyword matching)
cloud/app/features/research_pipeline.py | 429 | 416 | research extract/dedup/rank | KEEP
cloud/app/features/robot_expression.py | 123 | 78 | robot face/LED expressions | KEEP
cloud/app/features/scene_store.py | 428 | 366 | room scenes store | KEEP
cloud/app/features/screen_sender.py | 140 | 89 | send text/image to display | KEEP
cloud/app/features/shopping_store.py | 229 | 218 | shopping list store | KEEP
cloud/app/features/speaker_id.py | 339 | 287 | speaker voice verification | KEEP
cloud/app/features/tasks_formatter.py | 178 | 147 | task display formatting | KEEP
cloud/app/features/tasks_matcher.py | 427 | 420 | resolve task references | KEEP
cloud/app/features/tasks_store.py | 543 | 500 | tasks store | KEEP
cloud/app/features/time_parser.py | 159 | 149 | LLM time expression parser | KEEP
cloud/app/features/usage_store.py | 85 | 74 | usage metering store | KEEP
cloud/app/features/users_store.py | 422 | 354 | user accounts store | KEEP
cloud/app/features/vision.py | 120 | 122 | image gen/edit provider chain | KEEP
cloud/app/features/weather.py | 94 | 94 | weather fetch | KEEP
cloud/app/features/wifi_switch.py | 82 | 61 | move board to new Wi-Fi | KEEP
cloud/app/integrations/__init__.py | 0 | 0 | package marker | KEEP
cloud/app/integrations/azure_flux.py | 187 | 86 | Azure FLUX image adapter | KEEP
cloud/app/integrations/azure_image.py | 133 | 119 | Azure DALL-E/gpt-image fallback | ASK OWNER
cloud/app/integrations/azure_intent_client.py | 373 | 235 | Azure OpenAI routing client | KEEP
cloud/app/integrations/bedrock_router.py | 100 | 91 | optional Bedrock router backend | ASK OWNER
cloud/app/integrations/camera_client.py | 257 | 181 | robot camera photo requests | KEEP
cloud/app/integrations/error_tracking.py | 210 | 132 | Sentry error tracking | KEEP
cloud/app/integrations/exa_client.py | 104 | 100 | Exa web search client | KEEP
cloud/app/integrations/gemini_router.py | 114 | 96 | optional Gemini router backend | ASK OWNER
cloud/app/integrations/gemini_tts.py | 153 | 136 | Gemini text-to-speech | KEEP
cloud/app/integrations/mongodb_store.py | 108 | 63 | MongoDB connection setup | KEEP
cloud/app/integrations/mqtt_ingest.py | 656 | 413 | inbound MQTT listener | KEEP
cloud/app/integrations/openai_client.py | 118 | 107 | OpenAI chat client | KEEP
cloud/app/integrations/room_device.py | 363 | 252 | room node MQTT control | KEEP
cloud/app/services/__init__.py | 1 | 0 | package marker | KEEP
cloud/app/services/apns.py | 147 | 126 | Apple push sender | KEEP
cloud/app/services/nudge_scheduler.py | 118 | 108 | daily nudge scheduler | KEEP
cloud/app/services/scene_timer_runner.py | 72 | 60 | scene timed revert runner | KEEP
cloud/app/utils/__init__.py | 0 | 0 | package marker | KEEP
cloud/app/utils/arabic_days.py | 305 | 217 | Arabic day-name mapping | KEEP
cloud/app/utils/circuit_breaker.py | 141 | 112 | circuit breaker | KEEP
cloud/app/utils/nlp_normalizer.py | 23 | 16 | normalize user message text | KEEP
cloud/app/utils/process_leader.py | 81 | 50 | single-process job leader lock | KEEP
cloud/app/utils/prompt_prewarm.py | 129 | 100 | prebuild voice instructions | KEEP
cloud/app/utils/session.py | 21 | — | build session from state | MERGED INTO agent/graph/state.py
cloud/app/utils/stm_config.py | 9 | — | STM size/TTL constants | MERGED INTO agent/graph/graph.py
cloud/app/utils/tenant_db.py | 353 | 235 | tenant isolation boundary | KEEP
cloud/app/utils/tenant_version.py | 227 | 132 | per-tenant change counter | KEEP
cloud/app/utils/text_query.py | 41 | 19 | safe regex text queries | KEEP
cloud/app/utils/thread_pool.py | 91 | 58 | background thread pool | KEEP
cloud/app/utils/time.py | 5 | 5 | user timezone constant | KEEP (tests import it)
cloud/app/utils/time_awareness.py | 161 | 139 | time-of-day prompt lines | KEEP
cloud/app/utils/user_profiles.py | 238 | 168 | resolve current user identity | KEEP
cloud/serve_api.py | 52 | 37 | local dev server | KEEP
cloud/wsgi.py | 40 | 23 | production WSGI entrypoint | KEEP

cloud/app/api/life_api.py | — | 491 | new (merge target) | KEEP

## ASK OWNER

Working features that may not be worth keeping. Nothing here was removed.

- `integrations/bedrock_router.py` + `integrations/gemini_router.py` — opt-in alternative router backends (env-gated). Lose: the ability to route through Bedrock/Gemini instead of Azure.
- `integrations/azure_image.py` — DALL-E / gpt-image-1 fallback when FLUX fails. Lose: image generation/editing when FLUX is down.
- `api/future_messages_api.py` (+ agent/future_messages.py, future_message_tools.py) — messages to your future self. Lose: that feature in app and chat.
- `api/gifts_api.py` (+ gift_tools.py) — AI-written "digital gifts" (poems, jokes...). Lose: the gifts screen and tool.
- `api/share_api.py` (+ content_share_tools.py, agent/interests_tracker.py) — interest-based content cards. Lose: the share/suggest screen.
- `api/timeline_api.py` — unified activity timeline. Lose: the timeline screen (data stays in each store).
- For the agent rewrite, experimental persona memory modules: anomaly_detector, dreams_engine, emotional_ltm, health_monitor, lessons_memory, proactive_comfort, proactive_goals, relationships_memory, shared_history, style_memory. Lose: the extra "she remembers/notices" prompt context each adds.
