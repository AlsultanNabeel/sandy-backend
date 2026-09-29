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


---

# ios/ file justification

Scope: ios/ only, excluding `ios/SandyApp/Features/` and `ios/SandyApp/Localization/`
(scheduled for rewrite). Swift cannot be compiled here, so no ios file was moved,
merged or deleted and no code changed: only comments shrank. MERGE / DELETE verdicts
below are proposals for the owner to apply in Xcode.

Totals (.swift files in scope): 9735 lines before → 8483 after.

file | lines before | lines after | what it does | verdict
---|---|---|---|---
ios/README_RUN.md | 26 | 26 | build and run notes | KEEP
ios/SandyApp.xcodeproj/project.pbxproj | 941 | 941 | Xcode project, targets | KEEP
ios/SandyApp.xcodeproj/project.xcworkspace/contents.xcworkspacedata | 7 | 7 | Xcode workspace stub | KEEP
ios/SandyApp.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved | 78 | 78 | pinned Swift package versions | KEEP
ios/SandyApp.xcodeproj/xcshareddata/xcschemes/SandyApp.xcscheme | 29 | 29 | app build scheme | KEEP
ios/SandyApp.xcodeproj/xcshareddata/xcschemes/SandyShareExtension.xcscheme | 96 | 96 | share extension scheme | KEEP
ios/SandyApp.xcodeproj/xcshareddata/xcschemes/SandyWidgetExtension.xcscheme | 112 | 112 | widget extension scheme | KEEP
ios/SandyApp/App/AppState.swift | 237 | 183 | session, base URL, api | KEEP
ios/SandyApp/App/DeepLinkRouter.swift | 65 | 54 | handles sandy:// deep links | KEEP
ios/SandyApp/App/MainTabView.swift | 249 | 208 | tab shell and tab bar | KEEP
ios/SandyApp/App/SandyApp.swift | 148 | 130 | app entry, launch, delegate | KEEP
ios/SandyApp/Assets.xcassets/AccentColor.colorset/Contents.json | 11 | 11 | accent color asset | KEEP
ios/SandyApp/Assets.xcassets/AppIcon.appiconset/Contents.json | 37 | 37 | app icon manifest | KEEP
ios/SandyApp/Assets.xcassets/AppIcon.appiconset/SandyAppIcon-dark.png | 1093 | 1093 | dark app icon | KEEP
ios/SandyApp/Assets.xcassets/AppIcon.appiconset/SandyAppIcon-tinted.png | 561 | 561 | tinted app icon | KEEP
ios/SandyApp/Assets.xcassets/AppIcon.appiconset/SandyAppIcon.png | 941 | 941 | app icon | KEEP
ios/SandyApp/Assets.xcassets/Contents.json | 6 | 6 | asset catalog manifest | KEEP
ios/SandyApp/Assets.xcassets/LaunchBackground.colorset/Contents.json | 20 | 20 | launch screen color | KEEP
ios/SandyApp/Assets.xcassets/LaunchMark.imageset/Contents.json | 13 | 13 | launch mark manifest | KEEP
ios/SandyApp/Assets.xcassets/LaunchMark.imageset/LaunchMark@3x.png | 844 | 844 | launch screen image | KEEP
ios/SandyApp/Core/Auth/AuthView.swift | 276 | 236 | sign-in screen | KEEP
ios/SandyApp/Core/Auth/GoogleAuth.swift | 72 | 47 | Google sign-in flow | KEEP
ios/SandyApp/Core/Auth/Keychain.swift | 60 | 40 | token storage in Keychain | KEEP
ios/SandyApp/Core/Cache/CacheModels.swift | 140 | 138 | offline cache record types | KEEP
ios/SandyApp/Core/Cache/DiskCache.swift | 58 | 48 | JSON cache on disk | KEEP
ios/SandyApp/Core/Intents/AskSandyIntent.swift | 54 | 47 | Siri "ask Sandy" intent | KEEP
ios/SandyApp/Core/Intents/DeviceIntents.swift | 182 | 161 | Siri device control intents | ASK OWNER
ios/SandyApp/Core/Intents/SandyIntents.swift | 201 | 182 | Siri quick-add shortcuts | KEEP
ios/SandyApp/Core/Models/Models.swift | 446 | 381 | shared API model types | KEEP
ios/SandyApp/Core/Networking/APIClient+Auth.swift | 203 | 177 | auth/profile/onboarding endpoints | KEEP
ios/SandyApp/Core/Networking/APIClient+Books.swift | 155 | 145 | books endpoints | KEEP
ios/SandyApp/Core/Networking/APIClient+Chat.swift | 279 | 246 | chat/conversation endpoints | KEEP
ios/SandyApp/Core/Networking/APIClient+Content.swift | 226 | 216 | images/search/insights endpoints | KEEP
ios/SandyApp/Core/Networking/APIClient+Devices.swift | 355 | 299 | devices/nodes/scenes endpoints | KEEP
ios/SandyApp/Core/Networking/APIClient+FutureMessages.swift | 41 | 37 | future messages endpoints | KEEP (per-domain extension is the documented pattern)
ios/SandyApp/Core/Networking/APIClient+Gifts.swift | 69 | 66 | gifts endpoints | KEEP (per-domain extension is the documented pattern)
ios/SandyApp/Core/Networking/APIClient+Goals.swift | 62 | 56 | goals endpoints | KEEP (per-domain extension is the documented pattern)
ios/SandyApp/Core/Networking/APIClient+Life.swift | 178 | 170 | habits/expenses/journal endpoints | KEEP
ios/SandyApp/Core/Networking/APIClient+Photos.swift | 76 | 54 | photos endpoints | KEEP (per-domain extension is the documented pattern)
ios/SandyApp/Core/Networking/APIClient+Productivity.swift | 312 | 300 | tasks/reminders/focus endpoints | KEEP
ios/SandyApp/Core/Networking/APIClient+Projects.swift | 156 | 146 | projects endpoints | KEEP
ios/SandyApp/Core/Networking/APIClient+ShareContent.swift | 65 | 61 | shared content endpoints | KEEP (per-domain extension is the documented pattern)
ios/SandyApp/Core/Networking/APIClient+Shopping.swift | 75 | 70 | shopping endpoints | KEEP (per-domain extension is the documented pattern)
ios/SandyApp/Core/Networking/APIClient+Weather.swift | 34 | 33 | weather endpoint | KEEP (per-domain extension is the documented pattern)
ios/SandyApp/Core/Networking/APIClient.swift | 259 | 175 | HTTP client core, token | KEEP
ios/SandyApp/Core/Networking/APIClientProtocol.swift | 24 | 16 | unused mocking protocol | ASK OWNER (nothing uses it as a type; DELETE + drop conformance)
ios/SandyApp/Core/Networking/Backend.swift | 26 | 16 | server URL source | KEEP
ios/SandyApp/Core/Shared/SharedAuth.swift | 27 | 17 | base URL for extensions | MERGE INTO Core/Networking/Backend.swift
ios/SandyApp/Core/Spotlight/SpotlightIndexer.swift | 97 | 89 | index items into Spotlight | ASK OWNER
ios/SandyApp/Core/Spotlight/SpotlightRouter.swift | 37 | 32 | open tapped Spotlight results | MERGE INTO Core/Spotlight/SpotlightIndexer.swift
ios/SandyApp/Core/Stores/LoadableStore.swift | 103 | 79 | shared load/error state | KEEP
ios/SandyApp/DesignSystem/Board/BoardStore.swift | 111 | 86 | board card order persistence | KEEP
ios/SandyApp/DesignSystem/Board/CardBoard.swift | 399 | 373 | draggable resizable card board | KEEP
ios/SandyApp/DesignSystem/Board/CardMetrics.swift | 72 | 49 | card size environment values | MERGE INTO DesignSystem/Board/CardBoard.swift
ios/SandyApp/DesignSystem/Components.swift | 440 | 380 | shared UI components | KEEP (contains unused HubList, see report)
ios/SandyApp/DesignSystem/Haptics.swift | 55 | 42 | haptic feedback helpers | KEEP
ios/SandyApp/DesignSystem/OfflineBanner.swift | 25 | 24 | offline notice banner | MERGE INTO DesignSystem/Components.swift
ios/SandyApp/DesignSystem/Theme.swift | 304 | 244 | colors, fonts, glass styles | KEEP
ios/SandyApp/Info.plist | 59 | 54 | app Info.plist | KEEP
ios/SandyApp/PrivacyInfo.xcprivacy | 97 | 97 | App Store privacy manifest | KEEP
ios/SandyApp/SandyApp.entitlements | 16 | 12 | app entitlements | KEEP
ios/SandyApp/Services/GeminiLiveManager.swift | 541 | 475 | in-app live voice call | KEEP
ios/SandyApp/Services/NotificationManager.swift | 524 | 449 | local and push notifications | KEEP
ios/SandyApp/Services/SpeechManager.swift | 82 | 74 | reply audio playback | KEEP
ios/SandyApp/Services/SubscriptionManager.swift | 96 | 88 | StoreKit subscription state | KEEP
ios/SandyApp/Widgets/CallLiveActivity.swift | 71 | 63 | starts call Live Activity | KEEP
ios/SandyApp/Widgets/FocusLiveActivity.swift | 89 | 80 | starts focus Live Activity | KEEP
ios/SandyApp/Widgets/SandyCallAttributes.swift | 64 | 53 | call activity attributes (copy) | MERGE: byte-identical to SandyWidget/SandyCallAttributes.swift; share one file via Xcode target membership
ios/SandyApp/Widgets/SandyFocusAttributes.swift | 41 | 27 | focus activity attributes (copy) | MERGE: byte-identical to SandyWidget/SandyFocusAttributes.swift; share one file via Xcode target membership
ios/SandyApp/Widgets/WidgetContents.swift | 79 | 72 | in-app tasks board tile | KEEP
ios/SandyApp/Widgets/WidgetData.swift | 81 | 58 | writes data for home widgets | KEEP
ios/SandyApp/ar.lproj/InfoPlist.strings | 3 | 3 | Arabic app name | KEEP
ios/SandyApp/en.lproj/InfoPlist.strings | 3 | 3 | English app name | KEEP
ios/SandyAppTests/APIClientTests.swift | 58 | 48 | JWT decode unit tests | KEEP
ios/SandyAppTests/README.md | 25 | 25 | how to run unit tests | KEEP
ios/SandyAppUITests/SandyAppUITests.swift | 41 | 24 | Xcode template UI tests | ASK OWNER (template, asserts nothing)
ios/SandyAppUITests/SandyAppUITestsLaunchTests.swift | 33 | 23 | launch screenshot UI test | ASK OWNER (template)
ios/SandyShareExtension/Info.plist | 29 | 29 | share extension Info.plist | KEEP
ios/SandyShareExtension/SandyShareExtension.entitlements | 10 | 10 | share extension entitlements | KEEP
ios/SandyShareExtension/ShareAPI.swift | 105 | 100 | share extension HTTP calls | KEEP (separate target, cannot reuse APIClient)
ios/SandyShareExtension/ShareViewController.swift | 376 | 363 | share sheet UI | ASK OWNER
ios/SandyWidget/Assets.xcassets/AccentColor.colorset/Contents.json | 11 | 11 | widget accent color | KEEP
ios/SandyWidget/Assets.xcassets/AppIcon.appiconset/Contents.json | 35 | 35 | widget icon manifest | KEEP
ios/SandyWidget/Assets.xcassets/Contents.json | 6 | 6 | asset catalog manifest | KEEP
ios/SandyWidget/Assets.xcassets/WidgetBackground.colorset/Contents.json | 11 | 11 | widget background color | KEEP
ios/SandyWidget/Info.plist | 11 | 11 | widget Info.plist | KEEP
ios/SandyWidget/PrivacyInfo.xcprivacy | 23 | 23 | widget privacy manifest | KEEP
ios/SandyWidget/SandyCallAttributes.swift | 64 | 53 | call activity attributes | KEEP (see app copy)
ios/SandyWidget/SandyCallLiveActivity.swift | 147 | 140 | call Lock Screen/Island UI | KEEP
ios/SandyWidget/SandyControl.swift | 32 | 27 | Control Center talk button | KEEP
ios/SandyWidget/SandyFocusAttributes.swift | 41 | 27 | focus activity attributes | KEEP (see app copy)
ios/SandyWidget/SandyFocusLiveActivity.swift | 191 | 182 | focus Lock Screen/Island UI | KEEP
ios/SandyWidget/SandyTasksWidget.swift | 285 | 275 | interactive tasks home widget | KEEP
ios/SandyWidget/SandyWidget.swift | 221 | 216 | main Sandy home widget | KEEP
ios/SandyWidget/SandyWidgetBundle.swift | 20 | 13 | registers all widgets | KEEP
ios/SandyWidgetExtension.entitlements | 10 | 10 | widget entitlements | KEEP
ios/SandyApp/Features/Books/ (4 files) | 979 | 979 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Control/ (11 files) | 2691 | 2691 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Daily/ (1 files) | 73 | 73 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/DailyNudge/ (2 files) | 180 | 180 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Focus/ (1 files) | 307 | 307 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/FutureMessages/ (2 files) | 312 | 312 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Gifts/ (2 files) | 427 | 427 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Goals/ (2 files) | 349 | 349 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Home/ (4 files) | 675 | 675 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Images/ (2 files) | 287 | 287 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Insights/ (2 files) | 269 | 269 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Life/ (7 files) | 1066 | 1066 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Memory/ (2 files) | 274 | 274 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Onboarding/ (1 files) | 650 | 650 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Paywall/ (1 files) | 124 | 124 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Photos/ (2 files) | 410 | 410 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Profile/ (2 files) | 714 | 714 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Projects/ (2 files) | 525 | 525 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/QuickAdd/ (1 files) | 170 | 170 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Reminders/ (2 files) | 626 | 626 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Sandy/ (11 files) | 2665 | 2665 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Search/ (2 files) | 291 | 291 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/ShareContent/ (2 files) | 306 | 306 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Shopping/ (2 files) | 459 | 459 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Tasks/ (2 files) | 629 | 629 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Timeline/ (2 files) | 346 | 346 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Features/Weather/ (2 files) | 369 | 369 | feature screens | SKIPPED: scheduled for rewrite
ios/SandyApp/Localization/ (37 files) | 3352 | 3352 | L10n strings per area | SKIPPED: scheduled for rewrite

