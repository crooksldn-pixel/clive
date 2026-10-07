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
    def get_job_states(self, job_id: int) -> list[dict[str, Any]]: ...
    def describe(self) -> dict[str, Any]: ...


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

    def _printer_row(self) -> dict[str, Any]:
        rows = self._call("GET", f"/printers/{self.printer_id}")
        if not isinstance(rows, list) or len(rows) != 1:
            raise PrintProviderError("Configured printer was not found.")
        return rows[0]

    def describe(self) -> dict[str, Any]:
        """What PrintNode says about the printer and the computer it hangs off, whatever their
        state, so a person can see why printing would wait or fail."""
        try:
            p = self._printer_row()
        except PrintProviderError as exc:
            return dict(reachable=False, detail=str(exc))
        computer = p.get("computer") or {}
        return dict(
            reachable=True,
            printer_name=p.get("name"),
            printer_state=p.get("state"),
            computer_name=computer.get("name"),
            computer_state=computer.get("state"),
        )

    def get_printer(self):
        p = self._printer_row()
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

    def get_job_states(self, job_id):
        """Every state the job has been through, oldest first: new, sent_to_client, queued,
        in_progress, then done, or error / expired / deleted / disappeared."""
        rows = self._call("GET", f"/printjobs/{job_id}/states")
        # Endpoint returns one array of events per job.
        events = [e for row in rows for e in (row if isinstance(row, list) else [row])]
        events = [e for e in events if isinstance(e, dict) and e.get("printJobId") == job_id]
        return [
            dict(
                state=str(e.get("state") or ""),
                at=e.get("createTimestamp"),
                message=str(e.get("message") or "")[:200],
            )
            for e in sorted(events, key=lambda e: e.get("createTimestamp", ""))
        ]

    def get_job_status(self, job_id):
        states = self.get_job_states(job_id)
        return (states[-1]["state"] or "accepted") if states else "accepted"
