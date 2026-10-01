# ruff: noqa: E501  (the meanings are one-line prose, pasted verbatim into docs/api.md)
"""Every error code the app can answer with: HTTP status and what it means.

The single list behind three things, so they cannot drift apart:

* the "Error codes" table in `docs/api.md` (a test compares the two),
* the example error body Swagger shows for each documented error response
  (`app/core/openapi.py`),
* a test that every code raised anywhere in `app/` is listed here.

Add a row here when you introduce a code, then paste it into the docs table.
`meaning` is written for an API client, and is what the docs table prints.
"""

# code -> (HTTP status, meaning)
ERROR_CATALOG: dict[str, tuple[int, str]] = {
    "VALIDATION_ERROR": (
        422,
        "Body, query or path failed schema validation; see `details.errors`",
    ),
    "BAD_REQUEST": (
        400,
        "Generic framework 400",
    ),
    "UNAUTHENTICATED": (
        401,
        "No credentials sent (or a generic framework 401)",
    ),
    "INVALID_CREDENTIALS": (
        401,
        "Login: unknown email or wrong password (deliberately indistinguishable)",
    ),
    "INVALID_TOKEN": (
        401,
        "Token is malformed, tampered with, wrongly signed, or names a user that no longer exists",
    ),
    "TOKEN_EXPIRED": (
        401,
        "Token is past its expiry; log in again",
    ),
    "TOO_MANY_ATTEMPTS": (
        429,
        "Login: too many failed attempts for this IP and email; wait `Retry-After` seconds",
    ),
    "CSRF_FAILED": (
        403,
        "Cookie-authenticated unsafe request without a matching `X-CSRF-Token` header / `csrf_token` field (Bearer requests are exempt)",
    ),
    "ACCOUNT_INACTIVE": (
        401,
        "The account was deactivated (at login only once the password was right; on any request with a token)",
    ),
    "EMAIL_TAKEN": (
        409,
        "Registration: that email already has an account",
    ),
    "INVALID_TIMEZONE": (
        422,
        "Settings: the timezone is not an IANA name such as `Asia/Tashkent`",
    ),
    "GRANULARITY_CONFLICT": (
        409,
        "Settings: an active service's duration is not a multiple of the new slot granularity; `details.services` lists them",
    ),
    "DURATION_NOT_ALIGNED": (
        422,
        "A service's duration is not a multiple of the slot granularity; `details` has both numbers",
    ),
    "UNKNOWN_SERVICE": (
        422,
        "Setting a provider's services: an id is not an existing, active service; `details.service_ids` lists them",
    ),
    "MISALIGNED_TIME": (
        422,
        "Availability: a start or end time is not a multiple of the slot granularity; `details` has `field` and `slot_granularity_minutes`",
    ),
    "INVALID_TIME_RANGE": (
        422,
        "Availability: an edit leaves `end_time` at or before `start_time`, or an exception with only one of its two times",
    ),
    "DATE_OUT_OF_RANGE": (
        422,
        "Slots: the date is before today or beyond the booking horizon (business timezone); `details.earliest`, `details.latest`",
    ),
    "PROVIDER_DOES_NOT_OFFER_SERVICE": (
        422,
        "Slots: the chosen provider does not perform that service; `details` has both ids",
    ),
    "SERVICE_INACTIVE": (
        422,
        "Booking: the service is deactivated",
    ),
    "PROVIDER_INACTIVE": (
        422,
        "Booking: the provider is deactivated",
    ),
    "START_IN_PAST": (
        422,
        "Booking: the start is before now",
    ),
    "INSIDE_LEAD_TIME": (
        422,
        "Booking: the start is sooner than the minimum lead time; `details.earliest`",
    ),
    "BEYOND_HORIZON": (
        422,
        "Booking: the start is at or past the booking horizon; `details.before`",
    ),
    "OUTSIDE_AVAILABILITY": (
        422,
        "Booking: the provider is not working for the whole service at that time (weekly rules and exceptions applied)",
    ),
    "NOT_ALIGNED": (
        422,
        "Booking: the start is not on the slot grid measured from the window start",
    ),
    "BOOKING_NOT_FOUND": (
        404,
        "No such booking, or it belongs to someone else (a barber sees the ones made with them)",
    ),
    "INVALID_TRANSITION": (
        409,
        "Booking: that status change is not allowed (not the booking's barber or customer, the wrong current status, or it has already started); `details.from`, `details.to`",
    ),
    "CANCELLATION_CUTOFF_PASSED": (
        409,
        "Booking: too late for a customer to cancel (a confirmed booking after `start - cutoff`, a pending one after it started); `details.cutoff_at`",
    ),
    "REASON_REQUIRED": (
        422,
        "Booking: a barber cancelling a confirmed booking must give a reason",
    ),
    "TOO_EARLY_TO_COMPLETE": (
        409,
        "Booking: it can only be completed once `end_at` has passed; `details.end_at`",
    ),
    "BOOKING_STATE_CHANGED": (
        409,
        "Booking: someone changed it at the same moment (ADR 0008); reload and try again",
    ),
    "SLOT_TAKEN": (
        409,
        "Booking: the provider already has a pending or confirmed booking overlapping that time",
    ),
    "CUSTOMER_OVERLAP": (
        409,
        "Booking: you already have a pending or confirmed booking overlapping that time",
    ),
    "DATE_IN_PAST": (
        422,
        "Availability exception: the date is before today in the business timezone; `details.today`",
    ),
    "AVAILABILITY_EXCEPTION_EXISTS": (
        409,
        "Availability exception: the provider already has one for that date; `details.exception_id`",
    ),
    "AVAILABILITY_OVERLAP": (
        409,
        "Availability: the window overlaps another rule of the provider on that weekday; `details.conflicting_rule`",
    ),
    "FORBIDDEN": (
        403,
        "Logged in, but the endpoint needs the barber role, or it is another barber's profile or hours (or a generic framework 403)",
    ),
    "NOT_FOUND": (
        404,
        "No such route (or, for our own endpoints, no such resource)",
    ),
    "METHOD_NOT_ALLOWED": (
        405,
        "Route exists but not for this HTTP method; `Allow` header lists the valid ones",
    ),
    "CONFLICT": (
        409,
        "Generic framework 409",
    ),
    "TOO_MANY_REQUESTS": (
        429,
        "Generic framework 429",
    ),
    "INTERNAL_ERROR": (
        500,
        "Unexpected failure on our side",
    ),
    "DATABASE_UNAVAILABLE": (
        503,
        "`GET /health` could not reach the database",
    ),
    "INVALID_SLOT": (
        422,
        "Web booking form only (an HTML page, not JSON): the chosen time is not one of the offered slots",
    ),
    "INVALID_PROVIDER": (
        422,
        "Web booking form only (an HTML page, not JSON): the chosen person is not one of the offered providers",
    ),
}
