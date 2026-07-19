import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.models.match import Match
from app.models.match_event import MatchEvent
from app.monitoring.coordinator import MatchMonitorCoordinator


logger = logging.getLogger("uvicorn.error")


class MatchReplaySimulator:
    """Replay a completed ESPN match through the live notification handlers."""

    FIRST_HALF_END_SECONDS = 45 * 60

    def __init__(
        self,
        coordinator: MatchMonitorCoordinator,
        *,
        step_delay: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if step_delay < 0:
            raise ValueError("step_delay cannot be negative")
        self.coordinator = coordinator
        self.step_delay = step_delay
        self._sleep = sleep

    async def replay(self, completed_match: Match) -> Match:
        """Replay one completed match from scheduled state through full time."""
        if not completed_match.completed:
            raise ValueError("The replay source match must be completed")

        source_events = sorted(
            completed_match.events,
            key=lambda event: event.clock_seconds,
        )
        first_half_events = [
            event
            for event in source_events
            if event.clock_seconds <= self.FIRST_HALF_END_SECONDS
        ]
        later_events = [
            event
            for event in source_events
            if event.clock_seconds > self.FIRST_HALF_END_SECONDS
        ]

        current = self._scheduled_snapshot(completed_match)
        logger.info("SIMULACIÓN | Partido preparado sin eventos y sin iniciar")
        await self.coordinator.announce_detected_match(current)
        await self._pause()

        first_half = current.model_copy(
            update={
                "status": "in",
                "status_name": "STATUS_FIRST_HALF",
                "status_detail": "First Half",
                "display_clock": "1'",
                "clock_seconds": 60.0,
                "period": 1,
            }
        )
        await self.coordinator.handle_state_transition(current, first_half)
        current = first_half
        await self._pause()

        for event in first_half_events:
            current = await self._replay_event(current, event)

        halftime = current.model_copy(
            update={
                "status_name": "STATUS_HALFTIME",
                "status_detail": "Halftime",
                "display_clock": "45'",
                "clock_seconds": float(self.FIRST_HALF_END_SECONDS),
                "period": 1,
            }
        )
        await self.coordinator.handle_state_transition(current, halftime)
        current = halftime
        await self._pause()

        second_half = current.model_copy(
            update={
                "status_name": "STATUS_SECOND_HALF",
                "status_detail": "Second Half",
                "display_clock": "46'",
                "clock_seconds": 46 * 60.0,
                "period": 2,
            }
        )
        await self.coordinator.handle_state_transition(current, second_half)
        current = second_half
        await self._pause()

        for event in later_events:
            current = await self._replay_event(current, event)

        final_match = completed_match.model_copy(
            update={"events": source_events}
        )
        await self.coordinator.handle_state_transition(current, final_match)
        await self._pause()

        logger.info(
            "SIMULACIÓN FINALIZADA | %s | Resultado: %s - %s",
            completed_match.name,
            completed_match.home_score,
            completed_match.away_score,
        )
        return final_match

    async def _replay_event(self, current: Match, event: MatchEvent) -> Match:
        home_score = current.home_score or 0
        away_score = current.away_score or 0

        if event.scoring_play and event.score_value:
            if event.team is not None and event.team.id == current.home_team.id:
                home_score += event.score_value
            elif event.team is not None and event.team.id == current.away_team.id:
                away_score += event.score_value

        refreshed = current.model_copy(
            update={
                "events": [*current.events, event],
                "home_score": home_score,
                "away_score": away_score,
                "display_clock": event.minute,
                "clock_seconds": event.clock_seconds,
                "period": self._period_for_event(event),
            }
        )
        await self.coordinator.handle_new_match_events(current, refreshed)
        await self._pause()
        return refreshed

    async def _pause(self) -> None:
        if self.step_delay > 0:
            await self._sleep(self.step_delay)

    @staticmethod
    def _scheduled_snapshot(completed_match: Match) -> Match:
        return completed_match.model_copy(
            update={
                "status": "pre",
                "status_name": "STATUS_SCHEDULED",
                "status_detail": "Scheduled",
                "display_clock": "0'",
                "clock_seconds": 0.0,
                "period": 0,
                "completed": False,
                "home_score": 0,
                "away_score": 0,
                "events": [],
            }
        )

    @staticmethod
    def _period_for_event(event: MatchEvent) -> int:
        if event.clock_seconds <= 45 * 60:
            return 1
        if event.clock_seconds <= 90 * 60:
            return 2
        if event.clock_seconds <= 105 * 60:
            return 3
        return 4
