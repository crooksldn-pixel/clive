"""The CLIVE Shipping service's own code, loaded for CLIVE's tests: never copied into CLIVE.

The service is George's (built on branch claude/compassionate-dirac-44hnee, reviewed and fixed on
claude/n2-service-fixes; folder clive-shipping/). This takes
that folder AT ONE PINNED COMMIT (SERVICE_SHA) from the repository's history with `git archive` (or
from CLIVE_SHIPPING_SRC, a checkout of clive-shipping/) and imports it beside CLIVE, with its own fake
Shopify (shipping/fake_shopify.py), its own fake courier (shipping/providers/fake.py, which "behaves
like Parcel2Go, including charging again on re-pay") and its own test helpers. Used by
tests/test_crooks_shipping_contract.py and tests/test_shipping_browser.py. Not a test module.

Pinned, not the branch's tip: CLIVE is held to the code that answers it, and a change to the service
on its branch does not change what CLIVE's tests prove until someone says so.

To bump it, when George deploys a newer service:
  1. on the server: git -C /opt/clive rev-parse HEAD   (the commit /opt/clive/clive-shipping runs);
  2. set SERVICE_SHA below to that full SHA, and PINNED_ON to the day;
  3. run tests/test_crooks_shipping_contract.py; a failure is a change in the service's contract that
     CLIVE's client must meet before the bump lands.

The service needs pypdf and reportlab (its label PDFs); CLIVE's dev extras carry them for these tests
alone. Without them, or without the pinned commit (a shallow clone), the tests that need it skip and
say why; in the acceptance workflow, which checks out with full history and installs the dev
extras, they fail instead (`not_here`).
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import os
import subprocess
import sys
import tarfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "claude/n2-service-fixes"
# The service's commit these tests run, and the one to be deployed: the reviewed fixes of 8 October
# 2026 on top of claude/compassionate-dirac-44hnee's 92c11ba4 (the CLIVE API, 89341403, and its own
# fixes). Its clive-shipping/shipping/ code is 92c11ba4's unchanged; only its tests' made-up
# tracking numbers differ. Bump it as the module's docstring says.
SERVICE_SHA = "8f15b796cad83b0b6a3bbd635a141b60de51ec67"
PINNED_ON = "2026-10-08"
THEIR_TESTS = "clive_shipping_service_tests"
WHY_NOT = (f"the CLIVE Shipping service's code at {SERVICE_SHA[:8]} ({BRANCH}, clive-shipping/) is not in this "
           "checkout's history; fetch that branch, or set CLIVE_SHIPPING_SRC to a checkout of it, to run this")
WHY_NO_PDF = "the CLIVE Shipping service needs pypdf and reportlab (pip install -e '.[dev]')"


def not_here(reason: str) -> None:
    """The service's code cannot run here: a skip on a laptop, a failure in the acceptance run. The
    acceptance workflow checks out every branch's history and installs the dev extras, so there a
    skip would only hide that CLIVE's half of the contract went unproven."""
    import pytest

    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.fail(f"the CLIVE Shipping contract could not run in the acceptance run: {reason}")
    pytest.skip(reason)


def missing_libraries() -> str:
    """Why the service's code cannot be imported here, or "" when it can."""
    if any(importlib.util.find_spec(name) is None for name in ("pypdf", "reportlab")):
        return WHY_NO_PDF
    return ""


def source(into: Path) -> tuple[Path, str] | None:
    """The service's folder and the commit it is (empty for CLIVE_SHIPPING_SRC), or None when the
    pinned commit is not here. Never the branch's tip in its place."""
    named = os.environ.get("CLIVE_SHIPPING_SRC", "")
    if named and (Path(named) / "shipping" / "api.py").is_file():
        return Path(named), ""
    found = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", f"{SERVICE_SHA}^{{commit}}"],
                           capture_output=True, text=True)
    if found.returncode != 0 or found.stdout.strip() != SERVICE_SHA:
        return None
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", SERVICE_SHA, "clive-shipping"], capture_output=True)
    if archive.returncode != 0:
        return None
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(into, filter="data")
    return into / "clive-shipping", SERVICE_SHA


