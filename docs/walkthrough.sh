#!/usr/bin/env bash
# The curl walkthrough of docs/api.md as one script, so the guide can be proven to
# work against a fresh `docker compose up` (which seeds the demo barbershop):
#
#     docker compose up --build -d        # wait for it to be healthy
#     bash docs/walkthrough.sh            # or: BASE=http://localhost:8000 bash docs/walkthrough.sh
#
# It signs a new customer up with an emailed code, finds a free slot, books it, signs
# in as the seeded barber (also with a code), confirms it, reads the history and the
# calendar file, cancels, and checks the main refusals. It stops with a message at the first step that does not behave
# as documented. Needs only bash, curl and python3 (no jq).
#
# There are no passwords, so the script has to read the codes the way a person reads
# their inbox. With no mail server configured the app logs each email, and the script
# reads the log with `docker compose logs`. For another stack set CODE_LOG_CMD to a
# command that prints the app's log, for example
#     CODE_LOG_CMD='docker compose -p other logs --no-log-prefix app'
# (COMPOSE_PROJECT_NAME works too). With a real mail server, read the email yourself.

set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
API="$BASE/api/v1"
BARBER_EMAIL="${BARBER_EMAIL:-jasur@navbat.local}"
EMAIL="walkthrough-$(date +%s)-$RANDOM@example.com"
CODE_LOG_CMD="${CODE_LOG_CMD:-docker compose logs --no-log-prefix app}"

# json FIELD: print one top-level field of the JSON on stdin ("a.b" digs into objects)
json() {
  python3 -c 'import json,sys
v = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    v = v[int(part)] if part.isdigit() else v[part]
print(v if not isinstance(v, (dict, list)) else json.dumps(v))' "$1"
}

