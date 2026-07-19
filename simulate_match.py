import argparse
import asyncio
import logging
from datetime import datetime

import httpx

from app.clients.espn import EspnScoreboardClient
from app.clients.telegram import TelegramClient
from app.core.config import get_settings
from app.monitoring.coordinator import MatchMonitorCoordinator
from app.services.matches import MatchService
from app.simulation.replay import MatchReplaySimulator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay a completed ESPN match as an accelerated live match.",
    )
    parser.add_argument("--date", default="20260711", help="ESPN date as YYYYMMDD")
    parser.add_argument("--tournament", default="fifa.world")
    parser.add_argument("--match-id", help="ESPN match ID; defaults to the first match")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds between simulated updates",
    )
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        help="Send real Telegram notifications during the replay",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    replay_date = datetime.strptime(args.date, "%Y%m%d").date()

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        espn_client = EspnScoreboardClient(
            str(settings.espn_base_url),
            http_client=http_client,
        )
        match_service = MatchService(espn_client)
        matches = await match_service.get_matches(args.tournament, replay_date)
        if not matches:
            raise RuntimeError("ESPN returned no matches for the requested date")

        if args.match_id is None:
            selected_match = matches[0]
        else:
            selected_match = next(
                (match for match in matches if match.id == args.match_id),
                None,
            )
            if selected_match is None:
                available_ids = ", ".join(match.id for match in matches)
                raise RuntimeError(
                    f"Match {args.match_id} was not found. Available IDs: {available_ids}"
                )

        telegram_client = None
        if args.send_telegram:
            telegram_client = TelegramClient(
                str(settings.telegram_api),
                http_client=http_client,
            )

        coordinator = MatchMonitorCoordinator(
            match_service,
            (args.tournament,),
            telegram_client=telegram_client,
            timezone=settings.monitor_timezone,
            daily_scan_hour=settings.daily_scan_hour,
        )
        simulator = MatchReplaySimulator(coordinator, step_delay=args.delay)

        logging.getLogger("uvicorn.error").info(
            "SIMULACIÓN SELECCIONADA | ID: %s | %s | Eventos: %d | Telegram: %s",
            selected_match.id,
            selected_match.name,
            len(selected_match.events),
            "activado" if args.send_telegram else "desactivado",
        )
        await simulator.replay(selected_match)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(run(parse_args()))
