#!/usr/bin/env bash
# CROOKS Partner Hub: install the Shopify functions into the Base44 app from
# a terminal (a Linux server over SSH/Termius, a Mac, or Cowork's shell).
#
#   bash scripts/server-setup.sh           full setup (safe to re-run)
#   bash scripts/server-setup.sh --check   only test the Shopify connection
#   bash scripts/server-setup.sh --sync    run SYNC (catalogue, codes, tracking)
#   add --yes to answer yes to every question (for unattended runs; then the
#   Shopify credentials come from SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET or
#   SHOPIFY_ADMIN_ACCESS_TOKEN in the environment)
#
# It never creates a Shopify order, never runs a full `base44 deploy`, and
# never prints a secret.
set -euo pipefail

APP_ID="6a96ee08b3aefa8357c55ed7"
APP_URL="https://crooks-partner-hub.base44.app"
STORE_DOMAIN="5wn03t-nm.myshopify.com"
FUNCTIONS=(shopifyCreateSend shopifySyncCatalog shopifySyncTracking shopifySyncUsage sendMarkShipped shopifyCheckConnection shopifyWebhook portalCheckAvailable partnerApi shopifyCreateDiscount syncPromotions)
PROMPT_URL="https://github.com/crooksldn-pixel/clive/blob/claude/compassionate-planck-9xe5of/partner-hub/BASE44_PROMPT.md"
SAMPLE_VARIANT="53075854197079" # GREY CONVICT SWEATS - XS, used for a read-only stock check

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${PARTNER_HUB_STATE_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/crooks-partner-hub}"
API_URL="${PARTNER_HUB_API_URL:-$APP_URL/api/apps/$APP_ID/functions/partnerApi}"

MODE="setup"
YES="no"
for arg in "$@"; do
  case "$arg" in
    --check) MODE="check" ;;
    --sync) MODE="sync" ;;
    --yes|-y) YES="yes" ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then B=$'\e[1m'; G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; N=$'\e[0m'; else B=""; G=""; R=""; Y=""; N=""; fi
step() { printf '\n%s== %s ==%s\n' "$B" "$1" "$N"; }
ok() { printf '%s✔%s %s\n' "$G" "$N" "$1"; }
warn() { printf '%s!%s %s\n' "$Y" "$N" "$1"; }
die() { printf '%s✖ %s%s\n' "$R" "$1" "$N" >&2; exit 1; }
ask() { # ask "question" -> returns 0 for yes
  if [ "$YES" = "yes" ]; then return 0; fi
  local reply
  read -r -p "$1 [y/N] " reply </dev/tty || return 1
  [[ "$reply" =~ ^[Yy] ]]
}

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

# ---------------------------------------------------------------- tools
use_tools() {
  export PATH="$HERE/node_modules/.bin:$PATH"
  if [ -n "${BASE44_CLI:-}" ]; then
    # shellcheck disable=SC2206 # deliberate word splitting of a test override
    B44=($BASE44_CLI)
  else
    B44=("$HERE/node_modules/.bin/base44")
  fi
}

node_ok() {
  command -v node >/dev/null 2>&1 || return 1
  node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>20||(a===20&&b>=19)?0:1)'
}

ensure_tools() {
  step "Checking tools"
  command -v curl >/dev/null 2>&1 || die "curl is missing. Install it (e.g. sudo apt install curl) and re-run."
  if ! node_ok; then
    if [ -s "$HOME/.nvm/nvm.sh" ]; then
      # shellcheck disable=SC1091
      . "$HOME/.nvm/nvm.sh"
    fi
  fi
  if ! node_ok; then
    warn "Node.js 20.19 or newer is needed (found: $(node -v 2>/dev/null || echo none))."
    ask "Install Node.js 22 for this user with nvm (no sudo, nothing system-wide)?" ||
      die "Install Node.js 20.19+ and re-run."
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh"
    nvm install 22
  fi
  ok "Node $(node -v)"
  if [ ! -x "$HERE/node_modules/.bin/deno" ] || { [ -z "${BASE44_CLI:-}" ] && [ ! -x "$HERE/node_modules/.bin/base44" ]; }; then
    (cd "$HERE" && npm install --no-audit --no-fund --loglevel=error)
  fi
  use_tools
  ok "Base44 CLI $("${B44[@]}" --version 2>/dev/null | tail -1), Deno $(deno --version | head -1 | cut -d' ' -f2)"
}

# ------------------------------------------------------------- base44 helpers
b44() { (cd "$HERE" && "${B44[@]}" "$@" --app-id "$APP_ID"); }

