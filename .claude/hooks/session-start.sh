#!/bin/bash
# Cloud sessions start from a fresh container: put back what the sister apps need.
# Idempotent and quiet; each step reports one line.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$ROOT"

# 1. Python: both apps installed editable with their dev extras (pytest, ruff), so tests,
#    ruff and pyright resolve `returns.*` and `shipping.*` from anywhere.
pip_install() {
  python3 -m pip install --quiet --disable-pip-version-check "$@" 2>/dev/null \
    || python3 -m pip install --quiet --disable-pip-version-check --break-system-packages "$@"
}
pip_install -e "crooks-returns[dev]" -e "clive-shipping[dev]"
echo "session-start: python deps ok"

# 2. Pyright, the language server behind the pyright-lsp plugin.
if ! command -v pyright-langserver >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then uv tool install --quiet pyright; else pip_install pyright; fi
fi
echo "session-start: pyright $(pyright --version 2>/dev/null | tail -1 | awk '{print $2}')"

# 3. Browser trust: this environment intercepts TLS with its own CAs (listed in the proxy CA
#    bundle). Chromium reads the NSS store, which starts empty, so Playwright fails on
#    cdn.shopify.com (App Bridge, Polaris) with ERR_CERT_AUTHORITY_INVALID. Trust exactly
#    those CAs; verification stays on for everything else.
BUNDLE=/root/.ccr/ca-bundle.crt
if [ -f "$BUNDLE" ]; then
  if ! command -v certutil >/dev/null 2>&1; then
    (apt-get install -y -qq libnss3-tools >/dev/null 2>&1 \
      || (apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq libnss3-tools >/dev/null 2>&1)) || true
  fi
  if command -v certutil >/dev/null 2>&1; then
    NSS="sql:$HOME/.pki/nssdb"
    mkdir -p "$HOME/.pki/nssdb"
    [ -f "$HOME/.pki/nssdb/cert9.db" ] || certutil -N -d "$NSS" --empty-password
    python3 - "$BUNDLE" "$NSS" <<'PY'
import re, subprocess, sys
bundle, nss = sys.argv[1], sys.argv[2]
pems = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", open(bundle).read(), re.S)
added = 0
for i, pem in enumerate(pems):
    subj = subprocess.run(["openssl", "x509", "-noout", "-subject"], input=pem,
                          capture_output=True, text=True).stdout
    if "O = Anthropic" not in subj:
        continue  # public roots: Chromium already trusts its own
    subprocess.run(["certutil", "-A", "-d", nss, "-t", "C,,", "-n", f"env-ca-{i}"],
                   input=pem, text=True, capture_output=True)
    added += 1
print(f"session-start: browser trusts {added} environment CA(s)")
PY
  else
    echo "session-start: certutil unavailable; browser checks may fail on cdn.shopify.com"
  fi
fi

# 4. Session environment.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    # Shopify AI Toolkit scripts send queries and code to shopify.dev unless opted out.
    echo 'export OPT_OUT_INSTRUMENTATION=true'
  } >> "$CLAUDE_ENV_FILE"
fi
mkdir -p "$HOME/.config/shopify-ai-toolkit" && touch "$HOME/.config/shopify-ai-toolkit/opt-out"
echo "session-start: done"
