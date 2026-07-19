import httpx


class TelegramClient:
    """Send text messages through the configured Telegram HTTP API."""

    def __init__(
        self,
        api_url: str,
        *,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_url = api_url
        self.timeout = timeout
        self._http_client = http_client

    async def send_message(self, message: str) -> None:
        payload = {"msg": message}

        if self._http_client is not None:
            await self._send(self._http_client, payload)
            return

        async with httpx.AsyncClient(timeout=self.timeout) as http_client:
            await self._send(http_client, payload)

    async def _send(
        self,
        http_client: httpx.AsyncClient,
        payload: dict[str, str],
    ) -> None:
        response = await http_client.post(self.api_url, json=payload)
        response.raise_for_status()