# Runs a script as the signed-in admin and prints the line it marks RESULT.
exec_result() {
  local out
  out="$(printf '%s\n' "$1" | (cd "$HERE" && "${B44[@]}" exec --app-id "$APP_ID") 2>&1)" || true
  local line
  line="$(printf '%s\n' "$out" | grep '^PARTNER_HUB_RESULT ' | tail -1 | sed 's/^PARTNER_HUB_RESULT //')"
  if [ -z "$line" ]; then
    printf '%s\n' "$out" | tail -20 >&2
    return 1
  fi
  printf '%s\n' "$line"
}

invoke_script() { # invoke_script functionName jsonArgs
  cat <<EOF
try {
  const r = await base44.functions.invoke("$1", $2);
  console.log("PARTNER_HUB_RESULT " + JSON.stringify(r.data ?? r));
} catch (e) {
  const d = e?.response?.data ?? e?.data ?? {};
  console.log("PARTNER_HUB_RESULT " + JSON.stringify({ ok: false, error: d.error ?? d.message ?? e?.message ?? String(e), status: e?.response?.status ?? e?.status }));
}
EOF
}

json_get() { # json_get '<json>' 'js expression using d'
  node -e 'const d = JSON.parse(process.argv[1]); const v = (0, eval)("(d) => " + process.argv[2])(d); console.log(typeof v === "string" ? v : JSON.stringify(v));' "$1" "$2"
}

sign_in() {
  step "Signing in to Base44"
  echo "If you're not signed in yet, a code and a link appear below. Open the link on your phone"
  echo "or laptop, sign in as the owner of the Partner Hub app, and confirm the code. This window"
  echo "carries on by itself once you have."
  (cd "$HERE" && "${B44[@]}" whoami) || die "Couldn't sign in to Base44."
  ok "Signed in"
}

# ------------------------------------------------------------------ steps
verify_code() {
  step "Checking the code (type-check, tests, build, smoke test)"
  if [ "${PARTNER_HUB_SKIP_VERIFY:-}" = "1" ]; then warn "Skipped (PARTNER_HUB_SKIP_VERIFY=1, for script tests only)"; return; fi
  (cd "$HERE" && npm run --silent verify >"$STATE_DIR/verify.log" 2>&1) || {
    tail -30 "$STATE_DIR/verify.log" >&2
    die "The checks failed (full log: $STATE_DIR/verify.log). Nothing was deployed."
  }
  ok "$(grep -Eo '[0-9]+ passed \| [0-9]+ failed' "$STATE_DIR/verify.log" | sed 's/\x1b\[[0-9;]*m//g' | tail -1), smoke test passed"
  if command -v git >/dev/null 2>&1 && git -C "$HERE" rev-parse >/dev/null 2>&1; then
    git -C "$HERE" diff --quiet -- base44/functions ||
      die "The freshly built functions differ from the ones in the repository. Pull the latest branch and re-run."
    ok "Built functions match the repository"
  fi
}

BACKUP=""
backup() {
  step "Backing up what's in Base44 now"
  BACKUP="$STATE_DIR/backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP/base44"
  printf '{ "name": "partner-hub-backup" }\n' >"$BACKUP/base44/config.jsonc"
  if (cd "$BACKUP" && "${B44[@]}" functions pull --app-id "$APP_ID" >"$BACKUP/pull.log" 2>&1); then
    ok "Deployed functions saved to $BACKUP/base44/functions"
  else
    warn "Couldn't pull the deployed functions (see $BACKUP/pull.log). Carrying on."
  fi
  if b44 sandbox ls --recursive --max-depth 4 --json >"$BACKUP/sandbox-tree.json" 2>"$BACKUP/sandbox.log"; then
    ok "Builder file list saved"
  else
    warn "Couldn't list the builder's files (see $BACKUP/sandbox.log)."
    : >"$BACKUP/sandbox-tree.json"
  fi
}

ENVFILE=""
cleanup() { if [ -n "$ENVFILE" ]; then rm -f "$ENVFILE"; fi; }
trap cleanup EXIT

valid_value() { [[ "$1" =~ ^[A-Za-z0-9_.:-]+$ ]]; }

