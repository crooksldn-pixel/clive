# CROOKS Shipping physical printing

The Windows appliance stays a PrintNode client; the existing production Shipping container
makes PrintNode API calls. No purchase path was changed. Implementation is based on
`claude/compassionate-dirac-44hnee`, verified base `9b0a44c7faf892f7a10d75557288736d05374cbd`.

## Existing document path

Easyship `documents()` reads the paid shipment with label=4x6, commercial_invoice=A4,
packing_slip=none, and decodes its category=label bytes. Parcel2Go `documents()` verifies
PaidDate and reads Labels/Label4X6 (not the combined labels-4x6 URL). Both return the existing
ProviderDocument abstraction. Purchases._fetch_documents stores bytes in SQLite artifacts
and attaches ShipmentDocument metadata to Label. Printing reads only those artifacts.

Legacy browser Print/Reprint routes remain for compatibility. The detail UI's Print label
and deliberate Reprint use the new physical endpoints. Open PDF and customs documents remain
available separately. A label without a stored dedicated artifact is refused: no provider
retrieval or purchase is triggered by printing.

## Configuration

Add to the EXISTING production `clive-shipping/.env` only after review:

    PRINTNODE_ENABLED=true
    PRINTNODE_PRINTER_ID=75883753
    PRINTNODE_API_KEY=<enter locally on the production server; never commit>

Only this exact configured JD-168BT is accepted. It must be online, its client connected,
and expose the proven paper, roll feeder and 203x203 DPI. Windows client must use Engine6.

Payload is pdf_base64 of the stored shipping artifact; copies=1, qty=1, pages="1",
paper='4.00"x6.00"(101.6x152.4)', dpi="203x203", bin="Roll Paper Feeder",
fit_to_page=false, rotate=0, color=false, expireAfter=300.

Metadata AND PDF validation require a dedicated shipping_label artifact, PDF MIME type,
one page, portrait, approximately 4x6, unrotated, uncropped. Mixed, A4, multi-page, malformed,
encrypted or unknown PDFs are refused, not guessed or split at page 1. The label stays bought.

## Intent and status API

All routes are under `/shipping/admin/api` in production and retain Shopify staff session auth.

- POST /shipments/{sid}/print-label: first-print intent stable per shipment/artifact.
- POST /shipments/{sid}/reprint-label: new deliberate intent per caller request key.
- POST /print/order/{ref}/label: resolve a purchased order, then first-print it.
- GET /print/intents/{id}: read/refresh provider job status, scoped to the authenticated shop.
- GET /print/health: configured printer status only.
- POST /print/test: harmless CROOKS SHIPPING / PRINTER TEST, one copy.

Every POST takes {"idempotency_key": "unique-request-key-at-least-8-characters"}.
Retry with the SAME key. A later intentional reprint uses a NEW key. UI retains keys in
sessionStorage across network failures/reloads and uses a separate Reprint action.
The SQLite print_intents ledger owns submission across workers; a recorded intent is never
automatically POSTed again, even after a restart or PrintNode's 24-hour key retention.
A lost POST reply is unknown, not failed-and-retried. Inspect status/history/physical output
before choosing a deliberate reprint. requested/submitting after a crash remains uncertain.

PrintNode new/sent_to_client/done/error/expired states are retained as provider_state.
`done` means handed to the OS queue, NOT confirmed physical printing. Local accepted stays
accepted; error/expired records failure. No automatic reprints, batch printing or natural
language handling is added. Legacy browser batch behavior is unchanged.

Official reference: https://www.printnode.com/en/docs/api/curl

## Review and deployment (NOT executed during implementation)

Existing topology: /opt/clive/crooks-returns contains docker-compose.yml. Shipping source
is its ../clive-shipping sibling; use the existing repository root, not a second install.
Resolve and review local changes on the server before fast-forwarding the implementation branch.

    cd /opt/clive
    git status --short
    git fetch origin codex/printnode-shipping
    git switch --track origin/codex/printnode-shipping
    git log -1 --oneline
    mkdir -p clive-shipping/data
    python3 -c "import sqlite3; from pathlib import Path; p=Path('clive-shipping/data/shipping.sqlite3'); p.exists() and sqlite3.connect(p).backup(sqlite3.connect(str(p)+'.before-printnode'))"

Stop if there are uncommitted changes or the branch switch cannot fast-forward safely.
The schema addition is additive. The command above uses SQLite's online backup API for a
consistent backup while Shipping runs. Preserve the existing .env.
Enter the key with a hidden prompt (this command is for the server operator AFTER approval):

    cd /opt/clive/clive-shipping
    python3 - <<'PY'
    from getpass import getpass
    from pathlib import Path
    import os
    path = Path('.env')
    text = path.read_text()
    key = getpass('PrintNode API key (hidden): ').strip()
    if not key or any(c in key for c in "\r\n'\""):
        raise SystemExit('Invalid/empty key; nothing changed')
    names = {'PRINTNODE_API_KEY', 'PRINTNODE_PRINTER_ID', 'PRINTNODE_ENABLED'}
    lines = [line for line in text.splitlines() if line.split('=', 1)[0].strip() not in names]
    lines += ['PRINTNODE_ENABLED=true', 'PRINTNODE_PRINTER_ID=75883753', 'PRINTNODE_API_KEY='+key]
    path.write_text('\n'.join(lines)+'\n')
    os.chmod(path, 0o600)
    print('PrintNode environment configured; key not displayed')
    PY

Then rebuild/recreate ONLY Shipping (restart alone does not load changed container env):

    cd /opt/clive/crooks-returns
    docker compose build shipping
    docker compose up -d --no-deps shipping
    docker compose exec -T shipping python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8120/health').read().decode())"
    docker compose exec -T shipping python -m shipping.tools.print_health

Do not run tools.dry_run with any live purchase actions, change purchase authorisations, or
configure keys in browser UI. The readiness tool performs PrintNode GET requests only.

After review/deployment, owner tests Print label and intentional Reprint on ONE already
purchased label in Shopify. Confirm one physical label each and zero new postage activity.
Disable PRINTNODE_ENABLED and recreate Shipping to fall back to Open PDF if needed.
