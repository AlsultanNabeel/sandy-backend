"""WebSocket endpoint for Sandy streaming voice, split into _config +
speaker/memory/tools/session. Public surface unchanged: import
register_voice_ws from app.api.voice_ws as before.
"""
from app.api.voice_ws.session import register_voice_ws

__all__ = ["register_voice_ws"]
