# ADR 0012 — A barber's photo is uploaded and stored in Postgres

**Status:** accepted (P10.7, 2026-10-01)

## Context

The owner asked for barber photos, so customers can see who they are booking.
Image uploads were on the out-of-scope list (CLAUDE.md §8), so this is a change
of plan, and the owner chose between two options: (a) the barber uploads a file,
or (b) the barber pastes a link to an image hosted somewhere else. They chose
uploads. Still open: where the bytes live, and how an upload is checked.

The app runs as one container next to Postgres, and the deployment target (P11)
is not settled yet. A barber has one photo, and a shop has a handful of barbers.

## Decision

- **The bytes live on the provider row**: `providers.photo` (`bytea`) and
  `providers.photo_type`, both set or both NULL. The column is `deferred`, so
  listing providers never reads the images; only `GET /providers/{id}/photo`
  does.
- **The type is judged by the file's content.** The first bytes must be a JPEG,
  PNG or WebP signature (`services/provider_photo.image_type`); the file name
  and the client's Content-Type are ignored, and the stored type is the one the
  bytes prove. SVG is refused: it is a document that can run script.
- **At most 2 MB.** The router reads one byte past the cap and stops, so a huge
  upload is refused without being held in memory whole.
- **The database repeats the rules**: CHECKs for "both or neither", the three
  types, and `octet_length(photo) <= 2 MB`.
- **Served by the API** at `GET /providers/{id}/photo` with the stored type,
  `X-Content-Type-Options: nosniff` and a day of caching. Every provider
  response has a `photo_url` with a `v=` version that changes when the provider
  row does, so a new photo shows at once despite the cache. A hidden provider's
  photo is the same 404 as the provider for everyone but barbers.
- **Upload and removal** are `PUT` / `DELETE /providers/{id}/photo` for the barber
  themselves (multipart field `photo`), and a file field plus a "Remove my photo"
  box on the barber's profile form, saved in the same savepoint as the rest of
  the form.
- **No resizing.** That needs an imaging library (Pillow), which is a new
  dependency to justify. Pages show the photo small, `object-fit: cover`, and
  2 MB caps the cost.

## Alternatives considered

- **A link to an image elsewhere (option b).** No upload handling at all, but the
  picture depends on a third-party host, can break or change at any time, and
  makes every customer's browser call that host.
- **Files on disk (an upload directory or a volume).** Smaller rows, but one more
  thing to back up and mount, and it is lost on a redeploy to a host without a
  persistent disk. The database is already backed up and already shared by
  every app instance.
- **Object storage (S3 and similar).** The right answer at scale; credentials,
  a bucket and a dependency for a handful of small images is not.
- **A separate `provider_photos` table.** Keeps the bytes off the provider row,
  but `deferred` already keeps them out of every query that does not ask, and
  one table is simpler to explain.

## Consequences

- Backups and `make reset` include the photos; there is nothing else to copy.
- Each photo costs up to 2 MB of database space and is read from Postgres on a
  cache miss. Fine for a few barbers; a shop with thousands of images would move
  them to object storage and keep only the URL here.
- A barber who uploads a very large-dimension but small-file image gets it shown
  as is (no resizing); browsers scale it.
- The seed gives each demo barber a stock portrait (`scripts/seed_photos/`,
  Unsplash License) whenever they have none, including databases seeded before
  photos existed. So a demo barber who removes their photo gets it back the next
  time the seed runs (Docker runs it on every start); a photo they uploaded is
  never replaced. Barbers who are not part of the demo are never touched.
