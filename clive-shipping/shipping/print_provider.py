"""Physical print transport. No shipment or postage provider dependencies."""

from __future__ import annotations

import base64
from typing import Any, Protocol

import httpx

PAPER = '4.00"x6.00"(101.6x152.4)'
OPTIONS = dict(
    copies=1,
    paper=PAPER,
    dpi="203x203",
    bin="Roll Paper Feeder",
    fit_to_page=False,
    rotate=0,
    pages="1",
    color=False,
)


class PrintProviderError(Exception):
    def __init__(self, message: str, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


class PrintProvider(Protocol):
    def health(self) -> dict[str, Any]: ...
    def list_printers(self) -> list[dict[str, Any]]: ...
    def get_printer(self) -> dict[str, Any]: ...
    def print_pdf(self, body: bytes, title: str, key: str) -> int: ...
    def get_job_status(self, job_id: int) -> str: ...


class PrintNodeProvider:
    def __init__(self, api_key: str, printer_id: int, *, transport=None):
        self.printer_id = printer_id
        self._client = httpx.Client(
            base_url="https://api.printnode.com",
            timeout=20,
            auth=(api_key, ""),
            transport=transport,
        )

    def _call(self, method, path, **kw):
        try:
            response = self._client.request(method, path, **kw)
        except httpx.HTTPError:
            raise PrintProviderError(
                "PrintNode did not answer; no automatic retry.", uncertain=method == "POST"
            ) from None
        if not response.is_success:
            # Never copy a response body, URL, request headers or credentials into errors.
            raise PrintProviderError(
                f"PrintNode request failed (HTTP {response.status_code}).",
                uncertain=method == "POST"
                and (response.status_code >= 500 or response.status_code == 409),
            )
        try:
            return response.json()
        except ValueError:
            raise PrintProviderError(
                "PrintNode returned an unreadable reply.", uncertain=method == "POST"
            ) from None

    def list_printers(self):
        return self._call("GET", "/printers")

    def get_printer(self):
        rows = self._call("GET", f"/printers/{self.printer_id}")
        if not isinstance(rows, list) or len(rows) != 1:
            raise PrintProviderError("Configured printer was not found.")
        p = rows[0]
        caps = p.get("capabilities") or {}
        if p.get("id") != self.printer_id or p.get("name") != "JD-168BT":
            raise PrintProviderError("Configured printer does not match JD-168BT.")
        if p.get("state") != "online" or p.get("computer", {}).get("state") != "connected":
            raise PrintProviderError("JD-168BT or its Windows PrintNode client is offline.")
        if PAPER not in caps.get("papers", {}) or "203x203" not in caps.get("dpis", []):
            raise PrintProviderError("Printer does not expose the proven 4x6 / 203 dpi settings.")
        if OPTIONS["bin"] not in caps.get("bins", []):
            raise PrintProviderError("Printer does not expose its roll paper feeder.")
        return {
            "id": p["id"],
            "name": p["name"],
            "state": p["state"],
            "computer_id": p["computer"]["id"],
            "capabilities": caps,
        }

    def health(self):
        try:
            p = self.get_printer()
            return dict(
                enabled=True,
                connected=True,
                name=p["name"],
                printer_id=p["id"],
                state="online",
                paper=PAPER,
                dpi="203x203",
                detail="Connected",
            )
        except PrintProviderError as exc:
            return dict(
                enabled=True,
                connected=False,
                name="JD-168BT",
                printer_id=self.printer_id,
                state="unavailable",
                detail=str(exc),
            )

    def print_pdf(self, body, title, key):
        result = self._call(
            "POST",
            "/printjobs",
            headers={"X-Idempotency-Key": key},
            json=dict(
                printerId=self.printer_id,
                title=title,
                contentType="pdf_base64",
                content=base64.b64encode(body).decode("ascii"),
                options=OPTIONS,
                qty=1,
                expireAfter=300,
                source="CROOKS Shipping",
            ),
        )
        if type(result) is not int or result <= 0:
            raise PrintProviderError("PrintNode acceptance could not be confirmed.", uncertain=True)
        return result

    def get_job_status(self, job_id):
        rows = self._call("GET", f"/printjobs/{job_id}/states")
        # Endpoint returns one array of events per job.
        events = [e for row in rows for e in (row if isinstance(row, list) else [row])]
        events = [e for e in events if e.get("printJobId") == job_id]
        if not events:
            return "accepted"
        return sorted(events, key=lambda e: e.get("createTimestamp", ""))[-1].get(
            "state", "accepted"
        )
