import asyncio
from datetime import date

import httpx

from app.clients.espn import EspnScoreboardClient


def test_get_scoreboard() -> None:
    expected_payload = {"events": [{"id": "123"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == (
            "https://example.com/soccer/esp.1/scoreboard?dates=20241215"
        )
        return httpx.Response(200, json=expected_payload)

    async def fetch_scoreboard() -> dict[str, object]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = EspnScoreboardClient(
                "https://example.com/soccer",
                http_client=http_client,
            )
            return await client.get_scoreboard("esp.1", date(2024, 12, 15))

    assert asyncio.run(fetch_scoreboard()) == expected_payload
