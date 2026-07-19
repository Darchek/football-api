from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.routes import matches, monitoring, system
from app.clients.espn import EspnScoreboardClient
from app.clients.telegram import TelegramClient
from app.core.config import get_settings
from app.monitoring.coordinator import MatchMonitorCoordinator
from app.services.matches import MatchService


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        espn_client = EspnScoreboardClient(
            str(settings.espn_base_url),
            http_client=http_client,
        )
        match_service = MatchService(espn_client)
        telegram_client = TelegramClient(
            str(settings.telegram_api),
            http_client=http_client,
        )
        monitor = MatchMonitorCoordinator(
            match_service,
            settings.monitored_tournaments,
            telegram_client=telegram_client,
            timezone=settings.monitor_timezone,
            daily_scan_hour=settings.daily_scan_hour,
        )

        application.state.match_service = match_service
        application.state.match_monitor = monitor
        application.state.telegram_client = telegram_client
        await monitor.start()
        try:
            yield
        finally:
            await monitor.stop()


app = FastAPI(
    title="Football API",
    description="A football data API backed by ESPN's public JSON endpoints.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(system.router)
app.include_router(matches.router)
app.include_router(monitoring.router)
