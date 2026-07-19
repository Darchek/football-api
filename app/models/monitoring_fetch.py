from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class MonitoringFetchKind(str, Enum):
    DAILY_SCAN = "daily_scan"
    MATCH_POLL = "match_poll"


class MonitoringFetch(BaseModel):
    """A queued ESPN fetch used by the background monitor."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: MonitoringFetchKind
    tournament: str
    match_id: str | None = None
    match_name: str | None = None
    scheduled_for: datetime
    seconds_until: float
    interval_seconds: float | None = None
    frequency: str
