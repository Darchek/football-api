from datetime import datetime

from app.models.match import Match


class MonitorPolicy:
    """Determine when a match should be checked again."""

    TEN_MINUTES = 10 * 60.0
    FIVE_MINUTES = 5 * 60.0
    ONE_MINUTE = 60.0
    TWO_SECONDS = 2.0
    HALFTIME_SLOW_PERIOD = 14 * 60.0

    @classmethod
    def next_poll_delay(
        cls,
        match: Match,
        now: datetime,
        halftime_started_at: datetime | None = None,
    ) -> float | None:
        """Return seconds until the next poll, or `None` when monitoring ends."""
        if match.completed or match.status == "post":
            return None

        if cls.is_halftime(match):
            if halftime_started_at is None:
                return cls.FIVE_MINUTES

            halftime_elapsed = (now - halftime_started_at).total_seconds()
            if halftime_elapsed >= cls.HALFTIME_SLOW_PERIOD:
                return cls.TWO_SECONDS

            until_fast_polling = cls.HALFTIME_SLOW_PERIOD - halftime_elapsed
            return min(cls.FIVE_MINUTES, until_fast_polling)

        if match.status == "in":
            return cls.TWO_SECONDS

        seconds_to_start = (match.starts_at - now).total_seconds()

        if seconds_to_start > 60 * 60:
            return seconds_to_start - 60 * 60
        if seconds_to_start > cls.FIVE_MINUTES:
            return min(cls.TEN_MINUTES, seconds_to_start - cls.FIVE_MINUTES)
        if seconds_to_start > cls.ONE_MINUTE:
            return min(cls.ONE_MINUTE, seconds_to_start - cls.ONE_MINUTE)

        return cls.TWO_SECONDS

    @classmethod
    def poll_frequency(
        cls,
        match: Match,
        now: datetime,
        halftime_started_at: datetime | None = None,
    ) -> str:
        """Describe the polling phase responsible for the next fetch."""
        if cls.is_halftime(match):
            if halftime_started_at is not None:
                halftime_elapsed = (now - halftime_started_at).total_seconds()
                if halftime_elapsed >= cls.HALFTIME_SLOW_PERIOD:
                    return "every 2 seconds"
            return "every 5 minutes"

        if match.status == "in":
            return "every 2 seconds"

        seconds_to_start = (match.starts_at - now).total_seconds()
        if seconds_to_start > 60 * 60:
            return "waiting until one hour before kickoff"
        if seconds_to_start > cls.FIVE_MINUTES:
            return "every 10 minutes"
        if seconds_to_start > cls.ONE_MINUTE:
            return "every minute"
        return "every 2 seconds"

    @staticmethod
    def is_halftime(match: Match) -> bool:
        status_name = (match.status_name or "").upper()
        status_detail = (match.status_detail or "").strip().lower()
        return status_name == "STATUS_HALFTIME" or status_detail in {
            "halftime",
            "half time",
            "ht",
        }
