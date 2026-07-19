import re
from datetime import date
from typing import Any

import httpx


class InvalidEspnResponseError(ValueError):
    """Raised when ESPN returns an unexpected response structure."""


class InvalidTournamentError(ValueError):
    """Raised when an ESPN tournament slug has an invalid format."""


class EspnScoreboardClient:
    """Fetch soccer scoreboard data from ESPN's public JSON API."""

    _TOURNAMENT_PATTERN = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http_client = http_client

    async def get_scoreboard(
        self,
        tournament: str,
        match_date: date | None = None,
    ) -> dict[str, Any]:
        """Return the scoreboard for a tournament and date."""
        if not self._TOURNAMENT_PATTERN.fullmatch(tournament):
            raise InvalidTournamentError("Invalid ESPN tournament slug")

        scoreboard_url = f"{self.base_url}/{tournament}/scoreboard"
        requested_date = match_date or date.today()

        if self._http_client is not None:
            return await self._fetch(
                self._http_client,
                scoreboard_url,
                requested_date,
            )

        async with httpx.AsyncClient(timeout=self.timeout) as http_client:
            return await self._fetch(http_client, scoreboard_url, requested_date)

    async def _fetch(
        self,
        http_client: httpx.AsyncClient,
        scoreboard_url: str,
        match_date: date,
    ) -> dict[str, Any]:
        response = await http_client.get(
            scoreboard_url,
            params={"dates": match_date.strftime("%Y%m%d")},
        )
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict):
            raise InvalidEspnResponseError(
                "ESPN scoreboard response must be a JSON object"
            )

        return payload
