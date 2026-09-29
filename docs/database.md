# Database

_Skeleton — completed in P1.7 and kept current by every schema change._

## ER diagram
_Mermaid `erDiagram`._

## Conventions
_P1.1._ `timestamptz` in UTC everywhere; integer money (UZS); constraint
naming convention; soft deactivation instead of deletes.

## Tables
_One subsection per table: purpose, columns of note._

## Constraints and indexes
_Every constraint and index, and **why** it exists._

## The exclusion constraints, in plain language
_How `EXCLUDE USING gist (provider_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)`
makes double booking impossible, and why only pending/confirmed bookings count._

## Snapshot fields
_Why bookings copy price and duration at booking time._
