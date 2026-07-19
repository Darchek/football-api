import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.clients.espn import InvalidEspnResponseError
from app.clients.telegram import TelegramClient
from app.models.match import Match
from app.models.match_event import MatchEvent, MatchEventKind
from app.models.monitoring_fetch import MonitoringFetch, MonitoringFetchKind
from app.monitoring.policy import MonitorPolicy
from app.services.matches import MatchService


logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class _ScheduledFetch:
    id: str
    kind: MonitoringFetchKind
    tournament: str
    scheduled_for: datetime
    frequency: str
    interval_seconds: float | None = None
    match_id: str | None = None
    match_name: str | None = None


class MatchMonitorCoordinator:
    """Discover today's matches and monitor each one until it finishes."""

    def __init__(
        self,
        match_service: MatchService,
        tournaments: tuple[str, ...],
        *,
        telegram_client: TelegramClient | None = None,
        timezone: str = "Europe/Madrid",
        daily_scan_hour: int = 10,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.match_service = match_service
        self.tournaments = tournaments
        self.telegram_client = telegram_client
        self.timezone = ZoneInfo(timezone)
        self.daily_scan_hour = daily_scan_hour
        self._now_provider = now_provider
        self._scheduler_task: asyncio.Task[None] | None = None
        self._match_tasks: dict[str, asyncio.Task[None]] = {}
        self._scheduled_fetches: dict[str, _ScheduledFetch] = {}
        self._notified_match_ids: set[str] = set()

    async def start(self) -> None:
        """Start the startup scan and daily 10:00 scheduler."""
        if self._scheduler_task is None or self._scheduler_task.done():
            await self.scan_today()
            self._scheduler_task = asyncio.create_task(
                self._daily_loop(),
                name="daily-match-discovery",
            )

    async def stop(self) -> None:
        """Cancel the scheduler and every active match monitor."""
        tasks = [*self._match_tasks.values()]
        if self._scheduler_task is not None:
            tasks.append(self._scheduler_task)

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self._match_tasks.clear()
        self._scheduled_fetches.clear()
        self._scheduler_task = None

    async def scan_today(self) -> None:
        """Find today's matches in every configured tournament."""
        scan_date = self._now().date()
        results = await asyncio.gather(
            *(self._scan_tournament(tournament, scan_date) for tournament in self.tournaments),
            return_exceptions=True,
        )

        for tournament, result in zip(self.tournaments, results, strict=True):
            if isinstance(result, BaseException):
                logger.error(
                    "Could not scan tournament %s: %s",
                    tournament,
                    result,
                )

    @property
    def active_monitor_count(self) -> int:
        return sum(not task.done() for task in self._match_tasks.values())

    def get_upcoming_fetches(self, limit: int = 20) -> list[MonitoringFetch]:
        """Return the next real fetch queued by each active monitor task."""
        if limit < 1:
            return []

        now = self._now()
        queued_fetches = list(self._scheduled_fetches.values())

        if self._scheduler_task is not None and not self._scheduler_task.done():
            daily_scan_at = self._next_daily_scan_at(now)
            queued_fetches.extend(
                _ScheduledFetch(
                    id=f"daily:{tournament}",
                    kind=MonitoringFetchKind.DAILY_SCAN,
                    tournament=tournament,
                    scheduled_for=daily_scan_at,
                    frequency=f"daily at {self.daily_scan_hour:02d}:00",
                )
                for tournament in self.tournaments
            )

        queued_fetches.sort(key=lambda fetch: (fetch.scheduled_for, fetch.id))
        return [
            MonitoringFetch(
                id=fetch.id,
                kind=fetch.kind,
                tournament=fetch.tournament,
                match_id=fetch.match_id,
                match_name=fetch.match_name,
                scheduled_for=fetch.scheduled_for,
                seconds_until=round(
                    max((fetch.scheduled_for - now).total_seconds(), 0.0),
                    3,
                ),
                interval_seconds=fetch.interval_seconds,
                frequency=fetch.frequency,
            )
            for fetch in queued_fetches[:limit]
        ]

    async def _daily_loop(self) -> None:
        try:
            while True:
                delay = self._seconds_until_next_daily_scan()
                logger.info("Próximo escaneo diario en %.0f segundos", delay)
                await asyncio.sleep(delay)
                await self.scan_today()
        except asyncio.CancelledError:
            raise

    async def _scan_tournament(self, tournament: str, scan_date: date) -> None:
        matches = await self.match_service.get_matches(tournament, scan_date)
        if not matches:
            logger.info("SIN PARTIDOS HOY | Torneo: %s", tournament)
            return

        logger.info(
            "PARTIDOS DEL DÍA | Torneo: %s | Total: %d",
            tournament,
            len(matches),
        )
        for match in matches:
            await self.announce_detected_match(match)

            if match.completed or match.status == "post":
                continue

            key = self._match_key(match)
            existing_task = self._match_tasks.get(key)
            if existing_task is not None and not existing_task.done():
                continue

            task = asyncio.create_task(
                self._monitor_match(match, scan_date),
                name=f"match-monitor-{key}",
            )
            self._match_tasks[key] = task
            task.add_done_callback(
                lambda completed_task, match_key=key: self._remove_match_task(
                    match_key,
                    completed_task,
                )
            )

    async def _monitor_match(self, match: Match, match_date: date) -> None:
        current_match = match
        halftime_started_at = (
            self._now() if MonitorPolicy.is_halftime(current_match) else None
        )

        self._log_initial_monitor_state(current_match)
        if current_match.status == "in":
            for event in current_match.events:
                self._log_match_event(current_match, event, detected_on_startup=True)

        while True:
            now = self._now()
            delay = MonitorPolicy.next_poll_delay(
                current_match,
                now,
                halftime_started_at,
            )
            if delay is None:
                self._scheduled_fetches.pop(self._match_key(current_match), None)
                logger.info(
                    "MONITORIZACIÓN FINALIZADA | %s",
                    self._match_label(match),
                )
                return

            delay = max(delay, 0.0)
            fetch_key = self._match_key(current_match)
            self._scheduled_fetches[fetch_key] = _ScheduledFetch(
                id=f"match:{fetch_key}",
                kind=MonitoringFetchKind.MATCH_POLL,
                tournament=current_match.tournament,
                match_id=current_match.id,
                match_name=self._match_label(current_match),
                scheduled_for=now + timedelta(seconds=delay),
                interval_seconds=round(delay, 3),
                frequency=MonitorPolicy.poll_frequency(
                    current_match,
                    now,
                    halftime_started_at,
                ),
            )

            await asyncio.sleep(delay)
            self._scheduled_fetches.pop(fetch_key, None)

            try:
                matches = await self.match_service.get_matches(
                    current_match.tournament,
                    match_date,
                )
            except (httpx.HTTPError, InvalidEspnResponseError) as exc:
                logger.warning("Could not refresh match %s: %s", match.id, exc)
                continue

            refreshed_match = next(
                (candidate for candidate in matches if candidate.id == current_match.id),
                None,
            )
            if refreshed_match is None:
                logger.warning("Match %s was not present in ESPN response", match.id)
                continue

            await self.handle_new_match_events(current_match, refreshed_match)
            await self.handle_state_transition(current_match, refreshed_match)

            if MonitorPolicy.is_halftime(refreshed_match):
                halftime_started_at = halftime_started_at or self._now()
            else:
                halftime_started_at = None

            current_match = refreshed_match

    def _seconds_until_next_daily_scan(self) -> float:
        now = self._now()
        return (self._next_daily_scan_at(now) - now).total_seconds()

    def _next_daily_scan_at(self, now: datetime) -> datetime:
        next_scan = now.replace(
            hour=self.daily_scan_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        if next_scan <= now:
            next_scan += timedelta(days=1)
        return next_scan

    def _now(self) -> datetime:
        if self._now_provider is not None:
            now = self._now_provider()
            if now.tzinfo is None:
                return now.replace(tzinfo=self.timezone)
            return now.astimezone(self.timezone)
        return datetime.now(self.timezone)

    def _remove_match_task(
        self,
        key: str,
        completed_task: asyncio.Task[None],
    ) -> None:
        if self._match_tasks.get(key) is completed_task:
            self._match_tasks.pop(key, None)
        self._scheduled_fetches.pop(key, None)

    @staticmethod
    def _match_key(match: Match) -> str:
        return f"{match.tournament}:{match.id}"

    def _log_detected_match(self, match: Match) -> None:
        local_kickoff = self._local_kickoff(match)

        logger.info(
            "PARTIDO DETECTADO | Torneo: %s | %s | Hora: %s (%s)",
            match.tournament,
            self._match_label(match),
            local_kickoff.strftime("%H:%M"),
            self.timezone.key,
        )

    async def announce_detected_match(self, match: Match) -> None:
        """Log and notify a newly discovered fixture."""
        self._log_detected_match(match)
        await self._notify_detected_match(match)

    async def _notify_detected_match(self, match: Match) -> None:
        if self.telegram_client is None:
            return

        match_key = self._match_key(match)
        if match_key in self._notified_match_ids:
            return

        local_kickoff = self._local_kickoff(match)
        text = (
            "PARTIDO DETECTADO HOY\n"
            f"Torneo: {match.tournament}\n"
            f"Partido: {self._match_label(match)}\n"
            f"Hora: {local_kickoff.strftime('%H:%M')} ({self.timezone.key})"
        )

        try:
            await self.telegram_client.send_message(text)
        except httpx.HTTPError as exc:
            logger.error(
                "ERROR TELEGRAM | No se pudo notificar %s: %s",
                self._match_label(match),
                exc,
            )
            return

        self._notified_match_ids.add(match_key)
        logger.info(
            "TELEGRAM ENVIADO | Partido: %s | Hora: %s",
            self._match_label(match),
            local_kickoff.strftime("%H:%M"),
        )

    def _log_initial_monitor_state(self, match: Match) -> None:
        if match.status != "in":
            return

        if MonitorPolicy.is_halftime(match):
            event = "PARTIDO EN DESCANSO AL INICIAR EL MONITOR"
        elif (match.status_name or "").upper() == "STATUS_SECOND_HALF":
            event = "PARTIDO EN SEGUNDA PARTE AL INICIAR EL MONITOR"
        else:
            event = "PARTIDO YA INICIADO AL INICIAR EL MONITOR"

        logger.info(
            "%s | %s | Resultado: %s",
            event,
            self._match_label(match),
            self._score_label(match),
        )

    def _log_state_transition(self, previous: Match, current: Match) -> None:
        transition = self._state_transition(previous, current)

        if transition == "full_time":
            logger.info(
                "FINAL SEGUNDA PARTE / PARTIDO | %s | Resultado: %s",
                self._match_label(current),
                self._score_label(current),
            )
        elif transition == "halftime":
            logger.info(
                "FINAL PRIMERA PARTE | %s | Resultado: %s",
                self._match_label(current),
                self._score_label(current),
            )
        elif transition == "second_half":
            logger.info(
                "INICIO SEGUNDA PARTE | %s | Resultado: %s",
                self._match_label(current),
                self._score_label(current),
            )
        elif transition == "kickoff":
            logger.info(
                "INICIO PARTIDO / PRIMERA PARTE | %s",
                self._match_label(current),
            )

    async def handle_state_transition(
        self,
        previous: Match,
        current: Match,
    ) -> None:
        transition = self._state_transition(previous, current)
        if transition is None:
            return

        self._log_state_transition(previous, current)
        transition_names = {
            "kickoff": "INICIO DEL PARTIDO",
            "halftime": "DESCANSO / FINAL PRIMERA PARTE",
            "second_half": "INICIO SEGUNDA PARTE",
            "full_time": "FINAL DEL PARTIDO",
        }
        message = (
            f"{transition_names[transition]}\n"
            f"Partido: {self._match_label(current)}\n"
            f"Reloj: {self._clock_label(current)}\n"
            f"Resultado: {self._score_label(current)}"
        )
        await self._send_telegram_message(message, current)

    def _log_new_match_events(self, previous: Match, current: Match) -> None:
        known_event_ids = {event.id for event in previous.events}
        for event in current.events:
            if event.id not in known_event_ids:
                self._log_match_event(current, event)

    async def handle_new_match_events(
        self,
        previous: Match,
        current: Match,
    ) -> None:
        known_event_ids = {event.id for event in previous.events}
        for event in current.events:
            if event.id in known_event_ids:
                continue

            self._log_match_event(current, event)
            await self._send_match_event(current, event)

    def _log_match_event(
        self,
        match: Match,
        event: MatchEvent,
        *,
        detected_on_startup: bool = False,
    ) -> None:
        event_names = {
            MatchEventKind.GOAL: "GOL",
            MatchEventKind.PENALTY: "PENALTI",
            MatchEventKind.PENALTY_SHOOTOUT: "PENALTI EN TANDA",
            MatchEventKind.OWN_GOAL: "AUTOGOL",
            MatchEventKind.YELLOW_CARD: "TARJETA AMARILLA",
            MatchEventKind.RED_CARD: "TARJETA ROJA",
            MatchEventKind.OTHER: "EVENTO",
        }
        event_name = event_names[event.kind]
        if detected_on_startup:
            event_name = f"{event_name} DETECTADO AL INICIAR"

        team_name = event.team.name if event.team is not None else "Desconocido"
        player_names = ", ".join(player.name for player in event.players)
        player_names = player_names or "Desconocido"

        logger.info(
            "%s | %s | Minuto: %s | Equipo: %s | Jugador: %s | Resultado: %s",
            event_name,
            self._match_label(match),
            event.minute,
            team_name,
            player_names,
            self._score_label(match),
        )

    async def _send_match_event(self, match: Match, event: MatchEvent) -> None:
        event_names = {
            MatchEventKind.GOAL: "GOL",
            MatchEventKind.PENALTY: "PENALTI",
            MatchEventKind.PENALTY_SHOOTOUT: "PENALTI EN TANDA",
            MatchEventKind.OWN_GOAL: "AUTOGOL",
            MatchEventKind.YELLOW_CARD: "TARJETA AMARILLA",
            MatchEventKind.RED_CARD: "TARJETA ROJA",
            MatchEventKind.OTHER: "EVENTO DEL PARTIDO",
        }
        team_name = event.team.name if event.team is not None else "Desconocido"
        lines = [
            event_names[event.kind],
            f"Partido: {self._match_label(match)}",
            f"Reloj: {event.minute}",
            f"Equipo: {team_name}",
        ]
        if event.players:
            player_names = ", ".join(player.name for player in event.players)
            lines.append(f"Jugador: {player_names}")
        lines.append(f"Resultado: {self._score_label(match)}")

        await self._send_telegram_message("\n".join(lines), match)

    async def _send_telegram_message(self, message: str, match: Match) -> bool:
        if self.telegram_client is None:
            return False

        try:
            await self.telegram_client.send_message(message)
        except httpx.HTTPError as exc:
            logger.error(
                "ERROR TELEGRAM | No se pudo notificar %s: %s",
                self._match_label(match),
                exc,
            )
            return False

        logger.info("TELEGRAM ENVIADO | %s", message.splitlines()[0])
        return True

    @staticmethod
    def _state_transition(previous: Match, current: Match) -> str | None:
        was_halftime = MonitorPolicy.is_halftime(previous)
        is_halftime = MonitorPolicy.is_halftime(current)

        if not previous.completed and (current.completed or current.status == "post"):
            return "full_time"
        if not was_halftime and is_halftime:
            return "halftime"
        if was_halftime and current.status == "in" and not is_halftime:
            return "second_half"
        if previous.status != "in" and current.status == "in":
            return "kickoff"
        return None

    @staticmethod
    def _match_label(match: Match) -> str:
        return f"{match.home_team.name} vs {match.away_team.name}"

    @staticmethod
    def _score_label(match: Match) -> str:
        home_score = "-" if match.home_score is None else str(match.home_score)
        away_score = "-" if match.away_score is None else str(match.away_score)
        return (
            f"{match.home_team.name} {home_score} - "
            f"{away_score} {match.away_team.name}"
        )

    @staticmethod
    def _clock_label(match: Match) -> str:
        return match.display_clock or match.status_detail or "No disponible"

    def _local_kickoff(self, match: Match) -> datetime:
        kickoff = match.starts_at
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        return kickoff.astimezone(self.timezone)
