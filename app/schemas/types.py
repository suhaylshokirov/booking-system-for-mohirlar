"""Field types shared by request schemas."""

from datetime import UTC, datetime, time
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# A datetime the client sent with an explicit offset ("...T10:00:00+05:00" or
# "...Z"). A naive one ("...T10:00:00") is a 422: without a zone it names no
# instant (edge case 12). Whatever offset came in, the value is UTC from here on.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


def _local_time_only(value: time) -> time:
    if value.tzinfo is not None:
        raise ValueError("a time of day has no timezone offset; it is local to the business")
    if value.second or value.microsecond:
        raise ValueError("use whole minutes, such as 09:30")
    return value


# A local wall-clock time of day ("09:30") for availability. It is read in the
# business timezone, so an offset is refused rather than silently ignored.
LocalTime = Annotated[time, AfterValidator(_local_time_only)]
