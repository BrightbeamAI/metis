#!/bin/sh
# Walk through capture, review, and retrieval against the Compose stack, as five people and
# two agents. Needs curl and python3. Run from anywhere:  sh deploy/compose/try-it.sh
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
COMPOSE="docker compose -f $HERE/docker-compose.yml"
TOKEN_URL=http://localhost:8080/realms/metis/protocol/openid-connect/token
API=http://localhost:8000
WS="wsp_plant_$(date +%s)"

field() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }
person() {
  curl -sf -d grant_type=password -d client_id=metis-cli -d username="$1" \
       -d password="$1-dev-only" "$TOKEN_URL" | field "['access_token']"
}
call() {
  method=$1; token=$2; path=$3; shift 3
  curl -sf -X "$method" -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
       "$API$path" "$@"
}

printf 'Waiting for the Metis server and Keycloak'
until curl -sf "$API/readyz" >/dev/null 2>&1 \
      && curl -sf http://localhost:8080/realms/metis/.well-known/openid-configuration >/dev/null 2>&1
do printf '.'; sleep 2; done
echo

ANA=$(person ana); WENDY=$(person wendy); RHEA=$(person rhea); RAJ=$(person raj)
AUDREY=$(person audrey)
AGENT=$(curl -sf -d grant_type=client_credentials -d client_id=shift-assistant \
             -d client_secret=shift-assistant-dev-only "$TOKEN_URL" | field "['access_token']")
CMMS=$($COMPOSE exec -T metis metis server api-key create --id "cmms-$WS" \
         --uri agent:cmms-connector 2>/dev/null | tr -d '\r')

echo "1. Ana, a global admin, creates $WS and names its members."
call POST "$ANA" /v1/workspaces -d "{\"id\": \"$WS\", \"name\": \"Plant A\", \"site\": \"plant_a\",
  \"members\": [
    {\"uri\": \"human:wendy@example.com\", \"roles\": [\"worker\"]},
    {\"uri\": \"human:rhea@example.com\", \"roles\": [\"reviewer\"]},
    {\"uri\": \"human:raj@example.com\", \"roles\": [\"reviewer\", \"escalation\"]},
    {\"uri\": \"human:audrey@example.com\", \"roles\": [\"auditor\"]},
    {\"uri\": \"agent:shift-assistant\", \"roles\": [\"agent\"]},
    {\"uri\": \"agent:cmms-connector\", \"roles\": [\"capture\"]}]}" >/dev/null

echo "2. The maintenance-system connector reports what Wendy did differently."
WHISPER=$(call POST "$CMMS" "/v1/workspaces/$WS/observations" -d '{
  "observation_id": "WO-4471", "worker": "human:wendy@example.com", "category": "K7_sensory",
  "work_as_imagined": "Reduce load only when the alarm threshold is crossed.",
  "work_as_done": "Eased back earlier, when high load met a dull sound.",
  "context": {"equipment_family": "centrifugal_pump", "operating_mode": "high_load"}}')
WHISPER_ID=$(echo "$WHISPER" | field "['whisper_id']")
echo "   Metis asks Wendy: $(echo "$WHISPER" | field "['question']")"

echo "3. Wendy confirms the account in her own words and grants consent."
FRAGMENT=$(call POST "$WENDY" "/v1/workspaces/$WS/whispers/$WHISPER_ID/answer" \
  -d '{"response": "confirm", "consent": "granted"}' | field "['fragment']['fragment_id']")
echo "   Stored $FRAGMENT in the Evidence layer."

echo "4. Two reviewers approve it as an advisory cue."
call POST "$RHEA" "/v1/workspaces/$WS/fragments/$FRAGMENT/votes" -d '{
  "outcome": "promoted_to_advisory", "summary": "Clear, recurring cue.",
  "use_constraints": ["Present as an advisory cue only.",
                      "Ask the operator to confirm the sound before acting."]}' \
  | field "['status']" | sed 's/^/   Rhea: /'
call POST "$RAJ" "/v1/workspaces/$WS/fragments/$FRAGMENT/votes" \
  -d '{"outcome": "promoted_to_advisory"}' | field "['status']" | sed 's/^/   Raj: /'

echo "5. The shift assistant asks for guidance on the right pump."
call POST "$AGENT" "/v1/workspaces/$WS/retrieve" \
  -d '{"context": {"equipment_family": "centrifugal_pump", "operating_mode": "high_load"}}' \
  | field "['guidance'][0]['guidance']" | sed 's/^/   /'

echo "6. Audrey, an auditor, verifies the evidence chain."
call GET "$AUDREY" "/v1/workspaces/$WS/audit/verify" \
  | python3 -c "import json, sys; v = json.load(sys.stdin); print(f\"   {v['entries']} entries, verified: {v['verified']}, ledger agrees: {v['ledger_agrees']}\")"