secrets() {
  step "Secrets"
  local existing
  existing="$(b44 secrets list 2>&1 || true)"
  has() { grep -Eq "(^|[^A-Z_])$1([^A-Z_]|$)" <<<"$existing"; }
  ENVFILE="$(umask 077 && mktemp)"
  printf 'SHOPIFY_STORE_DOMAIN=%s\n' "$STORE_DOMAIN" >>"$ENVFILE"

  local need_shopify="yes"
  if { has SHOPIFY_CLIENT_SECRET || has SHOPIFY_ADMIN_ACCESS_TOKEN; } &&
    [ -z "${SHOPIFY_CLIENT_SECRET:-}${SHOPIFY_ADMIN_ACCESS_TOKEN:-}" ]; then
    ok "Shopify credentials are already set in Base44"
    if [ "$YES" = "yes" ] || ! ask "Replace them?"; then need_shopify="no"; fi
  fi
  if [ "$need_shopify" = "yes" ]; then
    local id="${SHOPIFY_CLIENT_ID:-}" secret="${SHOPIFY_CLIENT_SECRET:-}" token="${SHOPIFY_ADMIN_ACCESS_TOKEN:-}"
    if [ -z "$id$secret$token" ]; then
      [ "$YES" = "yes" ] && die "--yes needs SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET (or SHOPIFY_ADMIN_ACCESS_TOKEN) in the environment."
      echo "From the Shopify Dev Dashboard app's Settings (README step 1)."
      echo "If you use an older custom app with an shpat_ token instead, leave the Client ID empty."
      read -r -p "Shopify Client ID: " id </dev/tty
      if [ -n "$id" ]; then
        read -r -s -p "Shopify Client secret (hidden): " secret </dev/tty; echo
      else
        read -r -s -p "Shopify admin access token shpat_... (hidden): " token </dev/tty; echo
      fi
    fi
    if [ -n "$token" ]; then
      valid_value "$token" || die "That token doesn't look right (letters, digits, _ only)."
      printf 'SHOPIFY_ADMIN_ACCESS_TOKEN=%s\n' "$token" >>"$ENVFILE"
      if [ -z "${SHOPIFY_WEBHOOK_SECRET:-}" ] && [ "$YES" != "yes" ]; then
        read -r -s -p "That app's API secret key, for webhooks (hidden, Enter to skip): " whs </dev/tty; echo
        [ -n "${whs:-}" ] && printf 'SHOPIFY_WEBHOOK_SECRET=%s\n' "$whs" >>"$ENVFILE"
      elif [ -n "${SHOPIFY_WEBHOOK_SECRET:-}" ]; then
        printf 'SHOPIFY_WEBHOOK_SECRET=%s\n' "$SHOPIFY_WEBHOOK_SECRET" >>"$ENVFILE"
      fi
    else
      { valid_value "$id" && valid_value "$secret"; } || die "Client ID and secret can't be empty or contain spaces."
      printf 'SHOPIFY_CLIENT_ID=%s\nSHOPIFY_CLIENT_SECRET=%s\n' "$id" "$secret" >>"$ENVFILE"
    fi
  fi

  local keyfile="$STATE_DIR/partner-api-key"
  if has PARTNER_API_KEY && [ -s "$keyfile" ]; then
    ok "CLIVE API key already set (copy kept in $keyfile)"
  elif has PARTNER_API_KEY && { [ "$YES" = "yes" ] || ! ask "A CLIVE API key is set in Base44 but there's no copy here. Make a new one (CLIVE would need the new one)?"; }; then
    warn "Keeping the existing CLIVE API key; the outside test is skipped."
  else
    local key
    key="$(openssl rand -hex 32 2>/dev/null || node -e 'console.log(require("crypto").randomBytes(32).toString("hex"))')"
    (umask 077 && printf '%s\n' "$key" >"$keyfile")
    printf 'PARTNER_API_KEY=%s\n' "$key" >>"$ENVFILE"
    ok "New CLIVE API key made; it's in $keyfile (CLIVE needs it)"
  fi

  b44 secrets set --env-file "$ENVFILE" >/dev/null
  rm -f "$ENVFILE"; ENVFILE=""
  ok "Secrets saved in Base44: $(b44 secrets list 2>&1 | grep -Eo '\b(SHOPIFY_[A-Z_]+|PARTNER_API_[A-Z_]+)\b' | sort -u | tr '\n' ' ')"
}

