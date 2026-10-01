# ADR 0013 — Email codes replace passwords

**Status:** accepted (2026-10-01, at the owner's request; reverses "email-code login" in
CLAUDE.md §8 and the Argon2 password design of P2.1)

## Context

Accounts had an email and a password. The owner asked for no passwords at all: both
signing up and signing in should end with typing a 6-digit code sent to the person's
email address. For a barbershop's customers this is less to remember and nothing for us
to store and protect, and it proves they can be reached, which the old sign-up never did.

Choices confirmed with the owner (asked, answered): codes go out over **SMTP using only
the standard library** (no new dependency), and a reviewer of any live demo **registers
their own email address**: no code is ever shown on screen and no demo password is
published.

## Decision

- **Two steps for everyone.** Step 1 asks for a code (`POST /auth/register` with a name,
  or `POST /auth/login`; the same on the web pages `/register` and `/login`). Step 2
  proves it (`POST /auth/verify`, web `/login/code`) and issues the same token and cookies
  as before. `users.password_hash` is dropped (migration `0008`); `pwdlib` is removed.
- **A sign-up creates the account only when the code is proven.** The name travels in the
  `login_codes` row, so an address nobody controls never gets an account.
- **The code.** Six digits from `secrets`, valid 10 minutes, usable once. Only a keyed
  hash (HMAC-SHA256 with the app secret, bound to the address) is stored. Asking again
  consumes the older codes: only the newest works. After 5 wrong tries a code is dead.
  A paste with a space or dash ("123 456") is accepted.
- **Three limits on guessing.** Per code (5 tries, in the database), per (client IP,
  email) on wrong codes (the existing in-memory limiter, now at `/auth/verify`), and per
  address on how many codes may be requested (5 per 10 minutes, counted in the database,
  so it holds across instances).
- **No account enumeration.** _Amended 2026-10-01: see "Amendment" below; sign-in requests no longer
  work this way._ Asking for a code answers 202 with the same body for every
  address. For an address with no account (or a deactivated one) a row is written and
  nothing is sent; the row is what the request limit counts, so the sixth request is 429
  for every address alike. Signing up with an address that has an account sends it an
  ordinary sign-in code instead of an "already registered" error. A wrong, expired, used,
  replaced or never-issued code is one `INVALID_CODE`.
- **A wrong try is committed by the service.** The one place a service commits
  (`auth.verify_code`): the request is about to fail, a failing request rolls back, and a
  counter that rolls back counts nothing. Everything else in the request has not changed
  yet, so nothing unrelated is committed with it.
- **The code is claimed with a guarded `UPDATE ... WHERE consumed_at IS NULL`**, the same
  idea as ADR 0008, so two requests carrying one code cannot both sign in
  (`tests/concurrency/test_sign_in_races.py`).
- **Sending (`app/core/mail.py`).** A `Mailer` protocol; `SmtpMailer` (`smtplib`, STARTTLS,
  SSL or none, 10 s timeout) when `SMTP_HOST` is set, otherwise `ConsoleMailer`, which logs
  the message so development and tests need no mail server. Production refuses to start
  without `SMTP_HOST`. The email is sent inside the request, after the code row is
  written; if the server refuses, the request fails with `503 EMAIL_SEND_FAILED` and the
  rollback removes the row, so no code exists that nobody received.
- **Barbers** are made by `create_barber` / the seed with no password; they sign in with a
  code to their address like everyone, so it must be an address they can read.
- **The login page's "demo barber" button** (Deviations log, 2026-10-01) now signs in
  without a code, outside production only, so the project can be tried without a mail
  server. The seeded `*.local` addresses cannot receive mail.

## Alternatives considered

- **Keep passwords and add the code as a second factor.** The owner asked to remove
  passwords; two mechanisms is more to explain and secure.
- **Magic links.** One click instead of typing six digits, but a link opened in another
  browser or app signs in the wrong place, and the owner asked for a code.
- **Send in the background (after the response).** Faster, and hides whether an address
  has an account by timing. But a failure would be invisible: the person waits for a code
  that was never sent. The timing difference is a known limitation (below).
- **Store codes in the outbox (ADR 0009) and send from a worker.** Right once there is a
  worker. A code has no booking to stay consistent with and is useless late, so a direct
  send with a visible failure is simpler today.
- **Keep an older code valid after asking again.** Friendlier when the first email is
  slow, but it multiplies the codes a guesser can hit at once.

## Consequences

- Whoever controls the inbox controls the account. There is no recovery path other than
  the email address itself; changing the address is not a feature.
- Someone who knows an address can make its owner wait: five requests burn the per-address
  limit for ten minutes, or five wrong tries kill the current code. They cannot sign in as
  the owner. Tolerable here; a CAPTCHA or per-IP request limit would be the next step.
- A sign-in with the real mail server takes as long as the SMTP conversation (up to 10 s
  before it fails), and an address with an account is measurably slower to answer than one
  without. Closing that gap needs background sending plus a worker (ADR 0009's next step).
- The IP limiter is still in process memory (see `docs/api.md`); the per-code and
  per-address limits are in the database and hold across instances.
- Production needs real SMTP credentials before anyone can sign in.
- Old password hashes are gone after the migration; downgrading restores an empty column,
  not the passwords.

## Amendment (2026-10-01): sign-in says when the address has no account

The owner tried the live site, typed an address with no account and got the code page as if
a code had been sent. A person who mistyped their address waits for an email that never comes.
At the owner's request, `POST /auth/login` (and the web sign-in form) now refuses an address
with no account: `404 ACCOUNT_NOT_FOUND`, shown in red under the email field ("No account with
this email address. Check the spelling, or create an account."), and a deactivated account gets
`401 ACCOUNT_INACTIVE`. Nothing is written or sent for either.

- **What it costs.** Anyone can now ask the sign-in form whether an address has an account.
  For a barbershop's customer list that is a small leak, accepted for a clear message.
  Sign-up is unchanged: signing up with an address that already has an account still sends it a
  sign-in code, so the sign-up form does not reveal it (and it stays the way to try an address
  without being told).
- **Mail abuse is not widened.** Mail is only sent to addresses that already have an account,
  as before, and the 5-codes-per-10-minutes limit per address is unchanged.
- **The limit rows.** Unknown addresses no longer write a `login_codes` row, so the request
  limit counts only real accounts; the "limit trips equally for every address" reasoning in the
  list above no longer applies to sign-in requests.
- **Not changed:** a wrong, expired, used or never-issued *code* is still one `INVALID_CODE`.
