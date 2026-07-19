import asyncio
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.models.match import Match
from app.models.match_event import MatchEvent, MatchEventKind
from app.models.player import Player
from app.models.team import Team
from app.monitoring.coordinator import MatchMonitorCoordinator
from app.monitoring.policy import MonitorPolicy


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def make_match(
    *,
    starts_in: timedelta = timedelta(hours=2),
    status: str = "pre",
    status_name: str | None = "STATUS_SCHEDULED",
    status_detail: str | None = "Scheduled",
    completed: bool = False,
) -> Match:
    return Match(
        id="match-1",
        name="Away FC at Home FC",
        tournament="esp.1",
        starts_at=NOW + starts_in,
        status=status,
        status_name=status_name,
        status_detail=status_detail,
        completed=completed,
        home_team=Team(id="home", name="Home FC"),
        away_team=Team(id="away", name="Away FC"),
    )


@pytest.mark.parametrize(
    ("starts_in", "expected_delay"),
    [
        (timedelta(hours=2), 3600.0),
        (timedelta(minutes=30), 600.0),
        (timedelta(minutes=7), 120.0),
        (timedelta(minutes=4), 60.0),
        (timedelta(seconds=90), 30.0),
        (timedelta(seconds=30), 2.0),
    ],
)
def test_prematch_poll_intervals(
    starts_in: timedelta,
    expected_delay: float,
) -> None:
    match = make_match(starts_in=starts_in)

    assert MonitorPolicy.next_poll_delay(match, NOW) == expected_delay


def test_live_match_is_polled_every_two_seconds() -> None:
    match = make_match(status="in", status_name="STATUS_IN_PROGRESS")

    assert MonitorPolicy.next_poll_delay(match, NOW) == 2.0


def test_halftime_is_slow_then_returns_to_two_seconds() -> None:
    match = make_match(
        status="in",
        status_name="STATUS_HALFTIME",
        status_detail="Halftime",
    )

    assert MonitorPolicy.next_poll_delay(match, NOW, NOW) == 300.0
    assert MonitorPolicy.next_poll_delay(
        match,
        NOW + timedelta(minutes=13),
        NOW,
    ) == 60.0
    assert MonitorPolicy.next_poll_delay(
        match,
        NOW + timedelta(minutes=14),
        NOW,
    ) == 2.0


def test_finished_match_stops_monitoring() -> None:
    match = make_match(
        status="post",
        status_name="STATUS_FULL_TIME",
        status_detail="FT",
        completed=True,
    )

    assert MonitorPolicy.next_poll_delay(match, NOW) is None


def test_start_runs_initial_scan_and_stop_cancels_scheduler() -> None:
    async def exercise() -> None:
        match_service = AsyncMock()
        match_service.get_matches.return_value = []
        coordinator = MatchMonitorCoordinator(
            match_service,
            ("fifa.world", "esp.1"),
            timezone="UTC",
            now_provider=lambda: NOW,
        )

        await coordinator.start()
        await asyncio.sleep(0)
        await coordinator.stop()

        assert match_service.get_matches.await_count == 2
        assert coordinator.active_monitor_count == 0

    asyncio.run(exercise())


def test_logs_match_detection_and_lifecycle(caplog: pytest.LogCaptureFixture) -> None:
    coordinator = MatchMonitorCoordinator(
        AsyncMock(),
        ("esp.1",),
        timezone="Europe/Madrid",
        now_provider=lambda: NOW,
    )
    scheduled = make_match(starts_in=timedelta(hours=2)).model_copy(
        update={"home_score": 0, "away_score": 0}
    )
    first_half = scheduled.model_copy(
        update={"status": "in", "status_name": "STATUS_FIRST_HALF"}
    )
    halftime = first_half.model_copy(
        update={
            "status_name": "STATUS_HALFTIME",
            "status_detail": "Halftime",
            "home_score": 1,
        }
    )
    second_half = halftime.model_copy(
        update={
            "status_name": "STATUS_SECOND_HALF",
            "status_detail": "Second Half",
        }
    )
    finished = second_half.model_copy(
        update={
            "status": "post",
            "status_name": "STATUS_FULL_TIME",
            "status_detail": "FT",
            "completed": True,
            "away_score": 1,
        }
    )

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        coordinator._log_detected_match(scheduled)
        coordinator._log_state_transition(scheduled, first_half)
        coordinator._log_state_transition(first_half, halftime)
        coordinator._log_state_transition(halftime, second_half)
        coordinator._log_state_transition(second_half, finished)

    messages = [record.getMessage() for record in caplog.records]
    assert any("PARTIDO DETECTADO" in message and "Hora: 16:00" in message for message in messages)
    assert any("INICIO PARTIDO / PRIMERA PARTE" in message for message in messages)
    assert any("FINAL PRIMERA PARTE" in message and "Home FC 1 - 0 Away FC" in message for message in messages)
    assert any("INICIO SEGUNDA PARTE" in message and "Home FC 1 - 0 Away FC" in message for message in messages)
    assert any("FINAL SEGUNDA PARTE / PARTIDO" in message and "Home FC 1 - 1 Away FC" in message for message in messages)


