# Submission form: draft answers

Drafts for the one-shot form. **Edit them in your own words before submitting**: the form
cannot be changed afterwards, and you will be asked about every sentence. Nothing here was
submitted by an agent.

## Links

- **Public repository:** https://github.com/suhaylshokirov/booking-system-for-mohirlar
- **Live demo:** https://navbat-pi.vercel.app (the first request after idle can take a few seconds)
- **Signing in on the demo:** there are no passwords. Choose *Sign up*, enter your own email,
  and type the 6-digit code that arrives (check spam).

> Before submitting: confirm the repository is **public**, the live URL opens, and one code
> email reaches your own inbox. Those are the two checks no test can do (see P11.1).

## Product description (at least 100 characters)

Navbat ("turn" in Uzbek) is an appointment booking system for a small service business,
shown as a barbershop. A customer chooses a service, sees the free times of the barbers
who offer it, and books one; the booking starts Pending and a barber confirms it, later
marking it Completed, or either side cancels it (customers until a cutoff before the
start). Each barber manages their own hours, days off, profile and bookings, and any
barber manages the shared services and settings; there is no administrator. Free times
are computed from weekly hours and existing bookings, shown in the shop's timezone and
stored in UTC. Two people can never hold the same barber at overlapping times: the
database refuses it, so even simultaneous requests end with one booking and one clear
"that time was just taken" message. There is a JSON API with Swagger docs, a server-rendered
website that also works without JavaScript, passwordless sign-in with an emailed code,
a downloadable calendar file for each booking, and a full status history.

## Architecture (optional, filled in anyway)

Python 3.12, FastAPI, SQLAlchemy 2.0 and PostgreSQL, deployed on Vercel with a Neon database.
Routers (the JSON API and the HTML pages) are thin and call one shared layer of services,
so each rule (validation, double-booking protection, status transitions) lives in exactly
one place. Double booking is prevented by the database, not by application code: two
PostgreSQL `EXCLUDE USING gist` constraints on the time range `[start, end)`, one per barber
and one per customer, whose violation becomes `409 SLOT_TAKEN` or `CUSTOMER_OVERLAP`; the
service's own check only produces a friendlier message in the ordinary case. Free slots are
computed on request by a pure function rather than stored, so changing hours or durations
needs no migration. Every timestamp is UTC; local time is converted in one module. Status
changes go through one state machine and a guarded `UPDATE ... WHERE status = :expected`,
each writing a history row in the same transaction. Fourteen short ADRs in `docs/decisions/`
record each choice and the alternatives rejected; `docs/edge-cases.md` lists 105 risks with
the test that proves each.

## AI tools used

Claude Code (Anthropic's command-line coding agent) with the Claude Opus 5.5 and
Claude Sonnet 5.5 models.

## Where AI helped, and what I verified or changed myself (at least 120 characters)

Claude Code wrote most of the code, the tests and first drafts of the documentation, one
task at a time from a task list, under written rules (thin routers, one place per business
rule, real PostgreSQL in tests, no `now()` in business code). The architecture decisions
were mine and are recorded as ADRs; I also changed the product direction myself (removed the
administrator role, replaced passwords with emailed codes, chose the host). I did not accept
output on trust: every task had to pass its tests and the whole suite (1241 tests, including
concurrency tests with real commits and threads, such as ten customers booking one slot)
before a commit; I read the generated migrations by hand, because autogenerate cannot produce
exclusion constraints; and I checked each page by screenshot. That caught real mistakes, such
as a migration that created an enum twice, an update that would have been a 500, a deadlock
that returned a 500 instead of 409, invisible white-on-white buttons, a race test that proved
nothing, and tests that passed in CI but failed on my machine because they read my real mail
settings. `AI_USAGE.md` logs every phase: what I asked, what was produced, how I verified it,
what I changed or rejected, and the bugs caught.

## Length check

As drafted, the product description is about 1,030 characters (minimum 100) and the AI
answer about 1,250 (minimum 120). If the form has a maximum, shorten the first paragraph of
each rather than dropping the last sentence, which carries the specifics.
