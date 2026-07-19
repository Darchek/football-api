from fastapi import Request

from app.monitoring.coordinator import MatchMonitorCoordinator
from app.services.matches import MatchService


def get_match_service(request: Request) -> MatchService:
    """Return the application-scoped match service."""
    return request.app.state.match_service


def get_match_monitor(request: Request) -> MatchMonitorCoordinator:
    """Return the application-scoped match monitor."""
    return request.app.state.match_monitor
