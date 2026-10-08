#!/usr/bin/env bash
# Tests scripts/server-setup.sh against a stand-in Base44 CLI and CLIVE API
# (test/setup/). Nothing here talks to Base44 or Shopify. Linux (GNU stat).
#   npm run test:setup
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"
trap 'kill "${API:-}" 2>/dev/null; rm -rf "$T"' EXIT
fails=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

export FAKE_DIR="$T/fake" PARTNER_HUB_STATE_DIR="$T/state" BASE44_CLI="$HERE/test/setup/fake-base44.sh"
export PARTNER_HUB_API_URL="http://127.0.0.1:8991/" PARTNER_HUB_SKIP_VERIFY=1 NO_COLOR=1
mkdir -p "$FAKE_DIR" "$PARTNER_HUB_STATE_DIR"
run() { bash "$HERE/scripts/server-setup.sh" "$@" >"$T/out" 2>&1; echo $? >"$T/code"; }

echo "first run (--yes, credentials from the environment)"
( while [ ! -s "$T/state/partner-api-key" ]; do sleep 0.2; done; exec python3 "$HERE/test/setup/fake-api.py" 8991 "$T/state/partner-api-key" ) &
API=$!
SHOPIFY_CLIENT_ID=cid SHOPIFY_CLIENT_SECRET=csecret123 run --yes
check "exits 0" '[ "$(cat "$T/code")" = 0 ]'
check "sets the four secrets" '[ "$(tr "\n" " " <"$FAKE_DIR/secret-names")" = "PARTNER_API_KEY SHOPIFY_CLIENT_ID SHOPIFY_CLIENT_SECRET SHOPIFY_STORE_DOMAIN " ]'
check "secret file was private" '[ "$(cat "$FAKE_DIR/envfile-perms")" = 600 ]'
check "never prints the Shopify secret" '! grep -q csecret123 "$T/out"'
check "CLIVE key saved privately" '[ "$(stat -c %a "$T/state/partner-api-key")" = 600 ]'
check "deploys all nine by name" '[ "$(sort -u "$FAKE_DIR/deployed" | wc -l)" = 9 ]'
check "never runs a full deploy or --force" '! grep -Eq "^deploy|--force|entities push" "$FAKE_DIR/calls.log"'
check "backs up the old code first" 'grep -q "old builder version" "$T"/state/backup-*/base44/functions/shopifyCreateSend/entry.ts'
check "replaces builder copies with the built file" 'cmp -s "$FAKE_DIR/written/functions/shopifyCreateSend.ts" "$HERE/base44/functions/shopifyCreateSend/entry.ts"'
check "leaves other builder files alone" '[ ! -e "$FAKE_DIR/written/functions/notOurs.ts" ]'
check "connection and outside API pass" 'grep -q "All Shopify permissions granted" "$T/out" && grep -q "partnerApi answered" "$T/out"'

echo "re-run keeps existing credentials and key"
# shellcheck disable=SC2034 # read inside check's eval
key_before="$(cat "$T/state/partner-api-key")"
run --yes
check "exits 0" '[ "$(cat "$T/code")" = 0 ]'
check "key unchanged" '[ "$(cat "$T/state/partner-api-key")" = "$key_before" ]'
check "Shopify secret not re-sent" '[ "$(grep -c "^SHOPIFY_CLIENT_SECRET=" "$FAKE_DIR/secret-values")" = 1 ]'

echo "--sync after the builder rewrote a function"
echo "// rewritten" >"$FAKE_DIR/code/sendMarkShipped"
run --sync --yes
check "exits 0" '[ "$(cat "$T/code")" = 0 ]'
check "redeploys only the changed one" 'grep -q "Redeployed: sendMarkShipped$" "$T/out"'
check "restored" 'cmp -s "$FAKE_DIR/code/sendMarkShipped" "$HERE/base44/functions/sendMarkShipped/entry.ts"'
check "reports the sync" 'grep -q "CROOKS-1869 → cancelled" "$T/out" && grep -q "shopifySyncUsage: Shopify: access denied" "$T/out"'

echo "--check with a missing Shopify permission"
sed 's/"missing":\[\]/"missing":[{"scope":"read_discounts","why":"affiliate code usage"}]/' "$BASE44_CLI" >"$T/fake-missing.sh"
chmod +x "$T/fake-missing.sh"
BASE44_CLI="$T/fake-missing.sh" run --check
check "exits 1" '[ "$(cat "$T/code")" = 1 ]'
check "names the scope and the fix" 'grep -q "read_discounts (affiliate code usage)" "$T/out" && grep -q "Versions page" "$T/out"'

echo "--yes without credentials on a fresh app"
rm -rf "$FAKE_DIR" "$T/state"; mkdir -p "$FAKE_DIR" "$T/state"
run --yes
check "refuses, explaining what's needed" '[ "$(cat "$T/code")" = 1 ] && grep -q "needs SHOPIFY_CLIENT_ID" "$T/out"'

[ "$fails" = 0 ] && echo "all setup-script checks passed" || { echo "$fails setup-script check(s) failed"; exit 1; }
