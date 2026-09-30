# Architecture Decision Records

Short records of the decisions that shape this project. Format for each:
**Context · Decision · Alternatives considered · Consequences.**

| # | Decision | Status |
|---|---|---|
| [0001](0001-exclusion-constraints.md) | PostgreSQL exclusion constraints prevent double booking | accepted (final in P6.5) |
| [0002](0002-computed-slots.md) | Slots are computed on the fly, not stored | accepted (P5.1) |
| [0003](0003-sync-sqlalchemy.md) | Sync SQLAlchemy 2.0 instead of async | accepted (P1.1) |
| 0004 | Server-rendered UI (Jinja2) with vanilla JS | planned (P8.1) |
| [0005](0005-jwt-cookie-bearer-csrf.md) | JWT in an HttpOnly cookie + Bearer, with CSRF double-submit | accepted (P2.4) |
| [0006](0006-half-open-ranges-and-utc.md) | Half-open ranges and UTC storage | accepted (P1.4; DST policy P4.1) |
| [0007](0007-booking-snapshots.md) | Price and duration snapshots on bookings | accepted (P1.3) |
| [0008](0008-guarded-status-updates.md) | Guarded (optimistic) status updates instead of row locks | accepted (P7.2; proven in P7.6) |
| 0009 | Transactional outbox for notifications | planned (P10.2) |