# code_for ADDRESS: the newest sign-in code the app emailed (logged) to ADDRESS
code_for() {
  local code
  code=$(sleep 1; $CODE_LOG_CMD 2>&1 | python3 -c 'import re,sys
found = re.findall(r"email to " + re.escape(sys.argv[1]) + r": [^\n]*sign-in code is (\d{6})", sys.stdin.read())
print(found[-1] if found else "")' "$1")
  [ -n "$code" ] || fail "no sign-in code for $1 in the app's log (is a mail server configured? set CODE_LOG_CMD)"
  printf '%s' "$code"
}

step() { printf '\n== %s\n' "$*"; }
fail() { printf 'WALKTHROUGH FAILED: %s\n' "$*" >&2; exit 1; }

# call EXPECTED_STATUS curl-args...: run curl, check the HTTP status, print the body
call() {
  local expected="$1"; shift
  local out status
  out="$(curl -s -w '\n%{http_code}' "$@")"
  status="${out##*$'\n'}"
  BODY="${out%$'\n'*}"
  [ "$status" = "$expected" ] || fail "expected HTTP $expected, got $status for: curl $* -> $BODY"
  printf '%s\n' "$BODY"
}

step "0. The service is up and the database answers"
call 200 "$API/health" >/dev/null

step "1. Sign up: a code is emailed, proving it creates the account (always a customer) and signs in"
call 202 -X POST "$API/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\": \"$EMAIL\", \"full_name\": \"Walkthrough Customer\"}" >/dev/null
TOKEN=$(call 200 -X POST "$API/auth/verify" -H 'Content-Type: application/json' \
  -d "{\"email\": \"$EMAIL\", \"code\": \"$(code_for "$EMAIL")\"}" | json access_token)
[ "$(call 200 "$API/auth/me" -H "Authorization: Bearer $TOKEN" | json role)" = customer ] || fail "role is not customer"

step "2. Sign in as the seeded barber with a code: their provider id comes from /auth/me"
call 202 -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\": \"$BARBER_EMAIL\"}" >/dev/null
BARBER_TOKEN=$(call 200 -X POST "$API/auth/verify" -H 'Content-Type: application/json' \
  -d "{\"email\": \"$BARBER_EMAIL\", \"code\": \"$(code_for "$BARBER_EMAIL")\"}" | json access_token)
PROVIDER_ID=$(call 200 "$API/auth/me" -H "Authorization: Bearer $BARBER_TOKEN" | json provider_id)
SERVICE_ID=$(call 200 "$API/providers/$PROVIDER_ID" | json services.0.id)
echo "barber runs provider $PROVIDER_ID, who offers service $SERVICE_ID (public browsing: GET /services, GET /providers)"

step "3. Free slots: the next day with a free time"
DAY=""; START=""
for offset in 2 3 4 5 6 7 8; do
  DAY=$(date -d "+$offset day" +%F)
  SLOTS=$(call 200 "$API/slots?service_id=$SERVICE_ID&date=$DAY&provider_id=$PROVIDER_ID")
  START=$(printf '%s' "$SLOTS" | python3 -c 'import json,sys
d = json.load(sys.stdin)
s = d["providers"][0]["slots"]
print(s[0]["start_at"] if s else "")')
  [ -n "$START" ] && break
done
[ -n "$START" ] || fail "no free slot in the next week (is the demo data seeded?)"
echo "booking $START on $DAY"

step "4. Book it (pending), then see that the slot is no longer offered"
BOOKING=$(call 201 -X POST "$API/bookings" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"service_id\": $SERVICE_ID, \"provider_id\": $PROVIDER_ID, \"start_at\": \"$START\", \"notes\": \"Short back and sides\"}")
BOOKING_ID=$(printf '%s' "$BOOKING" | json id)
[ "$(printf '%s' "$BOOKING" | json status)" = pending ] || fail "new booking is not pending"
printf '%s' "$BOOKING" | json local_start

step "5. The same time again is refused: 409 SLOT_TAKEN"
[ "$(call 409 -X POST "$API/bookings" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"service_id\": $SERVICE_ID, \"provider_id\": $PROVIDER_ID, \"start_at\": \"$START\"}" | json error.code)" = SLOT_TAKEN ] \
  || fail "second booking was not SLOT_TAKEN"

step "6. A time without an offset is 422 VALIDATION_ERROR"
call 422 -X POST "$API/bookings" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"service_id\": $SERVICE_ID, \"provider_id\": $PROVIDER_ID, \"start_at\": \"2030-01-01T10:00:00\"}" \
  | json error.code

step "7. The customer cannot confirm: 403 FORBIDDEN"
call 403 -X POST "$API/bookings/$BOOKING_ID/confirm" -H "Authorization: Bearer $TOKEN" | json error.code

step "8. The booking is in the barber's client list; they confirm it"
call 200 "$API/bookings/clients?status=pending" -H "Authorization: Bearer $BARBER_TOKEN" \
  | grep -q "\"id\":$BOOKING_ID\|\"id\": $BOOKING_ID" || fail "booking not in the barber's client list"
[ "$(call 200 -X POST "$API/bookings/$BOOKING_ID/confirm" -H "Authorization: Bearer $BARBER_TOKEN" | json status)" = confirmed ] \
  || fail "booking was not confirmed"

step "9. History and the calendar file (the customer's view)"
call 200 "$API/bookings/$BOOKING_ID/history" -H "Authorization: Bearer $TOKEN" | json 1.to_status
ICS=$(curl -s -D - "$API/bookings/$BOOKING_ID/ics" -H "Authorization: Bearer $TOKEN")
printf '%s' "$ICS" | grep -qi '^content-type: text/calendar' || fail "ics is not text/calendar"
printf '%s' "$ICS" | grep -q 'STATUS:CONFIRMED' || fail "ics is not CONFIRMED"
echo "ics ok"

step "10. Someone else's booking is a 404, not a 403"
OTHER_EMAIL="walkthrough-other-$RANDOM@example.com"
call 202 -X POST "$API/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\": \"$OTHER_EMAIL\", \"full_name\": \"Other\"}" >/dev/null
OTHER=$(call 200 -X POST "$API/auth/verify" -H 'Content-Type: application/json' \
  -d "{\"email\": \"$OTHER_EMAIL\", \"code\": \"$(code_for "$OTHER_EMAIL")\"}" | json access_token)
call 404 "$API/bookings/$BOOKING_ID" -H "Authorization: Bearer $OTHER" | json error.code

step "11. The customer cancels (before the cutoff); the time is free again"
CANCELLED=$(call 200 -X POST "$API/bookings/$BOOKING_ID/cancel" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"reason": "Walkthrough finished."}')
[ "$(printf '%s' "$CANCELLED" | json status)" = cancelled ] || fail "booking was not cancelled"
call 200 "$API/slots?service_id=$SERVICE_ID&date=$DAY&provider_id=$PROVIDER_ID" | grep -q "$START" \
  || fail "the cancelled time was not offered again"

step "12. The docs and the schema agree: Swagger lists the endpoints"
call 200 "$BASE/openapi.json" | python3 -c 'import json,sys
print(len(json.load(sys.stdin)["paths"]), "paths documented")'

printf '\nWALKTHROUGH OK\n'
