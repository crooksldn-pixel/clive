# CLIVE Shipping

International Shopify fulfilment that feels domestic. The sister service to `crooks-returns/`:
the same preview/execute action model, Shopify as the system of record, and a small native UI.

The design, Phase 0 findings and stage plan are in [`docs/shipping/DESIGN.md`](../docs/shipping/DESIGN.md).

**Stage 1 (this commit):** the domain core, with no network:
- `money.py`: integer minor units only.
- `models.py`: shipment, customs lines, package, quote, label, and the purchase ledger.
- `states.py`: the shipment state machine; illegal moves raise.
- `basis.py`: the preview fingerprint; a changed order is STALE.
- `store.py`: SQLite, every row keyed by shop; one open purchase per shipment, enforced by a
  unique index.
- `providers/base.py`: the provider port and its three failure kinds.
- `providers/fake.py`: behaves like Parcel2Go, including charging again on re-pay.
- `purchase.py`: preview → authorise → execute → reconcile, pay-once.

**Stage 2:**
- `shopify.py`: validated Admin GraphQL documents, a client-credentials client and fulfillment-order
  snapshots.
- `readiness.py`: facts come from Shopify first, then what you confirmed; only what's missing
  becomes a question, once per product.
- `packages.py`: real presets you entered once; the package each mix of products went in is learned.
- `duties.py`: honest DAP wording; IOSS/DDP is a per-shop setting.
- `service.py`: sync, prepare, answer (written back to Shopify), choose a package, preview, buy,
  and fulfil with read-first/read-back (never a duplicate fulfillment).
- `fake_shopify.py`.

```
cd clive-shipping
pip install -e '.[dev]'
pytest
```
