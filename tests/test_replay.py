import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.models.match import Match
from app.models.match_event import MatchEvent, MatchEventKind
from app.models.player import Player
from app.models.team import Team
from app.monitoring.coordinator import MatchMonitorCoordinator
from app.simulation.replay import MatchReplaySimulator


def test_replays_completed_match_as_accelerated_live_match() -> None:
    async def exercise() -> None:
        home_team = Team(id="home", name="Home FC")
        away_team = Team(id="away", name="Away FC")
        scorer = Player(id="9", name="Home Striker")
        goal = MatchEvent(
            id="goal-1",
            type_id="70",
            type="Goal",
            kind=MatchEventKind.GOAL,
            minute="20'",
            clock_seconds=20 * 60,
            team=home_team,
            players=[scorer],
            score_value=1,
            scoring_play=True,
        )
        yellow_card = MatchEvent(
            id="card-1",
            type_id="94",
            type="Yellow Card",
            kind=MatchEventKind.YELLOW_CARD,
            minute="70'",
            clock_seconds=70 * 60,
            team=away_team,
            players=[Player(id="4", name="Away Defender")],
        )
        completed_match = Match(
            id="finished-match",
            name="Away FC at Home FC",
            tournament="fifa.world",
            starts_at=datetime(2026, 7, 11, 18, 0, tzinfo=timezone.utc),
            status="post",
            status_name="STATUS_FULL_TIME",
            status_detail="FT",
            display_clock="90'",
            clock_seconds=5400,
            period=2,
            completed=True,
            home_team=home_team,
            away_team=away_team,
            home_score=1,
            away_score=0,
            events=[goal, yellow_card],
        )
        telegram_client = AsyncMock()
        coordinator = MatchMonitorCoordinator(
            AsyncMock(),
            ("fifa.world",),
            telegram_client=telegram_client,
            timezone="UTC",
        )
        detected_snapshots: list[Match] = []
        transition_snapshots: list[tuple[Match, Match]] = []
        event_snapshots: list[tuple[Match, Match]] = []

        original_announce = coordinator.announce_detected_match
        original_transition = coordinator.handle_state_transition
        original_events = coordinator.handle_new_match_events

        async def record_announce(match: Match) -> None:
            detected_snapshots.append(match)
            await original_announce(match)

        async def record_transition(previous: Match, current: Match) -> None:
            transition_snapshots.append((previous, current))
            await original_transition(previous, current)

        async def record_events(previous: Match, current: Match) -> None:
            event_snapshots.append((previous, current))
            await original_events(previous, current)

        coordinator.announce_detected_match = record_announce
        coordinator.handle_state_transition = record_transition
        coordinator.handle_new_match_events = record_events

        result = await MatchReplaySimulator(
            coordinator,
            step_delay=0,
        ).replay(completed_match)

        assert detected_snapshots[0].status == "pre"
        assert detected_snapshots[0].events == []
        assert detected_snapshots[0].home_score == 0
        assert detected_snapshots[0].away_score == 0
        assert [current.status_name for _, current in transition_snapshots] == [
            "STATUS_FIRST_HALF",
            "STATUS_HALFTIME",
            "STATUS_SECOND_HALF",
            "STATUS_FULL_TIME",
        ]
        assert [current.events[-1].id for _, current in event_snapshots] == [
            "goal-1",
            "card-1",
        ]
        assert event_snapshots[0][1].home_score == 1
        assert result.completed is True

        message_titles = [
            call.args[0].splitlines()[0]
            for call in telegram_client.send_message.await_args_list
        ]
        assert message_titles == [
            "PARTIDO DETECTADO HOY",
            "INICIO DEL PARTIDO",
            "GOL",
            "DESCANSO / FINAL PRIMERA PARTE",
            "INICIO SEGUNDA PARTE",
            "TARJETA AMARILLA",
            "FINAL DEL PARTIDO",
        ]

    asyncio.run(exercise())
