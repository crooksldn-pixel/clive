#!/usr/bin/env bash
# Used by scripts/test-setup.sh; see there.
# Stand-in for the Base44 CLI: records calls, answers like the real one.
set -euo pipefail
D="${FAKE_DIR:?}"; mkdir -p "$D/written"
echo "$*" >> "$D/calls.log"
args=("$@")
has() { for a in "${args[@]}"; do [ "$a" = "$1" ] && return 0; done; return 1; }
case "$1 ${2:-}" in
  "--version "*) echo "0.1.32" ;;
  "whoami "*) echo "owner@example.com" ;;
  "functions pull") mkdir -p "$D/code"; [ -e "$D/seeded" ] || { echo "// old builder version" > "$D/code/shopifyCreateSend"; touch "$D/seeded"; }
    for c in "$D"/code/*; do n="$(basename "$c")"; mkdir -p "base44/functions/$n"; cp "$c" "base44/functions/$n/entry.ts"; echo "$n written"; done ;;
  "functions deploy") shift 2; mkdir -p "$D/code"; for a in "$@"; do [[ "$a" == --* ]] && break; echo "$a" >> "$D/deployed"; cp "base44/functions/$a/entry.ts" "$D/code/$a"; echo "$a deployed"; done ;;
  "functions list") cat "$D/deployed" 2>/dev/null | sed 's/^/  /' ;;
  "secrets list") cat "$D/secret-names" 2>/dev/null | while read -r n; do echo "ℹ $n"; done; echo "Found secrets." ;;
  "secrets set")
    f=""; for ((i=0;i<${#args[@]};i++)); do [ "${args[$i]}" = "--env-file" ] && f="${args[$((i+1))]}"; done
    stat -c '%a' "$f" > "$D/envfile-perms"; cut -d= -f1 "$f" >> "$D/secret-names"; sort -u -o "$D/secret-names" "$D/secret-names"; cat "$f" >> "$D/secret-values"; echo "secrets set" ;;
  "sandbox ls") echo '{"entries":[{"path":"functions","name":"shopifyCreateSend.ts","type":"file"},{"path":"src/pages","name":"AdminInfluencer.jsx","type":"file"},"functions/partnerApi.ts",{"path":"functions/notOurs.ts"}]}' ;;
  "sandbox read") echo '{"files":[{"content":"// old builder code"}]}' ;;
  "sandbox write") p="$3"; mkdir -p "$D/written/$(dirname "$p")"; cat > "$D/written/$p"; echo '{"ok":true}' ;;
  "sandbox checkpoint") echo '{"ok":true}' ;;
  "exec "*)
    script="$(cat)"; echo "[Base44 SDK] noise line"
    case "$script" in
      *shopifyCheckConnection*) echo 'PARTNER_HUB_RESULT {"ok":true,"shop":{"name":"CROOKSLDN","myshopifyDomain":"5wn03t-nm.myshopify.com","currencyCode":"GBP"},"auth":"client credentials (auto-refreshing)","scopes":{"granted":[],"missing":[]},"webhooks":[{"topic":"FULFILLMENTS_CREATE","status":"created"},{"topic":"FULFILLMENTS_UPDATE","status":"created"},{"topic":"ORDERS_CANCELLED","status":"created"}],"warnings":[]}' ;;
      *shopifySyncCatalog*) echo 'PARTNER_HUB_RESULT {"ok":true,"products":25,"created":3,"updated":24,"hiddenMissing":0,"renamed":[{"from":"cb1-wash-jeans","to":"grey-wash-yard-jeans","interestsMoved":2}]}' ;;
      *shopifySyncUsage*) echo 'PARTNER_HUB_RESULT {"ok":false,"error":"Shopify: access denied","status":502}' ;;
      *shopifySyncTracking*) echo 'PARTNER_HUB_RESULT {"ok":true,"checked":1,"updated":1,"changes":[{"orderName":"CROOKS-1869","to":"cancelled"}]}' ;;
    esac ;;
  *) echo "fake: unhandled $*" >&2; exit 9 ;;
esac