## ios ASK OWNER

Working features that may not be worth keeping. Nothing here was removed.

- `Core/Networking/APIClientProtocol.swift` — protocol meant for mocking; nothing uses it as a type. Lose: nothing today (the planned test seam).
- `Core/Spotlight/` (indexer + router) — puts tasks/reminders etc. into iOS Spotlight search. Lose: finding Sandy items from the home-screen search.
- `Core/Intents/DeviceIntents.swift` — Siri/Shortcuts control of registered devices. Lose: "Hey Siri, turn on …" without opening the app (the in-app Control screen stays).
- `SandyShareExtension/` — share sheet that sends text/links from other apps to Sandy. Lose: "Share → Sandy" from Safari and other apps.
- `SandyAppUITests/` — Xcode template UI tests (launch + screenshot, no assertions). Lose: a launch smoke test.



---

# firmware/, room-node/, vision-core/ file justification

Scope: `firmware/`, `room-node/`, `vision-core/` (excluding `firmware/brain-core/main/fonts/`,
generated). C/Arduino cannot be compiled here, so no file was moved, merged or deleted and no
code changed: only comments shrank. Every edit was checked with a script that strips comments
and whitespace from the old and new file and requires the rest to be identical. Nothing in scope
is unused: every brain-core .c is in `main/CMakeLists.txt` SRCS, every header is included, and
the Arduino .ino files are all compiled together by the IDE.

