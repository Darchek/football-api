from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_match_service
from app.clients.espn import InvalidEspnResponseError
from app.models.match import Match
from app.services.matches import MatchService


router = APIRouter(prefix="/api/v1/matches", tags=["matches"])


async def _get_matches(
    tournament: str,
    match_service: MatchService,
) -> list[Match]:
    try:
        return await match_service.get_today_matches(tournament)
    except (httpx.HTTPError, InvalidEspnResponseError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to retrieve the ESPN scoreboard",
        ) from exc


@router.get("/fifa-world-cup", response_model=list[Match])
async def fifa_world_cup_matches(
    match_service: Annotated[MatchService, Depends(get_match_service)],
) -> list[Match]:
    """Return today's FIFA World Cup matches."""
    return await _get_matches("fifa.world", match_service)


@router.get("/la-liga", response_model=list[Match])
async def la_liga_matches(
    match_service: Annotated[MatchService, Depends(get_match_service)],
) -> list[Match]:
    """Return today's La Liga matches."""
    return await _get_matches("esp.1", match_service)
