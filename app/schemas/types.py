"""Field types shared by request schemas."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# A datetime the client sent with an explicit offset ("...T10:00:00+05:00" or
# "...Z"). A naive one ("...T10:00:00") is a 422: without a zone it names no
# instant (edge case 12). Whatever offset came in, the value is UTC from here on.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
