from pydantic import BaseModel, ConfigDict, HttpUrl


class Player(BaseModel):
    """A player involved in a match event."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    short_name: str | None = None
    jersey: str | None = None
    position: str | None = None
    headshot: HttpUrl | None = None
