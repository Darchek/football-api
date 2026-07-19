from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.dependencies import get_match_service
from app.main import app
from app.models.match import Match
from app.models.team import Team


client = TestClient(app)


def make_match(tournament: str) -> Match:
    return Match(
        id="123",
        name="Away FC at Home FC",
        tournament=tournament,
        starts_at="2024-12-15T13:00:00Z",
        status="pre",
        status_detail="Scheduled",
        home_team=Team(id="1", name="Home FC", abbreviation="HOM"),
        away_team=Team(id="2", name="Away FC", abbreviation="AWY"),
    )


def test_root() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Football API",
        "version": "0.1.0",
        "docs": "/docs",
    }


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_fifa_world_cup_matches() -> None:
    match_service = AsyncMock()
    match_service.get_today_matches.return_value = [make_match("fifa.world")]
    app.dependency_overrides[get_match_service] = lambda: match_service

    try:
        response = client.get("/api/v1/matches/fifa-world-cup")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["tournament"] == "fifa.world"
    assert response.json()[0]["home_team"]["name"] == "Home FC"
    assert response.json()[0]["events"] == []
    match_service.get_today_matches.assert_awaited_once_with("fifa.world")


def test_la_liga_matches() -> None:
    match_service = AsyncMock()
    match_service.get_today_matches.return_value = [make_match("esp.1")]
    app.dependency_overrides[get_match_service] = lambda: match_service

    try:
        response = client.get("/api/v1/matches/la-liga")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["tournament"] == "esp.1"
    assert response.json()[0]["away_team"]["name"] == "Away FC"
    match_service.get_today_matches.assert_awaited_once_with("esp.1")
