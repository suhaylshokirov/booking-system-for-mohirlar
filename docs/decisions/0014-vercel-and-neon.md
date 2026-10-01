# ADR 0014 — Deploy on Vercel with a Neon Postgres

**Status:** accepted (2026-10-01, P11.1; the owner chose Vercel, after ruling out Render)

## Context

The assignment wants a live URL. The owner chose **Vercel**. Vercel runs the app as a
serverless function (Fluid compute), not as a long-lived container, so the `Dockerfile`
and `docker-compose.yml` are not used there. They stay for local development. Vercel has
no database of its own; Postgres comes from the Marketplace. The app needs Postgres
with `btree_gist` (ADR 0001), so SQLite-style shortcuts were never an option.

## Decision

- **Host:** Vercel project `navbat`, connected to the GitHub repo (a push to `main`
  deploys). Vercel finds `app/main.py` and its `app` object with no configuration;
  `vercel.json` only pins the region (`iad1`, next to Neon) and a 30 s function limit.
  `.vercelignore` keeps tests, docs and every `.env*` file out of the upload.
- **Database:** Neon, added through the Vercel Marketplace (`navbat-db`). Vercel injects
  `DATABASE_URL` (pooled, through PgBouncer) and `DATABASE_URL_UNPOOLED`. The app uses the
  pooled one; Alembic and the seed use the unpooled one.
- **Neon URLs say `postgres://`.** `Settings` rewrites that prefix to
  `postgresql+psycopg://` so SQLAlchemy uses psycopg 3, not the missing psycopg2.
- **PgBouncer in transaction mode** may serve each transaction from a different server
  connection, so the engine sets `prepare_threshold=None` (no server-side prepared
  statements). Nothing in the app depends on session state: one request is one
  transaction (`app/core/db.py`) and the double-booking guarantee is the exclusion
  constraints, not a lock held across statements.
- **Migrations are run by hand**, from a developer machine against the unpooled URL
  (`alembic upgrade head`), then `python -m scripts.seed`. They do not run on deploy.
- **Production configuration** lives only in Vercel's environment: `APP_ENV=production`,
  a fresh `JWT_SECRET` (sensitive), the `SMTP_*` settings for Gmail (password sensitive),
  and `BARBER_EMAIL` set to the owner's real address.
- **The first barber is the owner.** Barbers sign in by emailed code (ADR 0013) and the
  demo shortcut does not exist in production, so a seeded `*.local` barber could never
  sign in. Reviewers sign up as customers with their own address.

## Alternatives considered

- **Run migrations in the Vercel build.** Fewer manual steps, but every preview build
  would migrate the production database, and a half-applied migration would be tied to a
  build log instead of an operator watching it.
- **A container host (Render, Railway, Fly).** Matches the Dockerfile better, but the
  owner chose Vercel. The stashed Render files were not used.
- **Supabase or a self-supplied database.** Equivalent Postgres; Neon is installed from
  the Vercel dashboard and wires its connection strings into the project.

## Consequences

- No process stays alive: no background worker (there is none; the outbox, ADR 0009, is
  still only written) and no in-process cache that survives a request.
- **Login rate limiting is weaker.** The per-(IP, email) limiter is in memory per
  instance (see README "Known limitations"). The cap of 5 wrong tries *per code* is in
  the database and holds everywhere. Behind Vercel's proxy the app may also see the
  proxy's address instead of the visitor's, which makes the IP half of that key coarser.
- **Cold starts.** The first request after idle time starts a function, and Neon's
  compute may be asleep too, so it can take a second or two longer.
- **Free-tier limits** (from the providers' docs, 2026-10-01). Neon Free: 0.5 GB storage,
  100 compute-hours a month per project, compute suspends after 5 minutes idle, no
  deletion for inactivity mentioned. Vercel Hobby: 1,000,000 function invocations and 4
  active-CPU hours a month, non-commercial use, a feature pauses up to 30 days when its
  limit is passed. The demo is far below each, and `vercel.json`'s 30 s function limit is
  under Hobby's 300 s maximum.
- **Postgres version drift.** Neon runs PostgreSQL 18; tests and Docker Compose run 16.
  The constraints and migrations ran unchanged on 18, but CI does not test it.
- Each deploy is immutable and the app is stateless, so rolling back is picking an older
  deployment in the dashboard. A migration is not rolled back by that.