def load(into: Path) -> types.SimpleNamespace | None:
    """The service's modules, or None when its code is not here. `unload()` puts things back."""
    found = source(into)
    if found is None:
        return None
    src, sha = found
    os.environ["SHIPPING_ENV_FILE"] = ""          # its settings read no .env file
    sys.path.insert(0, str(src))
    spec = importlib.util.spec_from_file_location(THEIR_TESTS, src / "tests" / "__init__.py",
                                                  submodule_search_locations=[str(src / "tests")])
    package = importlib.util.module_from_spec(spec)
    sys.modules[THEIR_TESTS] = package
    spec.loader.exec_module(package)
    module = importlib.import_module
    return types.SimpleNamespace(
        src=src, sha=sha, app=module("shipping.app"), api=module("shipping.api"), models=module("shipping.models"),
        fake_shopify=module("shipping.fake_shopify"), fake_provider=module("shipping.providers.fake"),
        purchase=module("shipping.purchase"), service=module("shipping.service"), settings=module("shipping.settings"),
        store=module("shipping.store"), conftest=module(f"{THEIR_TESTS}.conftest"),
        stage2=module(f"{THEIR_TESTS}.test_stage2"), labels=module(f"{THEIR_TESTS}.test_label_selection"),
    )


def unload(loaded: types.SimpleNamespace | None) -> None:
    if loaded is None:
        return
    if str(loaded.src) in sys.path:
        sys.path.remove(str(loaded.src))
    for name in list(sys.modules):
        if name.split(".")[0] in ("shipping", THEIR_TESTS):
            sys.modules.pop(name, None)
    os.environ.pop("SHIPPING_ENV_FILE", None)


def behind_caddy(app, prefix: str = "/shipping"):
    """The service as it is reached in production: Caddy's `handle_path /shipping/*` hands it the
    path without the prefix (crooks-returns/Caddyfile); anything else is not the service's."""
    from starlette.responses import PlainTextResponse

    async def asgi(scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if not path.startswith(prefix + "/"):
                await PlainTextResponse("not the shipping service", status_code=404)(scope, receive, send)
                return
            scope = {**scope, "path": path[len(prefix):], "raw_path": path[len(prefix):].encode()}
        await app(scope, receive, send)

    return asgi


def world(loaded: types.SimpleNamespace, folder: Path, *, read_key: str, write_key: str, buying: bool = True):
    """The service as deployed, on its own fakes: its fake Shopify, its fake courier, its clock, and
    CLIVE's two keys. `buying` is its SHIPPING_BUYING_ENABLED: off, no order is authorised."""
    s = loaded
    clock = s.conftest.Clock()
    store = s.store.Store(str(folder / "shipping.sqlite3"))
    provider = s.fake_provider.FakeProvider()
    shopify = s.fake_shopify.FakeShopify()
    settings = s.settings.Settings(shop_domain=s.conftest.SHOP, provider="fake", tick_interval_s=0,
                                   clive_read_keys=read_key, clive_write_keys=write_key, buying_enabled=buying)
    # The buying authorisation exactly as the service builds it (shipping/app.py build_service).
    allowed = settings.authorised()
    svc = s.service.ShippingService(
        store, shopify, provider, s.purchase.Purchases(store, provider, clock=clock), clock=clock,
        may_buy=lambda x: settings.buying_enabled or s.app._order_number(x.order_name) in allowed)
    app = s.app.create_app(settings, svc)
    # `app` is the service itself (its state holds the PrintNode connection); `reached` is how CLIVE
    # reaches it, under /shipping.
    return types.SimpleNamespace(svc=svc, store=store, provider=provider, shopify=shopify, clock=clock, app=app,
                                 reached=behind_caddy(app), shop=s.conftest.SHOP)


def ready_order(loaded: types.SimpleNamespace, w, number: int = 2145):
    """One order to Germany, found in Shopify, its three facts answered as a person would the first
    time (a package, an HS code, a country of origin): ready to price. The service's own helpers."""
    fake = loaded.fake_shopify
    w.shopify.add(fake.fo(number, [fake.tee_line(qty=2)]))
    w.svc.sync(w.shop)
    shipment = next(x for x in w.svc.store.shipments(w.shop) if x.order_name.endswith(str(number)))
    return loaded.stage2.answer_all_first_time(w.svc, shipment)


def real_label(loaded: types.SimpleNamespace, w, shipment_id: str) -> None:
    """A real 4x6 label PDF on a bought order, as a courier returns it: what the service prints."""
    row = w.store.get(w.shop, shipment_id)
    doc = row.label.document(loaded.models.DocumentKind.shipping_label)
    doc.artifact_id = w.store.put_artifact(w.shop, shipment_id, "shipping_label", "application/pdf",
                                           loaded.labels.bundle(("LABEL",)))
    w.store.save(row)