deploy() {
  step "Deploying the ${#FUNCTIONS[@]} functions"
  b44 functions deploy "${FUNCTIONS[@]}"
  local listed missing=()
  listed="$(b44 functions list 2>&1 || true)"
  for f in "${FUNCTIONS[@]}"; do grep -qw "$f" <<<"$listed" || missing+=("$f"); done
  [ ${#missing[@]} -eq 0 ] || die "Not showing as deployed: ${missing[*]}"
  ok "All deployed: ${FUNCTIONS[*]}"
}

builder_copies() {
  step "Builder copies of these functions"
  local tree="$BACKUP/sandbox-tree.json"
  if [ ! -s "$tree" ]; then
    warn "No builder file list, so skipping. If the builder later puts old versions back, re-run this script."
    return
  fi
  local paths
  paths="$(node -e '
    const names = new Set(process.argv[2].split(" "));
    const found = new Set();
    const walk = (v) => {
      if (typeof v === "string") {
        const m = v.match(/(?:^|\/)functions\/([A-Za-z0-9_]+)(?:\.(?:ts|js|jsx|tsx)|\/entry\.(?:ts|js))$/);
        if (m && names.has(m[1])) found.add(v.replace(/^\.?\//, ""));
      } else if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === "object") {
        if (typeof v.path === "string" && typeof v.name === "string" && !v.path.endsWith(v.name)) walk(v.path.replace(/\/$/, "") + "/" + v.name);
        Object.values(v).forEach(walk);
      }
    };
    walk(JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")));
    console.log([...found].sort().join("\n"));
  ' "$tree" "${FUNCTIONS[*]}" 2>/dev/null || true)"
  if [ -z "$paths" ]; then
    ok "None found in the builder's files; nothing to replace"
    return
  fi
  echo "The builder keeps its own copies here:"
  sed 's/^/   /' <<<"$paths"
  if ! ask "Replace them with the new versions (old ones are backed up first)?"; then
    warn "Left as they are. If the builder republishes them, the old code comes back; re-run to fix."
    return
  fi
  mkdir -p "$BACKUP/builder"
  while IFS= read -r p; do
    local name
    name="$(sed -E 's#.*functions/([A-Za-z0-9_]+)(/entry)?\.[a-z]+$#\1#' <<<"$p")"
    b44 sandbox read "$p" --json >"$BACKUP/builder/$(tr '/' '_' <<<"$p").json" 2>/dev/null || true
    b44 sandbox write "$p" --overwrite <"$HERE/base44/functions/$name/entry.ts" >/dev/null
    ok "Replaced $p"
  done <<<"$paths"
  b44 sandbox checkpoint --name "Partner Hub: Shopify functions" >/dev/null && ok "Saved a restore point in the builder"
}

confirm_deployed() {
  step "Checking Base44 is running this version"
  local tmp f changed=()
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/base44"
  printf '{ "name": "partner-hub-check" }\n' >"$tmp/base44/config.jsonc"
  if ! (cd "$tmp" && "${B44[@]}" functions pull --app-id "$APP_ID" >/dev/null 2>&1); then
    rm -rf "$tmp"
    warn "Couldn't read the deployed code, so this check was skipped."
    return
  fi
  for f in "${FUNCTIONS[@]}"; do
    # functions pull saves the code under the entry name in function.jsonc (main.ts), not always entry.ts
    local entry
    entry="$(node -e 'try { console.log(JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")).entry || "entry.ts") } catch { console.log("entry.ts") }' "$tmp/base44/functions/$f/function.jsonc")"
    diff -q -b -B "$tmp/base44/functions/$f/$entry" "$HERE/base44/functions/$f/entry.ts" >/dev/null 2>&1 || changed+=("$f")
  done
  rm -rf "$tmp"
  if [ ${#changed[@]} -eq 0 ]; then
    ok "All ${#FUNCTIONS[@]} functions match this version"
    return
  fi
  warn "Missing or changed in Base44 (the builder may have rewritten them): ${changed[*]}"
  ask "Deploy this version of them again?" || die "Not changed. Run bash scripts/server-setup.sh to put the right versions back."
  b44 functions deploy "${changed[@]}"
  ok "Redeployed: ${changed[*]}"
}

check_connection() {
  step "Connecting to Shopify"
  local res
  res="$(exec_result "$(invoke_script shopifyCheckConnection '{ registerWebhooks: true }')")" ||
    die "Couldn't run the connection check (output above). Is the account you signed in with the app's owner?"
  if [ "$(json_get "$res" 'd.ok === false && d.error ? "err" : "ok"')" = "err" ]; then
    die "Shopify connection failed: $(json_get "$res" 'd.error'). See README troubleshooting."
  fi
  ok "Shop: $(json_get "$res" 'd.shop.name + " (" + d.shop.myshopifyDomain + ", " + d.shop.currencyCode + ")"'), auth: $(json_get "$res" 'd.auth')"
  local missing
  missing="$(json_get "$res" 'd.scopes.missing.map(m => m.scope + " (" + m.why + ")").join(", ")')"
  if [ -n "$missing" ]; then
    printf '%s✖ Missing Shopify permissions:%s %s\n' "$R" "$N" "$missing"
    echo "  Add them on the app's Versions page in the Dev Dashboard, release, approve the update in"
    echo "  Shopify admin → Apps, then run: bash scripts/server-setup.sh --check"
    exit 1
  fi
  ok "All Shopify permissions granted"
  local lines
  lines="$(json_get "$res" '[...d.webhooks.map(w => "   webhook " + w.topic + ": " + w.status + (w.detail ? " (" + w.detail + ")" : "")), ...d.warnings.map(w => "   ! " + w)].join("\n")')"
  if [ -n "$lines" ]; then printf '%s\n' "$lines"; fi
}

outside_test() {
  step "Testing the CLIVE API from outside"
  local keyfile="$STATE_DIR/partner-api-key"
  if [ ! -s "$keyfile" ]; then warn "No local copy of the CLIVE key; skipped."; return; fi
  local key out
  key="$(cat "$keyfile")"
  out="$(curl -sS -m 60 "$API_URL" -H "X-Partner-Key: $key" -H 'Content-Type: application/json' \
    -d "{\"action\":\"checkStock\",\"items\":[{\"variantId\":\"$SAMPLE_VARIANT\"}]}" 2>&1)" || true
  if [ "$(json_get "$out" 'd.ok === true ? "y" : "n"' 2>/dev/null)" = "y" ]; then
    ok "partnerApi answered from the internet, with live Shopify stock: $(json_get "$out" 'd.data.stock.map(s => s.title + " = " + s.inStock).join(", ")')"
  else
    warn "partnerApi test didn't pass: $(head -c 300 <<<"$out")"
    warn "Ordering from the admin screens doesn't depend on this; CLIVE does."
  fi
}

run_sync() {
  step "SYNC (catalogue, affiliate codes, tracking, gift rules)"
  local fn res
  for fn in shopifySyncCatalog shopifySyncUsage shopifySyncTracking syncPromotions; do
    res="$(exec_result "$(invoke_script "$fn" '{}')")" || { warn "$fn didn't run (output above)"; continue; }
    if [ "$(json_get "$res" 'd.ok === false ? "err" : "ok"')" = "err" ]; then
      warn "$fn: $(json_get "$res" 'd.error')"
      continue
    fi
    case "$fn" in
      shopifySyncCatalog) ok "Catalogue: $(json_get "$res" 'd.products + " products, " + d.created + " new, " + d.hiddenMissing + " hidden (not in Shopify), " + d.renamed.length + " renamed with picks moved"')" ;;
      shopifySyncUsage) ok "Affiliate codes: $(json_get "$res" 'd.codes + " checked, " + d.updated + " updated" + (d.notInShopify.length ? ", not in Shopify: " + d.notInShopify.join(" ") : "")')" ;;
      shopifySyncTracking) ok "Tracking: $(json_get "$res" 'd.checked + " sends checked, " + d.updated + " updated" + (d.changes.length ? " (" + d.changes.map(c => (c.orderName || "?") + " → " + c.to).join(", ") + ")" : "")')" ;;
      syncPromotions) ok "Gift rules: $(json_get "$res" '(d.codes.length ? d.codes.join(" ") : "no codes yet") + (d.deactivated.length ? "; paused " + d.deactivated.join(" ") : "") + (d.activated.length ? "; unpaused " + d.activated.join(" ") : "") + (d.missingInShopify.length ? "; missing in Shopify: " + d.missingInShopify.join(" ") : "")')" ;;
    esac
  done
}

# ------------------------------------------------------------------- main
ensure_tools
case "$MODE" in
  check) sign_in; confirm_deployed; check_connection; outside_test; exit 0 ;;
  sync) sign_in; confirm_deployed; run_sync; exit 0 ;;
esac

verify_code
sign_in
backup
secrets
deploy
builder_copies
confirm_deployed
check_connection
outside_test

step "Screens and security"
echo "Paste the prompt from this page into the Base44 AI chat for the Partner Hub:"
echo "   $PROMPT_URL"
echo "It updates CREATE SEND / MARK SHIPPED / CHECK SHOPIFY and locks down the influencer data."
echo "Afterwards, --sync first checks the builder didn't touch the functions."
if [ "$YES" != "yes" ] && ask "Have you already pasted it and let Base44 finish? (then I'll run the first SYNC now)"; then
  run_sync
else
  echo "When it's done, run:  bash scripts/server-setup.sh --sync"
fi

step "Done"
ok "Functions are live. Backup of the previous versions: $BACKUP"
echo "Re-run any time; it only changes what needs changing."
