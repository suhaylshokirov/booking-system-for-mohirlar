# ADR 0004 — Server-rendered UI (Jinja2) with vanilla JS

**Status:** accepted (P8.1)

## Context

Navbat needs a browser UI for customers (pick a service, see free slots, book,
see history) and for barbers (services, profile, hours, bookings).
The graded core is the backend: the booking rules, the double-booking
guarantee, and the API. The UI has to be usable and pleasant, work without
JavaScript (CLAUDE.md rule 13), and never become a second place where
business rules live (rule 1). One developer, a short deadline, and every line
has to be explainable.

## Decision

Render HTML on the server with **Jinja2** from routers in `app/web/`, which
call the same `app/services/` functions as the JSON API. Add behaviour with
one small **vanilla JavaScript** file (`app/static/js/app.js`, a single IIFE)
and one stylesheet (`app/static/css/app.css`) that owns every design token and
shared component. No build step, no framework, no npm.

Every form is a real `<form>` that posts to the server; JavaScript only
improves it (the confirm dialog, later the live slot picker that swaps in a
server-rendered partial). Errors outside `/api/` render an HTML error page,
errors under `/api/` keep the JSON envelope (`app/core/errors.py` takes a
`render_page` function from `app/web/errors.py`, so `core` has no template
code).

## Alternatives considered

- **A single-page app (React/Vue) on top of the JSON API.** The API already
  exists, so this is tempting. Costs: a Node toolchain and build in Docker and
  CI, client-side routing, auth and form state duplicated in the browser,
  validation messages re-implemented in JS, and nothing works without
  JavaScript. It would roughly double the code to review for no requirement.
- **htmx or Alpine.js.** Would shorten the live slot picker. A new dependency
  (CLAUDE.md §3 lists none) for about forty lines of `fetch` + `innerHTML`
  we can write and explain ourselves.
- **Serve the UI from a separate app.** Two deployables and CORS for a
  single-business tool.

## Consequences

- One source of truth: a validation rule or status transition is written once
  in a service and both the API and the pages obey it. A page cannot book a
  slot the API would refuse.
- Works with JavaScript off; the tests assert the markup, not a browser.
- The API stays fully usable on its own (Swagger, API clients), which is also
  what the grader reads.
- Some interactions are full page loads. Where that hurts (the slot picker),
  JS fetches a server-rendered fragment instead of rebuilding HTML in the
  browser, so the template is still the only renderer.
- The design system was first ported from the owner's earlier project
  (Theoria) by copying, never by reference (rule 14). On 2026-09-30 it was
  replaced by Navbat's own "tile and ticket" system (see
  `docs/architecture.md`, Visual language); the "one colour means committed or
  selected" rule (rule 12) carried over, with saffron in place of lime. The
  redesign touched only templates, CSS and one formatting-only JS function,
  which is the point of this decision: no route or service changed.
