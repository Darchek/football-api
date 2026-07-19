import asyncio
import json

import httpx

from app.clients.telegram import TelegramClient


def test_sends_expected_telegram_payload() -> None:
    received_payload: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://example.com/telegram/send"
        received_payload.update(json.loads(request.content))
        return httpx.Response(200, json={"sent": True})

    async def send() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = TelegramClient(
                "https://example.com/telegram/send",
                http_client=http_client,
            )
            await client.send_message("Test message")

    asyncio.run(send())

    assert received_payload == {"msg": "Test message"}
