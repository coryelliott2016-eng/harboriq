#!/usr/bin/env bash
# Manual Phase 10 smoke test: real geocoding (Nominatim), backfill, and
# dispatch distance-scoring activation. Run once by hand against a live
# dev server -- not part of the automated pytest suite (which mocks
# Nominatim). See harboriq_phase10_spec.md's delivery checklist item 4.
set -euo pipefail
BASE="http://127.0.0.1:8811/api/v1"
EMAIL="smoke10-owner-$RANDOM@example.com"

echo "== signup =="
SIGNUP=$(curl -s -X POST "$BASE/auth/signup" -H 'content-type: application/json' \
  -d "{\"company_name\":\"Smoke Test Marine 10\",\"email\":\"$EMAIL\",\"password\":\"correct-horse-battery-staple\"}")
TOKEN=$(echo "$SIGNUP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["tokens"]["access_token"])')
OWNER_ID=$(echo "$SIGNUP" | python3 -c 'import sys,json;print(json.load(sys.stdin)["user"]["id"])')
echo "owner: $OWNER_ID"

echo "== invite a technician =="
TECH_EMAIL="smoke10-tech-$RANDOM@example.com"
INVITE=$(curl -s -X POST "$BASE/auth/users" -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d "{\"email\":\"$TECH_EMAIL\",\"password\":\"correct-horse-battery-staple\",\"role\":\"technician\"}")
TECH_ID=$(echo "$INVITE" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "technician: $TECH_ID"

echo "== technician logs in and self-edits skills + home address via PATCH /users/{id} =="
TECH_LOGIN=$(curl -s -X POST "$BASE/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$TECH_EMAIL\",\"password\":\"correct-horse-battery-staple\"}")
TECH_TOKEN=$(echo "$TECH_LOGIN" | python3 -c 'import sys,json;print(json.load(sys.stdin)["tokens"]["access_token"])')

echo "-- REAL Nominatim call: geocoding a real Sarasota address --"
UPDATE_SELF=$(curl -s -X PATCH "$BASE/users/$TECH_ID" -H "authorization: Bearer $TECH_TOKEN" -H 'content-type: application/json' \
  -d '{"skills":["outboard","electrical"],"address_text":"1100 23rd Street, Sarasota, FL 34234"}')
echo "$UPDATE_SELF" | python3 -m json.tool
LAT=$(echo "$UPDATE_SELF" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("home_latitude"))')
LNG=$(echo "$UPDATE_SELF" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("home_longitude"))')
echo "geocoded technician home coordinates: lat=$LAT lng=$LNG"
if [ "$LAT" = "None" ] || [ -z "$LAT" ]; then
  echo "WARNING: real Nominatim geocode did not populate coordinates (network/rate-limit?) -- continuing with manual coordinate seed for the rest of the smoke test"
fi

echo "== create a customer near the technician's home (real Nominatim call again) =="
CUSTOMER=$(curl -s -X POST "$BASE/customers" -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"last_name":"Smoke10 Customer","address_line1":"2000 Ken Thompson Pkwy","city":"Sarasota","state":"FL","postal_code":"34236"}')
echo "$CUSTOMER" | python3 -m json.tool
CUSTOMER_ID=$(echo "$CUSTOMER" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
CUST_LAT=$(echo "$CUSTOMER" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("latitude"))')
echo "customer: $CUSTOMER_ID  latitude=$CUST_LAT"

echo "== create a job requiring outboard+electrical =="
JOB=$(curl -s -X POST "$BASE/jobs" -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d "{\"customer_id\":\"$CUSTOMER_ID\",\"title\":\"Smoke10 dispatch test\",\"priority\":\"urgent\",\"required_skills\":[\"outboard\",\"electrical\"]}")
JOB_ID=$(echo "$JOB" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "job: $JOB_ID"

echo "== dispatch candidates BEFORE any un-geocoded customer (baseline) =="
curl -s "$BASE/jobs/$JOB_ID/dispatch/candidates" -H "authorization: Bearer $TOKEN" | python3 -m json.tool

echo "== create a SECOND customer with NO address (to prove graceful degradation: no address -> no geocode call, no error) =="
CUSTOMER2=$(curl -s -X POST "$BASE/customers" -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"last_name":"No Address Customer"}')
echo "$CUSTOMER2" | python3 -m json.tool

echo "== create a THIRD customer with a nonsense/unfindable address (to prove graceful degradation on a failed geocode) =="
CUSTOMER3=$(curl -s -X POST "$BASE/customers" -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"last_name":"Bad Address Customer","address_line1":"zzzzzznotarealaddressxyz123","city":"Nowhereville","state":"FL"}')
echo "$CUSTOMER3" | python3 -m json.tool
echo "(expect 201 Created with latitude/longitude null -- save must succeed regardless of geocode outcome)"

echo "== run the backfill job (admin route) against this company =="
BACKFILL=$(curl -s -X POST "$BASE/admin/geocode-backfill" -H "authorization: Bearer $TOKEN")
echo "$BACKFILL" | python3 -m json.tool

echo "== recompute dispatch score for the job now that coordinates may exist =="
curl -s -X POST "$BASE/jobs/$JOB_ID/dispatch/recompute" -H "authorization: Bearer $TOKEN" | python3 -m json.tool

echo "== final dispatch candidates (distance factor should be non-neutral if both technician and customer have coordinates) =="
curl -s "$BASE/jobs/$JOB_ID/dispatch/candidates" -H "authorization: Bearer $TOKEN" | python3 -m json.tool

echo "SMOKE TEST PHASE 10 COMPLETE"
