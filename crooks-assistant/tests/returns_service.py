"""The CROOKS Returns service's own code, loaded for CLIVE's tests: never copied into CLIVE.

The service is George's (branch claude/compassionate-dirac-44hnee, folder crooks-returns/). This
takes that folder from the repository's history with `git archive` (or from CROOKS_RETURNS_SRC, a
checkout of crooks-returns/) and imports it beside CLIVE, with its own fake Shopify
(returns/fake.py) and its own simulated Parcel2Go (its tests/test_parcel2go.py FakeParcel2Go).
Used by tests/test_crooks_returns_contract.py and tests/returns_world.py. Not a test module.
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
BRANCH = "claude/compassionate-dirac-44hnee"
THEIR_TESTS = "crooks_returns_service_tests"
WHY_NOT = (f"the CROOKS Returns service's code ({BRANCH}, crooks-returns/) is not in this checkout's history; "
           "set CROOKS_RETURNS_SRC to a checkout of it to run this")


def source(into: Path) -> Path | None:
    named = os.environ.get("CROOKS_RETURNS_SRC", "")
    if named and (Path(named) / "returns" / "api.py").is_file():
        return Path(named)
    for ref in (f"origin/{BRANCH}", BRANCH):
        found = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                               capture_output=True, text=True)
        if found.returncode != 0:
            continue
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", found.stdout.strip(), "crooks-returns"],
                                 capture_output=True)
        if archive.returncode != 0:
            continue
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(into, filter="data")
        return into / "crooks-returns"
    return None


def _segno_if_missing() -> None:
    """The service draws its in-store QR codes with segno, which CLIVE does not depend on: where it
    is not installed, a stand-in that writes a PNG signature is all the flow needs."""
    if importlib.util.find_spec("segno") is not None:
        return
    stand_in = types.ModuleType("segno")

    class _Code:
        def save(self, out, **_kw):
            out.write(b"\x89PNG\r\n\x1a\n stand-in")

    stand_in.make = lambda code, error=None: _Code()
    sys.modules["segno"] = stand_in


def load(into: Path) -> types.SimpleNamespace | None:
    """The service's modules, or None when its code is not here. `unload()` puts things back."""
    src = source(into)
    if src is None:
        return None
    os.environ["RETURNS_ENV_FILE"] = ""
    sys.path.insert(0, str(src))
    _segno_if_missing()
    spec = importlib.util.spec_from_file_location(THEIR_TESTS, src / "tests" / "__init__.py",
                                                  submodule_search_locations=[str(src / "tests")])
    package = importlib.util.module_from_spec(spec)
    sys.modules[THEIR_TESTS] = package
    spec.loader.exec_module(package)
    return types.SimpleNamespace(
        src=src, app=importlib.import_module("returns.app"), fake=importlib.import_module("returns.fake"),
        models=importlib.import_module("returns.models"), parcel2go=importlib.import_module("returns.parcel2go"),
        service=importlib.import_module("returns.service"), settings=importlib.import_module("returns.settings"),
        store=importlib.import_module("returns.store"), p2g=importlib.import_module(f"{THEIR_TESTS}.test_parcel2go"),
    )


def unload(loaded: types.SimpleNamespace | None) -> None:
    if loaded is None:
        return
    if str(loaded.src) in sys.path:
        sys.path.remove(str(loaded.src))
    for name in list(sys.modules):
        if name.split(".")[0] in ("returns", THEIR_TESTS) or (name == "segno" and not getattr(sys.modules[name], "__file__", None)):
            sys.modules.pop(name, None)
    os.environ.pop("RETURNS_ENV_FILE", None)


def settings(loaded: types.SimpleNamespace, folder: Path, *, read_key: str, write_key: str):
    """The service's settings as deployed, on its own fakes: Parcel2Go labels, simulated."""
    return loaded.settings.Settings(
        db_path=str(folder / "returns.sqlite3"), session_secret="contract-session", shopify_client_secret="not-a-secret",
        dev_skip_proxy_signature=True, return_label_cost_pence=350, clive_read_keys=read_key, clive_write_keys=write_key,
        public_base_url="https://returns.example.com", label_provider="parcel2go", tick_interval_s=0,
        p2g_client_id="id:CrooksReturns", p2g_client_secret="not-a-secret", p2g_base_url="https://p2g.test",
        returns_address_line1="Unit M", returns_address_line2="Bourne End Business Park",
        returns_address_city="Bourne End, Buckinghamshire", returns_address_postcode="SL8 5AS",
    )