Totals (.c/.h/.ino/.py in scope, fonts excluded): 14188 lines before → 12029 after.

file | lines before | lines after | what it does | verdict
---|---|---|---|---
firmware/brain-core/.gitignore | 18 | 12 | build outputs, secrets ignored | KEEP
firmware/brain-core/CMakeLists.txt | 3 | 3 | ESP-IDF project entry point | KEEP
firmware/brain-core/HARDWARE.md | 105 | 105 | generated pin table (gen_hardware_doc.py) | KEEP
firmware/brain-core/WIRING.md | 87 | 87 | human wiring map | KEEP
firmware/brain-core/dependencies.lock | 128 | 128 | component manager version pin | KEEP
firmware/brain-core/main/CMakeLists.txt | 73 | 69 | component sources and requires | KEEP
firmware/brain-core/main/fw_pubkey.pem | 4 | 4 | OTA signature public key | KEEP
firmware/brain-core/main/idf_component.yml | 13 | 10 | pinned managed components | KEEP
firmware/brain-core/main/include/config.h | 270 | 177 | feature flags, pins, tunables | KEEP
firmware/brain-core/main/include/sandy_audio_ctl.h | 131 | 84 | mic/speaker gain, NS, sounds API | KEEP
firmware/brain-core/main/include/sandy_buzzer.h | 6 | 6 | buzzer API | KEEP
firmware/brain-core/main/include/sandy_ears.h | 6 | 6 | sound direction API | KEEP
firmware/brain-core/main/include/sandy_face.h | 47 | 26 | face/display API | KEEP
firmware/brain-core/main/include/sandy_identity.h | 48 | 32 | robot identity API | KEEP
firmware/brain-core/main/include/sandy_ir.h | 26 | 11 | IR learn/replay API | KEEP
firmware/brain-core/main/include/sandy_led.h | 66 | 47 | status LED API | KEEP
firmware/brain-core/main/include/sandy_mic.h | 4 | 4 | clap mic API | KEEP
firmware/brain-core/main/include/sandy_motors.h | 7 | 7 | motor driver API | KEEP
firmware/brain-core/main/include/sandy_mqtt.h | 29 | 17 | MQTT publish API | KEEP
firmware/brain-core/main/include/sandy_net_busy.h | 24 | 16 | one-TLS-session lock API | KEEP
firmware/brain-core/main/include/sandy_nvs.h | 46 | 20 | NVS + deferred writes API | KEEP
firmware/brain-core/main/include/sandy_ota.h | 34 | 15 | OTA + rollback API | KEEP
firmware/brain-core/main/include/sandy_provision.h | 29 | 12 | SoftAP Wi-Fi setup API | KEEP
firmware/brain-core/main/include/sandy_remote.h | 10 | 6 | dev OTA/log server API | KEEP
firmware/brain-core/main/include/sandy_screen.h | 88 | 47 | owner text/image API | KEEP
firmware/brain-core/main/include/sandy_sensor.h | 6 | 6 | ultrasonic sensor API | KEEP
firmware/brain-core/main/include/sandy_servo.h | 43 | 31 | neck servo + gestures API | KEEP
firmware/brain-core/main/include/sandy_spktest.h | 8 | 5 | speaker test API | KEEP
firmware/brain-core/main/include/sandy_status.h | 49 | 29 | health status API | KEEP
firmware/brain-core/main/include/sandy_touch.h | 4 | 4 | touch sensor API | KEEP
firmware/brain-core/main/include/sandy_types.h | 68 | 66 | shared moods, melodies, enums | KEEP
firmware/brain-core/main/include/sandy_voice.h | 32 | 20 | voice link API | KEEP
firmware/brain-core/main/include/sandy_wifi.h | 60 | 37 | Wi-Fi station API | KEEP
firmware/brain-core/main/sandy_audio_ctl.c | 307 | 285 | mic/speaker controls, noise suppression | KEEP
firmware/brain-core/main/sandy_buzzer.c | 144 | 135 | piezo melodies task | KEEP
firmware/brain-core/main/sandy_ears.c | 90 | 86 | stereo sound direction | ASK OWNER (see list)
firmware/brain-core/main/sandy_face.c | 948 | 876 | LVGL animated face | KEEP
firmware/brain-core/main/sandy_identity.c | 142 | 138 | identity from secrets/factory/NVS | KEEP
firmware/brain-core/main/sandy_ir.c | 299 | 270 | IR learn and replay | KEEP
firmware/brain-core/main/sandy_led.c | 296 | 266 | WS2812 privacy LED, effects | KEEP
firmware/brain-core/main/sandy_main.c | 204 | 172 | boot sequence, app_main | KEEP
firmware/brain-core/main/sandy_mic.c | 50 | 50 | MAX9814 clap detection | ASK OWNER (see list)
firmware/brain-core/main/sandy_motors.c | 67 | 67 | L298N motors with watchdog | ASK OWNER (see list)
firmware/brain-core/main/sandy_mqtt.c | 1038 | 850 | MQTT commands, heartbeat, credentials | KEEP
firmware/brain-core/main/sandy_net_busy.c | 20 | 20 | one-TLS-session atomic lock | KEEP
firmware/brain-core/main/sandy_nvs.c | 157 | 139 | NVS init, deferred writes | KEEP
firmware/brain-core/main/sandy_ota.c | 534 | 486 | signed OTA pull, rollback | KEEP
firmware/brain-core/main/sandy_provision.c | 401 | 352 | SoftAP setup page | KEEP
firmware/brain-core/main/sandy_remote.c | 262 | 207 | dev LAN OTA + log | KEEP
firmware/brain-core/main/sandy_screen.c | 393 | 350 | owner text/image on display | KEEP
firmware/brain-core/main/sandy_sensor.c | 71 | 69 | HC-SR04 distance | ASK OWNER (see list)
firmware/brain-core/main/sandy_servo.c | 236 | 214 | neck servo, gestures | KEEP
firmware/brain-core/main/sandy_spktest.c | 87 | 86 | speaker triple-beep test | ASK OWNER (see list)
firmware/brain-core/main/sandy_status.c | 119 | 106 | health status to face/LED | KEEP
firmware/brain-core/main/sandy_touch.c | 38 | 38 | TTP223 head pat | ASK OWNER (see list)
firmware/brain-core/main/sandy_voice.c | 2256 | 1757 | voice WS, wake word, AEC | KEEP
firmware/brain-core/main/sandy_wifi.c | 404 | 338 | Wi-Fi, switch, factory reset | KEEP
firmware/brain-core/main/secrets.example.h | 46 | 24 | secrets template, retail build input | KEEP
firmware/brain-core/partitions.csv | 25 | 14 | flash partition table | KEEP
firmware/brain-core/sdkconfig.defaults | 158 | 98 | ESP-IDF config defaults | KEEP
firmware/brain-core/tools/gen_phonemes.py | 47 | 47 | MultiNet phoneme generator | ASK OWNER (see list)
room-node/partitions.csv | 10 | 8 | flash partition table | KEEP
room-node/room-node.ino | 586 | 544 | room node sketch: light, music | KEEP
room-node/sandy_ca_roots.h | 113 | 113 | generated TLS roots (gen_ca_roots.py) | KEEP
room-node/sandy_identity.h | 78 | 66 | identity in NVS (shared copy) | KEEP
room-node/sandy_ota_pull.h | 353 | 337 | signed OTA pull (shared copy) | KEEP
room-node/secrets.example.h | 36 | 28 | secrets template | KEEP
vision-core/cam_capture.ino | 192 | 172 | camera init, snapshot capture | KEEP
vision-core/cam_control.ino | 545 | 509 | flash, settings, command dispatch | KEEP
vision-core/cam_http.ino | 265 | 227 | local MJPEG stream server | KEEP
vision-core/cam_mqtt.ino | 386 | 314 | MQTT topics, heartbeat | KEEP
vision-core/cam_ota.ino | 102 | 80 | dev OTA + telnet | KEEP
vision-core/cam_upload.ino | 416 | 339 | signed HTTPS upload, remote stream | KEEP
vision-core/cam_wifi.ino | 191 | 167 | Wi-Fi, network switch | KEEP
vision-core/config.h | 200 | 153 | pins, topics, tunables | KEEP
vision-core/partitions.csv | 11 | 8 | flash partition table | KEEP
vision-core/sandy_ca_roots.h | 113 | 113 | generated TLS roots (gen_ca_roots.py) | KEEP
vision-core/sandy_identity.h | 78 | 66 | identity in NVS (shared copy) | KEEP
vision-core/sandy_ota_pull.h | 353 | 337 | signed OTA pull (shared copy) | KEEP
vision-core/secrets.example.h | 43 | 31 | secrets template | KEEP
vision-core/vision-core.ino | 341 | 274 | globals, setup, loop | KEEP
firmware/brain-core/main/fonts/ (3 files) | 18313 | 18313 | generated Arabic LVGL fonts | SKIPPED: generated font data