def test_logs_each_new_match_event_only_once(caplog: pytest.LogCaptureFixture) -> None:
    coordinator = MatchMonitorCoordinator(
        AsyncMock(),
        ("esp.1",),
        timezone="Europe/Madrid",
        now_provider=lambda: NOW,
    )
    previous = make_match(status="in", status_name="STATUS_FIRST_HALF")
    goal = MatchEvent(
        id="goal-1",
        type_id="70",
        type="Goal",
        kind=MatchEventKind.GOAL,
        minute="20'",
        clock_seconds=1200,
        team=previous.home_team,
        players=[Player(id="9", name="Home Striker")],
        score_value=1,
        scoring_play=True,
    )
    current = previous.model_copy(
        update={"home_score": 1, "away_score": 0, "events": [goal]}
    )

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        coordinator._log_new_match_events(previous, current)
        coordinator._log_new_match_events(current, current)

    event_logs = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("GOL |")
    ]
    assert len(event_logs) == 1
    assert "Minuto: 20'" in event_logs[0]
    assert "Equipo: Home FC" in event_logs[0]
    assert "Jugador: Home Striker" in event_logs[0]
    assert "Resultado: Home FC 1 - 0 Away FC" in event_logs[0]


def test_notifies_detected_match_by_telegram_only_once() -> None:
    async def exercise() -> None:
        match_service = AsyncMock()
        match_service.get_matches.return_value = [make_match()]
        telegram_client = AsyncMock()
        coordinator = MatchMonitorCoordinator(
            match_service,
            ("esp.1",),
            telegram_client=telegram_client,
            timezone="Europe/Madrid",
            now_provider=lambda: NOW,
        )

        await coordinator.scan_today()
        await coordinator.scan_today()
        await coordinator.stop()

        telegram_client.send_message.assert_awaited_once()
        message = telegram_client.send_message.await_args.args[0]
        assert "PARTIDO DETECTADO HOY" in message
        assert "Torneo: esp.1" in message
        assert "Partido: Home FC vs Away FC" in message
        assert "Hora: 16:00 (Europe/Madrid)" in message

    asyncio.run(exercise())


def test_sends_telegram_for_every_match_status_transition() -> None:
    async def exercise() -> None:
        telegram_client = AsyncMock()
        coordinator = MatchMonitorCoordinator(
            AsyncMock(),
            ("esp.1",),
            telegram_client=telegram_client,
            timezone="Europe/Madrid",
            now_provider=lambda: NOW,
        )
        scheduled = make_match().model_copy(
            update={"home_score": 0, "away_score": 0, "display_clock": "0'"}
        )
        first_half = scheduled.model_copy(
            update={
                "status": "in",
                "status_name": "STATUS_FIRST_HALF",
                "display_clock": "1'",
            }
        )
        halftime = first_half.model_copy(
            update={
                "status_name": "STATUS_HALFTIME",
                "status_detail": "Halftime",
                "display_clock": "45'+2'",
                "home_score": 1,
            }
        )
        second_half = halftime.model_copy(
            update={
                "status_name": "STATUS_SECOND_HALF",
                "status_detail": "Second Half",
                "display_clock": "46'",
            }
        )
        finished = second_half.model_copy(
            update={
                "status": "post",
                "status_name": "STATUS_FULL_TIME",
                "status_detail": "FT",
                "display_clock": "90'+4'",
                "completed": True,
                "away_score": 1,
            }
        )

        await coordinator._handle_state_transition(scheduled, first_half)
        await coordinator._handle_state_transition(first_half, halftime)
        await coordinator._handle_state_transition(halftime, second_half)
        await coordinator._handle_state_transition(second_half, finished)

        messages = [call.args[0] for call in telegram_client.send_message.await_args_list]
        assert len(messages) == 4
        assert "INICIO DEL PARTIDO" in messages[0] and "Reloj: 1'" in messages[0]
        assert "DESCANSO" in messages[1] and "Reloj: 45'+2'" in messages[1]
        assert "INICIO SEGUNDA PARTE" in messages[2] and "Reloj: 46'" in messages[2]
        assert "FINAL DEL PARTIDO" in messages[3] and "Reloj: 90'+4'" in messages[3]
        assert "Resultado: Home FC 1 - 1 Away FC" in messages[3]

    asyncio.run(exercise())


def test_sends_telegram_for_new_goals_cards_and_penalties() -> None:
    async def exercise() -> None:
        telegram_client = AsyncMock()
        coordinator = MatchMonitorCoordinator(
            AsyncMock(),
            ("esp.1",),
            telegram_client=telegram_client,
            timezone="Europe/Madrid",
            now_provider=lambda: NOW,
        )
        previous = make_match(status="in", status_name="STATUS_FIRST_HALF")
        player = Player(id="9", name="Home Striker")
        event_data = [
            ("goal", MatchEventKind.GOAL, "GOL", "20'", [player]),
            ("yellow", MatchEventKind.YELLOW_CARD, "TARJETA AMARILLA", "25'", [player]),
            ("red", MatchEventKind.RED_CARD, "TARJETA ROJA", "30'", [player]),
            ("penalty", MatchEventKind.PENALTY, "PENALTI", "35'", []),
        ]
        events = [
            MatchEvent(
                id=event_id,
                type_id=event_id,
                type=event_name,
                kind=kind,
                minute=minute,
                clock_seconds=index * 300,
                team=previous.home_team,
                players=players,
            )
            for index, (event_id, kind, event_name, minute, players) in enumerate(
                event_data,
                start=1,
            )
        ]
        current = previous.model_copy(
            update={"home_score": 1, "away_score": 0, "events": events}
        )

        await coordinator._handle_new_match_events(previous, current)

        messages = [call.args[0] for call in telegram_client.send_message.await_args_list]
        assert len(messages) == 4
        assert [message.splitlines()[0] for message in messages] == [
            "GOL",
            "TARJETA AMARILLA",
            "TARJETA ROJA",
            "PENALTI",
        ]
        assert "Reloj: 20'" in messages[0]
        assert "Jugador: Home Striker" in messages[0]
        assert "Jugador:" not in messages[3]

    asyncio.run(exercise())
