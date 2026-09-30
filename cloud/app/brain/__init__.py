"""Sandy's agent: one model call with native tools, in a loop, on the blocks.

Chat (`loop.run_turn`, from `api/server.py`) and voice (`voice.dispatch`, from
`api/voice_ws/tools.py`) share the tools, the confirmation flow and the memory.
See ARCHITECTURE_MAP.md §2.13.
"""
