# cloud/ file justification

Lines are before cleanup. Scope: cloud/ only (ios/, firmware/, room-node/, vision-core/ come in later sessions).

file | lines | what it does | verdict
---|---|---|---
cloud/app/__init__.py | 0 | package marker | KEEP
cloud/app/agent/__init__.py | 0 | package marker | KEEP
cloud/app/agent/agents/__init__.py | 8 | package docstring only | KEEP (docstring shrunk)
cloud/app/agent/agents/fc_router.py | 400 | function-calling router, picks tools | KEEP
cloud/app/agent/anomaly_detector.py | 59 | late-night habit anomaly context | ASK OWNER
cloud/app/agent/command_rules.py | 20 | shared disambiguation prompt text | KEEP (shared by text+voice)
cloud/app/agent/conflict_resolution.py | 354 | same-day task clash check | KEEP
cloud/app/agent/context_builder.py | 591 | builds prompt context block | KEEP
cloud/app/agent/deep_context.py | 88 | recent search results buffer | KEEP
cloud/app/agent/dreams_engine.py | 54 | goal-deadline reminders in prompt | ASK OWNER
cloud/app/agent/emotional_ltm.py | 103 | long-term emotional memory | ASK OWNER
cloud/app/agent/executor/__init__.py | 9 | executor public exports | KEEP
cloud/app/agent/executor/deps.py | 24 | store re-exports (test patch seam) | KEEP (tests patch it)
cloud/app/agent/executor/dispatch.py | 338 | operational action dispatch | KEEP
cloud/app/agent/executor/helpers.py | 242 | confirm/cancel text helpers | KEEP
cloud/app/agent/executor/pending/__init__.py | 0 | package marker | KEEP
cloud/app/agent/executor/pending/dispatch.py | 251 | routes pending confirmations | KEEP
cloud/app/agent/executor/pending/reminder_pending.py | 171 | reminder pending confirmation | KEEP
cloud/app/agent/executor/pending/task_pending/__init__.py | 46 | re-exports task pending handlers | KEEP
cloud/app/agent/executor/pending/task_pending/executors.py | 432 | apply confirmed task actions | KEEP
cloud/app/agent/executor/pending/task_pending/handlers.py | 434 | task clarification handlers | KEEP
cloud/app/agent/executor/pending_execution.py | 3 | backward-compat import shim | DELETE (point importers at pending/dispatch.py)
cloud/app/agent/executor/reminder_handlers.py | 483 | reminder action handlers | KEEP
cloud/app/agent/executor/task_handlers/__init__.py | 8 | package public export | KEEP
cloud/app/agent/executor/task_handlers/_common.py | 38 | shared ambiguous-choice reply | KEEP (tiny, 4 users)
cloud/app/agent/executor/task_handlers/_now.py | 91 | run confirmed action immediately | KEEP (test reads its source)
cloud/app/agent/executor/task_handlers/completion.py | 304 | task complete handlers | KEEP
cloud/app/agent/executor/task_handlers/creation.py | 153 | task create handlers | KEEP
cloud/app/agent/executor/task_handlers/deletion.py | 203 | task delete handlers | KEEP
cloud/app/agent/executor/task_handlers/dispatch.py | 303 | routes task actions | KEEP
cloud/app/agent/executor/task_handlers/due_date.py | 546 | task due-date handlers | KEEP
cloud/app/agent/executor/task_handlers/listing.py | 67 | task list handlers | KEEP (tests patch it)
cloud/app/agent/executor/task_handlers/notes.py | 223 | task notes handlers | KEEP
cloud/app/agent/facade/__init__.py | 1 | package marker | KEEP
cloud/app/agent/facade/agent.py | 181 | agent runtime wiring | KEEP
cloud/app/agent/facade/briefing.py | 163 | daily briefing text | KEEP
cloud/app/agent/fast_path.py | 303 | model-free device command route | KEEP
cloud/app/agent/future_messages.py | 149 | scheduled messages to future self | ASK OWNER
cloud/app/agent/graph/__init__.py | 0 | package marker | KEEP
cloud/app/agent/graph/graph.py | 697 | agent pipeline runner | KEEP
cloud/app/agent/graph/response_templates.py | 95 | reply templates by intent | KEEP
cloud/app/agent/graph/state.py | 133 | pipeline state TypedDict | KEEP
cloud/app/agent/guards.py | 38 | destructive tool set | KEEP
cloud/app/agent/guest_usage.py | 143 | guest rate limiting | KEEP
cloud/app/agent/health_monitor.py | 178 | late-night pattern tracking | ASK OWNER
cloud/app/agent/interests_tracker.py | 129 | tracks user interest topics | ASK OWNER
cloud/app/agent/lessons_memory.py | 95 | lessons-learned memory | ASK OWNER
cloud/app/agent/life_snapshot.py | 325 | user facts summary block | KEEP
cloud/app/agent/ltm_crypto.py | 83 | encrypts sensitive memory fields | KEEP
cloud/app/agent/memory.py | 83 | legacy per-tenant memory doc | DELETE (only a test uses it)
cloud/app/agent/model_fallback.py | 106 | fallback models on API failure | KEEP
cloud/app/agent/nodes/__init__.py | 0 | package marker | KEEP
cloud/app/agent/nodes/clarify.py | 63 | clarifying question node | KEEP
cloud/app/agent/nodes/execute.py | 495 | tool execution node | KEEP
cloud/app/agent/nodes/pending.py | 184 | pending action node | KEEP
cloud/app/agent/nodes/response.py | 110 | final reply node | KEEP
cloud/app/agent/nodes/router.py | 85 | next-node picker | KEEP
cloud/app/agent/nodes/soul.py | 557 | persona/emotion injection node | KEEP
cloud/app/agent/pending.py | 79 | pending action builder | KEEP
cloud/app/agent/pending_store.py | 72 | per-conversation pending persistence | KEEP
cloud/app/agent/proactive_comfort.py | 102 | comfort message when tired | ASK OWNER
cloud/app/agent/proactive_goals.py | 50 | stale goal follow-up prompt | ASK OWNER
cloud/app/agent/relationships_memory.py | 127 | remembers relationship names | ASK OWNER
cloud/app/agent/semantic_memory.py | 552 | embedding-based long-term memory | KEEP
cloud/app/agent/session_state.py | 63 | cross-channel session state | KEEP
cloud/app/agent/shared_history.py | 155 | milestones with dates | ASK OWNER
cloud/app/agent/soul_vault.py | 158 | persona manager | KEEP
cloud/app/agent/style_memory.py | 69 | user style preferences memory | ASK OWNER
cloud/app/agent/tool_health.py | 117 | per-tool failure tracker | KEEP
cloud/app/agent/tool_result.py | 76 | handled/ok/error result contract | KEEP
cloud/app/agent/tools/__init__.py | 10 | tools public exports | KEEP
cloud/app/agent/tools/dispatcher.py | 219 | runs tool calls | KEEP
cloud/app/agent/tools/registry.py | 134 | tool registry | KEEP
cloud/app/agent/tools/schemas/__init__.py | 0 | package marker | KEEP
cloud/app/agent/tools/schemas/brainstorm_tools.py | 261 | brainstorm/plan tools | KEEP
cloud/app/agent/tools/schemas/content_share_tools.py | 66 | content suggestion tools | ASK OWNER
cloud/app/agent/tools/schemas/device_tools.py | 168 | device control tool | KEEP
cloud/app/agent/tools/schemas/future_message_tools.py | 94 | future message tool | ASK OWNER (with future_messages)
cloud/app/agent/tools/schemas/gift_tools.py | 160 | digital gifts tools | ASK OWNER
cloud/app/agent/tools/schemas/goal_tools.py | 149 | goal tracking tools | KEEP
cloud/app/agent/tools/schemas/life_tools/__init__.py | 422 | life tools registration | MERGE INTO life_tools.py
cloud/app/agent/tools/schemas/life_tools/books.py | 180 | books tool adapters | MERGE INTO life_tools.py
cloud/app/agent/tools/schemas/life_tools/expenses.py | 40 | expenses tool adapters | MERGE INTO life_tools.py
cloud/app/agent/tools/schemas/life_tools/focus.py | 119 | focus tool adapters | MERGE INTO life_tools.py
cloud/app/agent/tools/schemas/life_tools/habits.py | 51 | habits tool adapters | MERGE INTO life_tools.py
cloud/app/agent/tools/schemas/life_tools/journal.py | 45 | journal tool adapters | MERGE INTO life_tools.py
cloud/app/agent/tools/schemas/life_tools/scenes.py | 72 | scenes tool adapters | MERGE INTO life_tools.py
cloud/app/agent/tools/schemas/life_tools/shopping.py | 60 | shopping tool adapters | MERGE INTO life_tools.py
cloud/app/agent/tools/schemas/mcp_tools.py | 257 | memory + web fetch tools | KEEP
cloud/app/agent/tools/schemas/meta_tools.py | 102 | routing meta-tools | KEEP
cloud/app/agent/tools/schemas/other_tools.py | 145 | research/image/utility tools | KEEP
cloud/app/agent/tools/schemas/photo_tools.py | 220 | photo album tools | KEEP
cloud/app/agent/tools/schemas/reminder_tools.py | 101 | reminder tools | KEEP
cloud/app/agent/tools/schemas/self_awareness_tools.py | 133 | capabilities report tool | KEEP
cloud/app/agent/tools/schemas/task_tools.py | 286 | task tools | KEEP
cloud/app/agent/tools/setup.py | 60 | registers all tools | KEEP
cloud/app/api/__init__.py | 0 | package marker | KEEP
cloud/app/api/account_api.py | 105 | account get/reset/delete routes | KEEP
cloud/app/api/auth_handlers.py | 234 | JWT auth helpers | KEEP
cloud/app/api/conversations_api.py | 528 | chat conversations routes | KEEP
cloud/app/api/daily_nudge_api.py | 233 | daily nudge routes | KEEP
cloud/app/api/devices_api.py | 747 | devices/nodes/camera routes | KEEP
cloud/app/api/email_auth_api.py | 114 | email register/login routes | KEEP
cloud/app/api/features_api.py | 35 | feature visibility route | KEEP
cloud/app/api/firmware_api.py | 100 | firmware OTA routes | KEEP
cloud/app/api/future_messages_api.py | 120 | future messages routes | ASK OWNER (with future_messages)
cloud/app/api/gifts_api.py | 159 | gifts routes | ASK OWNER (with gift_tools)
cloud/app/api/goals_api.py | 151 | goals routes | KEEP
cloud/app/api/insights_api.py | 53 | weekly insights route | KEEP
cloud/app/api/life_api/__init__.py | 19 | registers life routes | MERGE INTO api/life_api.py
cloud/app/api/life_api/_common.py | 69 | life routes shared helpers | MERGE INTO api/life_api.py
cloud/app/api/life_api/books.py | 101 | books routes | MERGE INTO api/life_api.py
cloud/app/api/life_api/expenses.py | 64 | expenses routes | MERGE INTO api/life_api.py
cloud/app/api/life_api/habits.py | 70 | habits routes | MERGE INTO api/life_api.py
cloud/app/api/life_api/journal.py | 53 | journal routes | MERGE INTO api/life_api.py
cloud/app/api/life_api/scenes.py | 117 | scenes/focus routes | MERGE INTO api/life_api.py
cloud/app/api/life_api/shopping.py | 72 | shopping routes | MERGE INTO api/life_api.py
cloud/app/api/memory_api.py | 147 | user memory view routes | KEEP
cloud/app/api/metering.py | 61 | per-account paid-route quota | KEEP
cloud/app/api/onboarding_api.py | 82 | onboarding routes | KEEP
cloud/app/api/persona_api.py | 68 | persona customization routes | KEEP
cloud/app/api/photos_api.py | 262 | photo album routes | KEEP
cloud/app/api/productivity_api.py | 235 | reminders/tasks routes | KEEP
cloud/app/api/push_api.py | 41 | push token routes | KEEP
cloud/app/api/research_api.py | 95 | web/place search routes | KEEP
cloud/app/api/server.py | 750 | Flask app, chat/image routes | KEEP
cloud/app/api/share_api.py | 163 | content share routes | ASK OWNER (with content_share_tools)
cloud/app/api/social_auth_api.py | 285 | Google/Apple sign-in routes | KEEP
cloud/app/api/studio_api.py | 212 | brainstorm plans routes | KEEP
cloud/app/api/subscriptions_api.py | 160 | RevenueCat subscription routes | KEEP
cloud/app/api/timeline_api.py | 101 | unified activity timeline route | ASK OWNER
cloud/app/api/voice_api.py | 38 | TTS route | KEEP
cloud/app/api/voice_ws/__init__.py | 7 | voice WS export | KEEP
cloud/app/api/voice_ws/_config.py | 295 | voice WS constants | KEEP
cloud/app/api/voice_ws/memory.py | 314 | voice STM/identity memory | KEEP (tests patch it)
cloud/app/api/voice_ws/session.py | 1789 | voice WebSocket session loop | KEEP
cloud/app/api/voice_ws/speaker.py | 116 | voice speaker identification | KEEP (tests patch it)
cloud/app/api/voice_ws/tools.py | 691 | voice tools + system prompt | KEEP
cloud/app/api/weather_api.py | 55 | weather route | KEEP
cloud/app/bootstrap.py | 335 | startup: indexes, schedulers | KEEP
cloud/app/config.py | 283 | central env config | KEEP
cloud/app/db.py | 44 | single Mongo handle | KEEP
cloud/app/errors.py | 89 | typed error classes | KEEP (unused classes removed)
cloud/app/features/__init__.py | 0 | package marker | KEEP
cloud/app/features/account_delete.py | 279 | erase a user completely | KEEP
cloud/app/features/brainstorm.py | 415 | brainstorm/plans store | KEEP
cloud/app/features/broker_creds.py | 123 | per-board MQTT credentials | KEEP
cloud/app/features/device_keys.py | 153 | per-board voice keys | KEEP
cloud/app/features/device_store.py | 470 | device registry store | KEEP
cloud/app/features/expenses_store.py | 144 | expenses store | KEEP
cloud/app/features/firmware_store.py | 215 | firmware releases store | KEEP
cloud/app/features/focus_store.py | 429 | focus/pomodoro store | KEEP
cloud/app/features/google_places.py | 154 | Google Places search | KEEP
cloud/app/features/habits_store.py | 238 | habits store | KEEP
cloud/app/features/image_agent.py | 324 | image generate/edit flow | KEEP
cloud/app/features/image_planner.py | 202 | LLM image action planner | KEEP
cloud/app/features/insights.py | 401 | weekly insights compute | KEEP
cloud/app/features/journal_store.py | 116 | journal store | KEEP
cloud/app/features/node_provision.py | 383 | node outputs to devices | KEEP
cloud/app/features/node_store.py | 682 | paired nodes registry | KEEP
cloud/app/features/pair_presence.py | 106 | pairing proof of presence | KEEP
cloud/app/features/photo_album.py | 279 | photo album store | KEEP
cloud/app/features/push_tokens_store.py | 121 | push tokens store | KEEP
cloud/app/features/reading_store.py | 574 | books/reading sessions store | KEEP
cloud/app/features/reminders_store.py | 422 | reminders store | KEEP
cloud/app/features/research.py | 289 | web research orchestration | KEEP
cloud/app/features/research_formatter.py | 168 | research results to Arabic | KEEP
cloud/app/features/research_intent.py | 287 | research type/count detection | KEEP
cloud/app/features/research_pipeline.py | 429 | research extract/dedup/rank | KEEP
cloud/app/features/robot_expression.py | 123 | robot face/LED expressions | KEEP
cloud/app/features/scene_store.py | 428 | room scenes store | KEEP
cloud/app/features/screen_sender.py | 140 | send text/image to display | KEEP
cloud/app/features/shopping_store.py | 229 | shopping list store | KEEP
cloud/app/features/speaker_id.py | 339 | speaker voice verification | KEEP
cloud/app/features/tasks_formatter.py | 178 | task display formatting | KEEP
cloud/app/features/tasks_matcher.py | 427 | resolve task references | KEEP
cloud/app/features/tasks_store.py | 543 | tasks store | KEEP
cloud/app/features/time_parser.py | 159 | LLM time expression parser | KEEP
cloud/app/features/usage_store.py | 85 | usage metering store | KEEP
cloud/app/features/users_store.py | 422 | user accounts store | KEEP
cloud/app/features/vision.py | 120 | image gen/edit provider chain | KEEP
cloud/app/features/weather.py | 94 | weather fetch | KEEP
cloud/app/features/wifi_switch.py | 82 | move board to new Wi-Fi | KEEP
cloud/app/integrations/__init__.py | 0 | package marker | KEEP
cloud/app/integrations/azure_flux.py | 187 | Azure FLUX image adapter | KEEP
cloud/app/integrations/azure_image.py | 133 | Azure DALL-E/gpt-image fallback | ASK OWNER
cloud/app/integrations/azure_intent_client.py | 373 | Azure OpenAI routing client | KEEP
cloud/app/integrations/bedrock_router.py | 100 | optional Bedrock router backend | ASK OWNER
cloud/app/integrations/camera_client.py | 257 | robot camera photo requests | KEEP
cloud/app/integrations/error_tracking.py | 210 | Sentry error tracking | KEEP
cloud/app/integrations/exa_client.py | 104 | Exa web search client | KEEP
cloud/app/integrations/gemini_router.py | 114 | optional Gemini router backend | ASK OWNER
cloud/app/integrations/gemini_tts.py | 153 | Gemini text-to-speech | KEEP
cloud/app/integrations/mongodb_store.py | 108 | MongoDB connection setup | KEEP
cloud/app/integrations/mqtt_ingest.py | 656 | inbound MQTT listener | KEEP
cloud/app/integrations/openai_client.py | 118 | OpenAI chat client | KEEP
cloud/app/integrations/room_device.py | 363 | room node MQTT control | KEEP
cloud/app/services/__init__.py | 1 | package marker | KEEP
cloud/app/services/apns.py | 147 | Apple push sender | KEEP
cloud/app/services/nudge_scheduler.py | 118 | daily nudge scheduler | KEEP
cloud/app/services/scene_timer_runner.py | 72 | scene timed revert runner | KEEP
cloud/app/utils/__init__.py | 0 | package marker | KEEP
cloud/app/utils/arabic_days.py | 305 | Arabic day-name mapping | KEEP
cloud/app/utils/circuit_breaker.py | 141 | circuit breaker | KEEP
cloud/app/utils/nlp_normalizer.py | 23 | normalize user message text | KEEP
cloud/app/utils/process_leader.py | 81 | single-process job leader lock | KEEP
cloud/app/utils/prompt_prewarm.py | 129 | prebuild voice instructions | KEEP
cloud/app/utils/session.py | 21 | build session from state | MERGE INTO agent/graph/state.py
cloud/app/utils/stm_config.py | 9 | STM size/TTL constants | MERGE INTO agent/graph/graph.py
cloud/app/utils/tenant_db.py | 353 | tenant isolation boundary | KEEP
cloud/app/utils/tenant_version.py | 227 | per-tenant change counter | KEEP
cloud/app/utils/text_query.py | 41 | safe regex text queries | KEEP
cloud/app/utils/thread_pool.py | 91 | background thread pool | KEEP
cloud/app/utils/time.py | 5 | user timezone constant | KEEP (tests import it)
cloud/app/utils/time_awareness.py | 161 | time-of-day prompt lines | KEEP
cloud/app/utils/user_profiles.py | 238 | resolve current user identity | KEEP
cloud/serve_api.py | 52 | local dev server | KEEP
cloud/wsgi.py | 40 | production WSGI entrypoint | KEEP