## firmware ASK OWNER

Working code that is compiled in but switched off in `config.h`. Nothing was removed.

- `sandy_sensor.c` (ENABLE_SENSOR=0) — HC-SR04 "look surprised when something is close". Lose: proximity reaction (part isn't fitted).
- `sandy_motors.c` (ENABLE_MOTORS=0) — L298N drive with a watchdog. Lose: the MQTT `base` motor commands.
- `sandy_touch.c` (ENABLE_TOUCH=0) — TTP223 head pat → happy face + melody. Lose: the head-pat reaction.
- `sandy_mic.c` (ENABLE_MIC=0) — MAX9814 clap detection. Lose: clap reactions (the INMP441 voice mics are separate).
- `sandy_ears.c` (ENABLE_EARS=0) — standalone stereo sound direction; the voice path already turns toward the caller. Lose: eye glances toward sounds outside a conversation.
- `sandy_spktest.c` (ENABLE_SPK_TEST=0) — bring-up triple beep. Lose: a boot-time speaker wiring check (the `spk_play` sounds over MQTT remain).
- MultiNet command words (ENABLE_COMMANDS=0: the `SANDY_COMMANDS` block in `sandy_voice.c`, `tools/gen_phonemes.py`, `CONFIG_SR_MN_*` in sdkconfig.defaults) — offline English "Sandy turn on the light". Off because it cost ~58 KB internal RAM. Lose: offline English room commands.

## firmware left alone (unsure / by design)

- `room-node/` and `vision-core/` each carry identical `sandy_identity.h`, `sandy_ota_pull.h`, `sandy_ca_roots.h`: Arduino sketches only see their own folder, and `tests/` checks the copies match. Merging needs a shared Arduino library; left for the owner.
- `sandy_ca_roots.h`, `HARDWARE.md`, `dependencies.lock`: generated; not hand-edited (HARDWARE.md was regenerated because it quotes config.h comments).
- `WIRING.md`, `firmware/brain-core/tools/gen_phonemes.py` docstring: documentation, kept as is.
- Tiny per-module headers (`sandy_mic.h`, `sandy_touch.h`, …, 4–8 lines): conventional one header per module; not worth a merge that can't be compiled here.
