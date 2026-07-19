from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_match_monitor
from app.models.monitoring_fetch import MonitoringFetch
from app.monitoring.coordinator import MatchMonitorCoordinator


router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


@router.get("/queue", response_model=list[MonitoringFetch])
async def monitoring_queue(
    monitor: Annotated[MatchMonitorCoordinator, Depends(get_match_monitor)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[MonitoringFetch]:
    """Return upcoming ESPN fetches ordered by scheduled execution time."""
    return monitor.get_upcoming_fetches(limit)
