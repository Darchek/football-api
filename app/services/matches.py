import hashlib
from datetime import date
from typing import Any

from pydantic import ValidationError

from app.clients.espn import EspnScoreboardClient, InvalidEspnResponseError
from app.models.match import Match
from app.models.match_event import MatchEvent, MatchEventKind
from app.models.player import Player
from app.models.team import Team


class MatchService:
    """Convert ESPN scoreboard data into the API's match models."""

    def __init__(self, espn_client: EspnScoreboardClient) -> None:
        self.espn_client = espn_client

    async def get_today_matches(self, tournament: str) -> list[Match]:
        return await self.get_matches(tournament)

    async def get_matches(
        self,
        tournament: str,
        match_date: date | None = None,
    ) -> list[Match]:
        payload = await self.espn_client.get_scoreboard(tournament, match_date)
        events = payload.get("events")

        if not isinstance(events, list):
            raise InvalidEspnResponseError("ESPN response is missing an events list")

        return [self._parse_match(event, tournament) for event in events]

    def _parse_match(self, event: Any, tournament: str) -> Match:
        try:
            competition = event["competitions"][0]
            competitors = competition["competitors"]
            home = next(item for item in competitors if item["homeAway"] == "home")
            away = next(item for item in competitors if item["homeAway"] == "away")
            match_status = competition["status"]
            status_type = match_status["type"]
            home_team = self._parse_team(home)
            away_team = self._parse_team(away)
            teams_by_id = {
                home_team.id: home_team,
                away_team.id: away_team,
            }
            details = competition.get("details", []) or []
            if not isinstance(details, list):
                raise InvalidEspnResponseError(
                    "ESPN competition details must be a list"
                )

            return Match(
                id=str(event["id"]),
                name=event["name"],
                tournament=tournament,
                starts_at=event["date"],
                status=status_type["state"],
                status_name=status_type.get("name"),
                status_detail=status_type.get("shortDetail"),
                display_clock=match_status.get("displayClock"),
                clock_seconds=match_status.get("clock"),
                period=match_status.get("period"),
                completed=status_type.get("completed", False),
                venue=competition.get("venue", {}).get("fullName"),
                home_team=home_team,
                away_team=away_team,
                home_score=self._parse_score(home.get("score")),
                away_score=self._parse_score(away.get("score")),
                events=[
                    self._parse_match_event(detail, teams_by_id)
                    for detail in details
                ],
            )
        except (
            KeyError,
            IndexError,
            StopIteration,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise InvalidEspnResponseError(
                "ESPN event has an unexpected structure"
            ) from exc

    @staticmethod
    def _parse_team(competitor: dict[str, Any]) -> Team:
        team = competitor["team"]
        return Team(
            id=str(team["id"]),
            name=team["displayName"],
            abbreviation=team.get("abbreviation"),
            logo=team.get("logo"),
        )

    @staticmethod
    def _parse_score(score: Any) -> int | None:
        if score is None or score == "":
            return None

        try:
            return int(score)
        except (TypeError, ValueError) as exc:
            raise InvalidEspnResponseError("ESPN returned an invalid score") from exc

    def _parse_match_event(
        self,
        detail: dict[str, Any],
        teams_by_id: dict[str, Team],
    ) -> MatchEvent:
        event_type = detail["type"]
        clock = detail["clock"]
        team_id = str(detail.get("team", {}).get("id", ""))
        players = [
            self._parse_player(athlete)
            for athlete in detail.get("athletesInvolved", []) or []
        ]
        type_id = str(event_type["id"])
        type_text = event_type["text"]
        clock_seconds = float(clock["value"])

        event_identity = "|".join(
            (
                type_id,
                str(clock_seconds),
                team_id,
                ",".join(player.id for player in players),
                type_text,
            )
        )
        event_id = hashlib.sha256(event_identity.encode("utf-8")).hexdigest()[:16]

        return MatchEvent(
            id=event_id,
            type_id=type_id,
            type=type_text,
            kind=self._event_kind(detail, type_text),
            minute=clock["displayValue"],
            clock_seconds=clock_seconds,
            team=teams_by_id.get(team_id),
            players=players,
            score_value=int(detail.get("scoreValue", 0)),
            scoring_play=bool(detail.get("scoringPlay", False)),
            penalty_kick=bool(detail.get("penaltyKick", False)),
            own_goal=bool(detail.get("ownGoal", False)),
            shootout=bool(detail.get("shootout", False)),
        )

    @staticmethod
    def _parse_player(athlete: dict[str, Any]) -> Player:
        return Player(
            id=str(athlete["id"]),
            name=athlete["displayName"],
            short_name=athlete.get("shortName"),
            jersey=athlete.get("jersey"),
            position=athlete.get("position"),
            headshot=athlete.get("headshot"),
        )

    @staticmethod
    def _event_kind(detail: dict[str, Any], type_text: str) -> MatchEventKind:
        if detail.get("shootout"):
            return MatchEventKind.PENALTY_SHOOTOUT
        if detail.get("penaltyKick"):
            return MatchEventKind.PENALTY
        if detail.get("ownGoal"):
            return MatchEventKind.OWN_GOAL
        if detail.get("redCard"):
            return MatchEventKind.RED_CARD
        if detail.get("yellowCard"):
            return MatchEventKind.YELLOW_CARD
        if detail.get("scoringPlay") or "goal" in type_text.lower():
            return MatchEventKind.GOAL
        return MatchEventKind.OTHER
