"""A stand-in for a `cdp-use` client: every command is recorded and answered from `answers`
(by «Domain.method», a value or a function of the params), every event callback is kept so a
test can fire it."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional, Tuple


class _Domain:
    def __init__(self, client: "FakeCDP", name: str):
        self._client, self._name = client, name

    def __getattr__(self, method: str):
        async def call(params: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None):
            key = f"{self._name}.{method}"
            self._client.sent.append((key, params or {}, session_id))
            answer = self._client.answers.get(key, {})
            return answer(params or {}, session_id) if callable(answer) else answer
        return call


class _Send:
    def __init__(self, client: "FakeCDP"):
        self._client = client

    def __getattr__(self, domain: str) -> _Domain:
        return _Domain(self._client, domain)


class _RegisterDomain:
    def __init__(self, client: "FakeCDP", name: str):
        self._client, self._name = client, name

    def __getattr__(self, event: str):
        def register(callback: Callable):
            self._client.handlers[f"{self._name}.{event}"] = callback
        return register


class _Register:
    def __init__(self, client: "FakeCDP"):
        self._client = client

    def __getattr__(self, domain: str) -> _RegisterDomain:
        return _RegisterDomain(self._client, domain)


class FakeCDP:
    def __init__(self, answers: Optional[Dict[str, Any]] = None):
        self.answers: Dict[str, Any] = {
            "Target.getTargets": {"targetInfos": [{"targetId": "t1", "type": "page"}]},
            "Target.attachToTarget": {"sessionId": "s1"},
            **(answers or {})}
        self.sent: List[Tuple[str, Dict[str, Any], Optional[str]]] = []
        self.handlers: Dict[str, Callable] = {}
        self.send = _Send(self)
        self.register = _Register(self)
        self.stopped = False
        self._reader: Optional[asyncio.Future] = None

    @property
    def _message_handler_task(self) -> asyncio.Future:
        """The connection's reader, as cdp-use's: done once the connection drops (`cut`)."""
        if self._reader is None:
            self._loop = asyncio.get_running_loop()
            self._reader = self._loop.create_future()
        return self._reader

    def cut(self) -> None:
        """The connection drops (from any thread)."""
        self._loop.call_soon_threadsafe(lambda: self._reader.done() or self._reader.set_result(None))

    async def stop(self):
        self.stopped = True
        if self._reader is not None and not self._reader.done():
            self._reader.cancel()

    def names(self) -> List[str]:
        return [name for name, _, _ in self.sent]

    def of(self, name: str) -> List[Dict[str, Any]]:
        return [params for n, params, _ in self.sent if n == name]

    async def fire(self, event: str, data: Dict[str, Any], session_id: Optional[str] = None) -> None:
        """Fire an event and let what it scheduled run."""
        self.handlers[event](data, session_id)
        for _ in range(20):
            await asyncio.sleep(0)
