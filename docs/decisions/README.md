# Architecture Decision Records

Short records of the decisions that shape this project. Format for each:
**Context · Decision · Alternatives considered · Consequences.**

| # | Decision | Status |
|---|---|---|
| 0001 | PostgreSQL exclusion constraints prevent double booking | planned (P1.7, final P6.5) |
| 0002 | Slots are computed on the fly, not stored | planned (P5.1) |
| 0003 | Sync SQLAlchemy 2.0 instead of async | planned (P1.1) |
| 0004 | Server-rendered UI (Jinja2) with vanilla JS | planned (P8.1) |
| 0005 | JWT in an HttpOnly cookie + Bearer, with CSRF double-submit | planned (P2.4) |
| 0006 | Half-open ranges and UTC storage | planned (P1.4, P4.1) |
| 0007 | Price and duration snapshots on bookings | planned (P1.3) |
| 0008 | Guarded (optimistic) status updates instead of row locks | planned (P7.2) |
| 0009 | Transactional outbox for notifications | planned (P10.2) |
