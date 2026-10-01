# ADR 0009 — Transactional outbox for notifications

**Status:** accepted (P10.2)

## Context

The customer should be told when their booking is requested, confirmed or
cancelled. Two things must never happen: telling someone about a booking that
was rolled back (it lost a race, or the commit failed), and committing a
booking whose message is lost because the process died between the two steps.
We also had no SMTP server and did not want to add a dependency. (Since ADR 0013 the
app can send email over SMTP using only the standard library, but only for sign-in
codes; booking messages still go to the outbox, and no worker sends them.)

## Decision

Messages are rows in `outbox_messages`, inserted by `OutboxNotifier` in the
**same transaction** as the booking change (`create_booking`, `transition`).
Both commit or both roll back. Delivery is a separate step: a worker reads rows
with `sent_at IS NULL`, sends them and sets `sent_at`. The worker is not built;
the table is the integration point.

`services/notifications.py` defines a `Notifier` protocol and a list
`NOTIFIERS`, currently `OutboxNotifier` and `ConsoleNotifier` (logs, for
development). The text is composed once and given to each.

## Alternatives considered

- **Send the email inside the request.** A slow or failing mail server then
  slows or fails bookings, and the email can go out before a commit that later
  fails.
- **Send after commit (a hook or background task).** The message is lost if the
  process dies between the commit and the send, and nothing records that it was
  owed.
- **A message queue (Redis, RabbitMQ).** Right at larger scale; here it is a new
  service to run and still has the same two-system consistency problem the
  outbox avoids by reusing the database transaction.

## Consequences

- No message for a booking that does not exist, and none lost for one that does.
- Delivery is at-least-once once a worker exists (it may crash after sending and
  before `sent_at`), so a worker must tolerate duplicates.
- `ConsoleNotifier` is not transactional: it can log a message for a booking
  that is later rolled back. It is a development log, not a record.
- A notifier that raises aborts the request, so a booking whose message cannot
  be recorded is not made. Acceptable for an insert into the same database.
- Only the customer is notified; the settings hold no business email.
