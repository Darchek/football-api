from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.match_event import MatchEvent
from app.models.team import Team


class Match(BaseModel):
    """Normalized football match returned by the public API."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    tournament: str
    starts_at: datetime
    status: str
    status_name: str | None = None
    status_detail: str | None = None
    display_clock: str | None = None
    clock_seconds: float | None = None
    period: int | None = None
    completed: bool = False
    venue: str | None = None
    home_team: Team
    away_team: Team
    home_score: int | None = None
    away_score: int | None = None
    events: list[MatchEvent] = Field(default_factory=list)
