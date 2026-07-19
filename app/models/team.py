from pydantic import BaseModel, ConfigDict, HttpUrl


class Team(BaseModel):
    """A football team participating in a match."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    abbreviation: str | None = None
    logo: HttpUrl | None = None
