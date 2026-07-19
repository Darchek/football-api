from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.player import Player
from app.models.team import Team


class MatchEventKind(str, Enum):
    GOAL = "goal"
    PENALTY = "penalty"
    PENALTY_SHOOTOUT = "penalty_shootout"
    OWN_GOAL = "own_goal"
    YELLOW_CARD = "yellow_card"
    RED_CARD = "red_card"
    OTHER = "other"


class MatchEvent(BaseModel):
    """A normalized goal, card, penalty, or other ESPN match event."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type_id: str
    type: str
    kind: MatchEventKind
    minute: str
    clock_seconds: float
    team: Team | None = None
    players: list[Player] = Field(default_factory=list)
    score_value: int = 0
    scoring_play: bool = False
    penalty_kick: bool = False
    own_goal: bool = False
    shootout: bool = False
