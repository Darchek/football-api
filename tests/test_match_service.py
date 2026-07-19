import asyncio
from unittest.mock import AsyncMock

from app.models.match import Match
from app.models.match_event import MatchEventKind
from app.services.matches import MatchService


def test_normalizes_espn_scoreboard_and_match_events() -> None:
    payload = {
        "events": [
            {
                "id": "704821",
                "name": "Getafe at Atletico Madrid",
                "date": "2024-12-15T13:00Z",
                "competitions": [
                    {
                        "venue": {"fullName": "Metropolitano"},
                        "status": {
                            "clock": 5400.0,
                            "displayClock": "90'+4'",
                            "period": 2,
                            "type": {
                                "name": "STATUS_FULL_TIME",
                                "state": "post",
                                "completed": True,
                                "shortDetail": "FT",
                            }
                        },
                        "competitors": [
                            {
                                "homeAway": "home",
                                "score": "2",
                                "team": {
                                    "id": "1068",
                                    "displayName": "Atletico Madrid",
                                    "abbreviation": "ATM",
                                    "logo": "https://example.com/atm.png",
                                },
                            },
                            {
                                "homeAway": "away",
                                "score": "0",
                                "team": {
                                    "id": "2922",
                                    "displayName": "Getafe",
                                    "abbreviation": "GET",
                                    "logo": "https://example.com/get.png",
                                },
                            },
                        ],
                        "details": [
                            {
                                "type": {"id": "70", "text": "Goal"},
                                "clock": {"value": 1200.0, "displayValue": "20'"},
                                "team": {"id": "1068"},
                                "scoreValue": 1,
                                "scoringPlay": True,
                                "yellowCard": False,
                                "redCard": False,
                                "penaltyKick": False,
                                "ownGoal": False,
                                "shootout": False,
                                "athletesInvolved": [
                                    {
                                        "id": "player-1",
                                        "displayName": "Player One",
                                        "shortName": "P. One",
                                        "jersey": "9",
                                        "position": "F",
                                    }
                                ],
                            },
                            {
                                "type": {"id": "94", "text": "Yellow Card"},
                                "clock": {"value": 1800.0, "displayValue": "30'"},
                                "team": {"id": "2922"},
                                "scoreValue": 0,
                                "scoringPlay": False,
                                "yellowCard": True,
                                "redCard": False,
                                "penaltyKick": False,
                                "ownGoal": False,
                                "shootout": False,
                                "athletesInvolved": [],
                            },
                            {
                                "type": {"id": "156", "text": "Penalty - Scored"},
                                "clock": {"value": 3600.0, "displayValue": "60'"},
                                "team": {"id": "1068"},
                                "scoreValue": 1,
                                "scoringPlay": True,
                                "yellowCard": False,
                                "redCard": False,
                                "penaltyKick": True,
                                "ownGoal": False,
                                "shootout": False,
                                "athletesInvolved": [],
                            },
                        ],
                    }
                ],
            }
        ]
    }
    espn_client = AsyncMock()
    espn_client.get_scoreboard.return_value = payload

    matches = asyncio.run(MatchService(espn_client).get_today_matches("esp.1"))

    assert len(matches) == 1
    assert isinstance(matches[0], Match)
    assert matches[0].home_team.name == "Atletico Madrid"
    assert matches[0].away_team.name == "Getafe"
    assert matches[0].home_score == 2
    assert matches[0].away_score == 0
    assert matches[0].completed is True
    assert matches[0].display_clock == "90'+4'"
    assert matches[0].clock_seconds == 5400.0
    assert matches[0].period == 2
    assert [event.kind for event in matches[0].events] == [
        MatchEventKind.GOAL,
        MatchEventKind.YELLOW_CARD,
        MatchEventKind.PENALTY,
    ]
    assert matches[0].events[0].team == matches[0].home_team
    assert matches[0].events[0].players[0].name == "Player One"
    assert matches[0].events[0].minute == "20'"
    assert len({event.id for event in matches[0].events}) == 3
