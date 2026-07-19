from fastapi import Request

from app.services.matches import MatchService


def get_match_service(request: Request) -> MatchService:
    """Return the application-scoped match service."""
    return request.app.state.match_service
