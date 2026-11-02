"""Steel's connect address carries its key (`steel_client.connect_url`), and cdp-use logs the
address it connects to: no log line, from any library to any handler, ever shows a key, a token,
a secret, a password or a signature an address carries (`bootstrap.install_redaction`)."""
from __future__ import annotations

import asyncio
import logging

import pytest

from app import bootstrap

SECRET = "ste-REALLOOKINGSECRET0123456789"


@pytest.mark.parametrize("address", [
    f"wss://connect.steel.dev?apiKey={SECRET}&sessionId=abc",
    f"https://x.example/cb?access_token={SECRET}", f"https://x.example/?api_key={SECRET}",
    f"https://x.example/?x=1&client_secret={SECRET}", f"https://x.example/?password={SECRET}",
    f"https://x.example/?sig={SECRET}&t=2", f"https://x.example/?X-Amz-Signature={SECRET}"])
def test_a_secret_in_any_address_is_hidden(address):
    shown = bootstrap.redact(f"Connecting to {address} now")
    assert SECRET not in shown and "=***" in shown


def test_an_address_with_nothing_secret_is_left_alone():
    text = "GET https://x.example/?page=2&q=sea"
    assert bootstrap.redact(text) == text


def test_a_real_connection_logs_no_key_anywhere(caplog):
    """A live websocket on this machine, cdp-use connecting to it with the key in the address
    and every logger at DEBUG: the key is in no line, the address is."""
    import websockets

    from app.integrations import browser_cdp

    async def serve(ws):
        async for _ in ws:
            pass

    async def flow():
        async with websockets.serve(serve, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            client = await browser_cdp.connect(f"ws://127.0.0.1:{port}/?apiKey={SECRET}&sessionId=s1")
            await client.stop()

    caplog.set_level(logging.DEBUG)
    for name in ("cdp_use", "cdp_use.client", "websockets", "browser_use"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    asyncio.run(flow())
    assert "Connecting to ws://127.0.0.1" in caplog.text
    assert SECRET not in caplog.text
    for record in caplog.records:
        assert SECRET not in record.getMessage()


def test_configuring_the_log_keeps_the_browsers_libraries_quiet_and_redacts():
    bootstrap.configure_logging()
    assert getattr(logging.getLogRecordFactory(), "redacting", False)
    for name in ("cdp_use", "browser_use", "bubus"):
        assert logging.getLogger(name).level == logging.WARNING
