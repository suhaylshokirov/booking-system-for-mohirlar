"""Field types shared by request schemas: times, and a phone number."""

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


# What people put between the digits of a phone number when they type it.
_PHONE_SEPARATORS = str.maketrans("", "", " -(). ")


def _e164(value: str) -> str:
    """'+998 (90) 123-45-67' -> '+998901234567'. The country code is required:
    without it a number means something different in every country."""
    number = value.translate(_PHONE_SEPARATORS)
    if not number.startswith("+"):
        raise ValueError("start with + and the country code, such as +998 90 123 45 67")
    digits = number[1:]
    if not (digits.isascii() and digits.isdigit()) or digits[0] == "0":
        raise ValueError("use digits after the country code, such as +998 90 123 45 67")
    if not 8 <= len(digits) <= 15:
        raise ValueError("a phone number has 8 to 15 digits with its country code")
    return number


# A phone number in E.164, the shape `providers.phone` stores (its CHECK says the
# same). Spaces, dashes, dots and brackets are accepted and dropped.
PhoneNumber = Annotated[str, AfterValidator(_e164)]
