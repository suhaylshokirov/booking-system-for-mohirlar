# ADR 0005 — JWT in an HttpOnly cookie and as a Bearer token, with CSRF double-submit

**Status:** accepted (P2.4)

## Context

Two kinds of client call the same services: the server-rendered web UI in a
browser, and API clients (curl, Swagger, scripts). A browser needs login to
survive page loads without the page handling the secret; an API client wants an
explicit header. Whatever the browser stores automatically is also sent
automatically on requests a *different* website triggers, which is the
cross-site request forgery (CSRF) problem.

## Decision

- Login returns a signed JWT (`sub`, `iat`, `exp`; HS256) **and** sets it in an
  `HttpOnly`, `SameSite=Lax` cookie (`Secure` in production). A request may
  authenticate with either; if both arrive, the Bearer header wins.
- The token carries only the user id. Role and active status are read from the
  database on every request, so demotion or deactivation applies immediately.
- **CSRF is prevented with a double-submit cookie.** Login also sets a
  non-HttpOnly `csrf_token` cookie holding a random value. Any unsafe method
  (POST, PUT, PATCH, DELETE) authenticated by the login cookie must echo it in
  an `X-CSRF-Token` header or a `csrf_token` form field, compared in constant
  time; otherwise `403 CSRF_FAILED`. A malicious site can make the browser send
  the cookie but cannot read it, so it cannot supply the copy.
- **Bearer requests are exempt.** Browsers never add an `Authorization` header
  on their own, so a forged cross-site request cannot carry one.
- The check is a dependency on the whole app, so a new endpoint cannot forget it.
  A separate always-on dependency exists for forms posted before login, which
  get a pre-session CSRF cookie (guards against "login CSRF", where an attacker
  signs the victim into the attacker's account).

## Alternatives considered

- **Token in `localStorage`, sent as Bearer only.** No CSRF at all, but any
  injected script can steal the token, and plain HTML forms (which we require to
  work without JavaScript) could not authenticate.
- **Server-side sessions.** Revocable on logout, but needs a session table or
  store and a lookup per request; the JWT plus a per-request user lookup gives
  the same immediate deactivation without extra storage.
- **`SameSite` alone.** `Lax` already blocks cross-site POSTs in current
  browsers, but it depends on browser behaviour and the site being same-site
  with its attackers' subdomains; the token is defence in depth.
- **Synchroniser token stored server-side, or a signed CSRF token bound to the
  session.** Stronger against an attacker who can set cookies on a sibling
  subdomain. Not needed for a single-origin deployment; it would be the upgrade.

## Consequences

- The web UI must put the token into every form (`csrf_token` hidden field) and
  JS `fetch` calls (`X-CSRF-Token` header). Missing it is a visible 403, not a
  silent failure (P8.2).
- A logged-in browser session that hits the API from Swagger UI will get
  `CSRF_FAILED` on POSTs unless it uses **Authorize** with a Bearer token; the
  error message says so.
- Logout cannot revoke a Bearer token already copied elsewhere; it expires on
  its own (`JWT_EXPIRE_MINUTES`). Acceptable for this scope; a token denylist
  would be the fix.
- Plain double-submit is vulnerable if an attacker can plant cookies on the
  site (a sibling subdomain, or a man-in-the-middle on http). `Secure` cookies
  in production and a single origin close that here.
