"""Gmail: one credential, the reads made with it, and the few named writes the action engine
can stage.

The credential is loaded with the scopes it was granted — they live in the stored token —
never with a list hardcoded here: an inbox authorised for more than a stale comment expects
is not a fault. What the token can actually do is read back from Google (the grant
response on refresh, or the tokeninfo endpoint), cached, and reported per kind of call —
reading, drafting, sending, changing labels — so a capability is a fact about the
credential and never an assumption. A credential is reported as needing re-authorisation
only when Google itself has refused to refresh it; never because a check could not run.

The writes are named methods with fixed request shapes. Nothing here takes an arbitrary
API call from a caller: the engine stages an exact message built on the Mac, and one of
these sends it, once.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app import readonly

log = logging.getLogger("crooks.gmail")

SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
SCOPE_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"
SCOPE_FULL = "https://mail.google.com/"

# What scripts/gmail_auth.py asks Google for, and what the CROOKS inbox is authorised with:
# modify (read mail, change labels) and compose (drafts, and sending). Not the full mailbox
# scope, which alone permits permanent deletion.
REQUESTED_SCOPES = [SCOPE_MODIFY, SCOPE_COMPOSE]

# Which scopes allow which kind of call, per Google's own table for each method.
OPERATIONS: dict[str, tuple[str, ...]] = {
    "read": (SCOPE_READONLY, SCOPE_MODIFY, SCOPE_FULL),
    "draft": (SCOPE_COMPOSE, SCOPE_MODIFY, SCOPE_FULL),
    "send": (SCOPE_SEND, SCOPE_COMPOSE, SCOPE_MODIFY, SCOPE_FULL),
    "labels": (SCOPE_MODIFY, SCOPE_FULL),
}
_SHORT = {SCOPE_READONLY: "readonly", SCOPE_MODIFY: "modify", SCOPE_COMPOSE: "compose", SCOPE_SEND: "send", SCOPE_FULL: "full"}

SCOPES_TTL_S = 600.0
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
TOKENINFO_TIMEOUT_S = 5.0

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CREDENTIALS_PATH = REPO_ROOT / "credentials.json"
TOKEN_PATH = REPO_ROOT / "token.json"


class GmailAuthRequired(RuntimeError):
    """The stored credential is missing or Google has refused to refresh it. Needs a human, once."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"{detail} Re-authorise with: python scripts/gmail_auth.py")


class GmailError(RuntimeError):
    """A Gmail call failed in a way worth reporting honestly."""


class GmailRefused(GmailError):
    """Gmail answered and said no (a 4xx with a reason): the change was not made."""

    refused = True


class GmailNotFound(GmailRefused):
    """Gmail answered 404: it does not hold the thing asked for. The one answer that proves a draft
    is gone; any other refusal (a 403, a 400) proves nothing about it (app/tools/gmail_drafts.py)."""


def short_scopes(scopes) -> str:
    """"modify, compose" — the scopes as a person says them."""
    return ", ".join(sorted(_SHORT.get(s, s.rsplit("/", 1)[-1]) for s in scopes)) or "none"


@dataclass(frozen=True)
class ScopeReport:
    """What the credential can do, and how that is known."""

    scopes: frozenset[str]
    source: str          # "google" (the grant response or tokeninfo) or "stored" (the token file, unverified)
    checked_at: float

    def allows(self, kind: str) -> bool:
        return any(s in self.scopes for s in OPERATIONS.get(kind, ()))

    @property
    def verified(self) -> bool:
        return self.source == "google"

    def words(self) -> str:
        return f"{short_scopes(self.scopes)} ({'verified by Google' if self.verified else 'as stored; Google did not answer the scope check'})"


def describe_error(exc: BaseException) -> str:
    """googleapiclient errors embed the request URL — including a search query, which may
    hold an email address. Strip URLs, then redact what is left."""
    from app.logging.turnlog import redact_text

    text = re.sub(r"https?://\S+", "[url]", str(exc))
    return redact_text(text)[:200]


def is_auth_failure(exc: BaseException) -> bool:
    try:
        from google.auth.exceptions import RefreshError
    except ImportError:  # pragma: no cover
        return isinstance(exc, GmailAuthRequired)
    return isinstance(exc, (RefreshError, GmailAuthRequired)) or "invalid_grant" in str(exc)


def _read_token_json() -> tuple[str, str]:
    """(json, where). The Keychain is preferred — the refresh token is a long-lived secret and
    the project rule is that secrets do not live in files. token.json (mode 600) remains the
    fallback for the plan's original flow and for hosts without a keychain."""
    from app.secrets import keychain

    stored = keychain.get_optional("gmail_token")
    if stored:
        return stored, "keychain"
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text(encoding="utf-8"), "file"
    raise GmailAuthRequired("No Gmail token stored.")


def stored_scopes() -> frozenset[str]:
    """The scopes the stored token says it was authorised with. The file's word, not Google's."""
    import json

    raw, _ = _read_token_json()
    try:
        info = json.loads(raw)
    except ValueError:
        return frozenset()
    scopes = info.get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    return frozenset(str(s) for s in scopes)


def store_token_json(payload: str) -> str:
    """Persist the authorised-user JSON. Returns where it went."""
    from app.secrets import keychain

    try:
        keychain.set_secret("gmail_token", payload)
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink()
        return "keychain"
    except Exception as exc:  # noqa: BLE001 — no keychain: fall back to the 600-mode file
        log.warning(
            "Keychain unavailable (%s: %s); Gmail credential written to %s with mode 600. "
            "This is the plan's original flow and an accepted exception to the secrets rule.",
            type(exc).__name__, exc, TOKEN_PATH.name,
        )
        TOKEN_PATH.write_text(payload, encoding="utf-8")
        TOKEN_PATH.chmod(0o600)
        return "file"


def load_credentials():
    """Load and refresh the stored credential, with the scopes it was granted. Never opens a
    browser. Google's refusal to refresh is the only thing reported as needing the owner."""
    import json

    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    raw, where = _read_token_json()
    try:
        info = json.loads(raw)
    except ValueError as exc:
        raise GmailAuthRequired(f"The stored Gmail token ({where}) is not valid JSON.") from exc
    # The scopes come from the token itself. Asking google-auth for a different list makes a
    # refresh fail with "not all requested scopes were granted" against a perfectly good token.
    creds = Credentials.from_authorized_user_info(info)

    if not creds.refresh_token:
        raise GmailAuthRequired(
            "The stored Gmail credential has no refresh token, so it will expire within the hour."
        )

    if creds.valid:
        return creds

    if creds.expired:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # invalid_grant is usually a Google password change (which revokes Gmail-scoped
            # tokens by design) or an app still in Testing (7-day token lifetime).
            raise GmailAuthRequired(f"Gmail refresh was rejected ({exc}).") from exc
        store_token_json(creds.to_json())
        return creds

    raise GmailAuthRequired("The stored Gmail credential cannot be refreshed.")


def effective_scopes(creds) -> tuple[frozenset[str], str]:
    """What Google says the credential may do: the grant response when the token was just
    refreshed, otherwise the tokeninfo endpoint. The stored list only when Google did not
    answer — and then said to be that."""
    granted = getattr(creds, "granted_scopes", None)
    if granted:
        return frozenset(granted), "google"
    token = getattr(creds, "token", None)
    if token:
        try:
            import httpx

            response = httpx.get(TOKENINFO_URL, params={"access_token": token}, timeout=TOKENINFO_TIMEOUT_S)
            if response.status_code == 200:
                scope = str((response.json() or {}).get("scope") or "")
                if scope:
                    return frozenset(scope.split()), "google"
            else:
                log.warning("tokeninfo answered %s; scopes taken from the stored token", response.status_code)
        except Exception as exc:  # noqa: BLE001 — Google not answering says nothing about the grant
            log.warning("tokeninfo unavailable (%s); scopes taken from the stored token", type(exc).__name__)
    return frozenset(getattr(creds, "scopes", None) or []), "stored"


class GmailClient:
    """One credential, one service object per thread.

    googleapiclient does its HTTP through httplib2, which is not safe to share between threads:
    the health check's profile call and a search running side by side on one connection
    corrupt its TLS state, and that has taken the whole backend down with a `malloc: double
    free`. Every Gmail call already runs in a worker thread, so each thread builds its own
    service (the discovery document ships with the library; no request is made) around the
    shared, refreshed credential."""

    def __init__(self) -> None:
        self._service = None            # an injected service, used from every thread (tests)
        self._creds = None
        self._lock = threading.Lock()
        self._local = threading.local()
        self._generation = 0
        self._scopes: ScopeReport | None = None
        self._address = ""

    # ------------------------------------------------------------ credential

    def service(self):
        if self._service is not None:
            return self._service
        local = self._local
        if getattr(local, "service", None) is None or local.generation != self._generation:
            local.service = self._build()
            local.generation = self._generation
        return local.service

    def credentials(self):
        with self._lock:
            if self._creds is None:
                self._creds = load_credentials()
            return self._creds

    def _build(self):
        from googleapiclient.discovery import build

        return build("gmail", "v1", credentials=self.credentials(), cache_discovery=False)

    def reset(self) -> None:
        """Forget the credential; every thread rebuilds on its next call."""
        self._service = None
        with self._lock:
            self._creds = None
            self._scopes = None
            self._generation += 1

    def scopes(self, *, fresh: bool = False) -> ScopeReport:
        """What the credential may do, from Google, cached for a while. Raises
        GmailAuthRequired only when there is no usable credential at all."""
        report = self._scopes
        if report is not None and not fresh and time.time() - report.checked_at < SCOPES_TTL_S:
            return report
        if self._service is not None and self._creds is None:
            # An injected service (tests, a double): whatever the double says it may do.
            scopes, source = frozenset(getattr(self._service, "scopes", ()) or ()), "stored"
        else:
            scopes, source = effective_scopes(self.credentials())
        report = ScopeReport(scopes=scopes, source=source, checked_at=time.time())
        self._scopes = report
        return report

    def can(self, kind: str) -> bool:
        return self.scopes().allows(kind)

    def address(self) -> str:
        """The mailbox's own address: the From of anything sent, and never a recipient."""
        if not self._address:
            self._address = str(self.profile().get("emailAddress") or "").strip().lower()
        return self._address

    def profile(self) -> dict:
        return self.service().users().getProfile(userId="me").execute()

    def health(self) -> tuple[bool, str]:
        try:
            profile = self.profile()
            report = self.scopes()
            return True, f"{profile.get('emailAddress')} · {report.words()}"
        except GmailAuthRequired as exc:
            self.reset()
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001
            return False, f"Gmail check failed: {describe_error(exc)}"

    # ---------------------------------------------------------------- calls

    def _run(self, what: str, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if is_auth_failure(exc):
                self.reset()
                raise GmailAuthRequired("Gmail authorisation has expired.") from exc
            status = getattr(getattr(exc, "resp", None), "status", None) or getattr(exc, "status_code", None)
            if status == 404:
                raise GmailNotFound(f"{what}: {describe_error(exc)}") from exc
            if isinstance(status, int) and 400 <= status < 500 and status not in (408, 429):
                raise GmailRefused(f"{what}: {describe_error(exc)}") from exc
            raise GmailError(f"{what}: {describe_error(exc)}") from exc

    # --- reads the writes need

    THREAD_HEADERS = ("From", "To", "Reply-To", "Subject", "Date", "Message-ID", "In-Reply-To", "References", "Authentication-Results")

    def thread_messages(self, thread_id: str) -> list[dict]:
        """Every message in a thread with its labels and the headers a reply needs: the
        thread as it is, for a fingerprint and for the reply's addressing."""
        def fetch():
            thread = self.service().users().threads().get(
                userId="me", id=thread_id, format="metadata", metadataHeaders=list(self.THREAD_HEADERS),
            ).execute()
            out = []
            for message in thread.get("messages") or []:
                headers: dict[str, str] = {}
                for h in (message.get("payload") or {}).get("headers") or []:
                    headers.setdefault(str(h.get("name", "")).lower(), str(h.get("value", "")))
                out.append({"id": str(message.get("id") or ""), "labels": list(message.get("labelIds") or []), "headers": headers})
            return out
        return self._run("Could not read the thread", fetch)

    def message_labels(self, message_id: str) -> set[str]:
        """One message's labels: SENT is the proof a send Gmail answered for really went."""
        def fetch():
            message = self.service().users().messages().get(userId="me", id=message_id, format="minimal").execute()
            return set(message.get("labelIds") or [])
        return self._run("Could not read the message", fetch)

    def thread_labels(self, thread_id: str) -> set[str]:
        def fetch():
            thread = self.service().users().threads().get(userId="me", id=thread_id, format="minimal").execute()
            labels: set[str] = set()
            for message in thread.get("messages") or []:
                labels.update(message.get("labelIds") or [])
            return labels
        return self._run("Could not read the thread", fetch)

    def thread_full(self, thread_id: str) -> list[dict]:
        """Every message in a thread with its whole payload, for a search the Mac runs over
        the text itself. One request per thread; the caller bounds how many threads."""
        def fetch():
            thread = self.service().users().threads().get(userId="me", id=thread_id, format="full").execute()
            return list(thread.get("messages") or [])
        return self._run("Could not read the thread", fetch)

    def thread_state(self, thread_id: str) -> list[dict]:
        """Every message in a thread as (id, labels, when). `internalDate` is Gmail's own
        millisecond stamp for when the message arrived or was sent, which is what makes
        "who spoke last" answerable without parsing a Date header nobody controls."""
        def fetch():
            thread = self.service().users().threads().get(
                userId="me", id=thread_id, format="metadata", metadataHeaders=["From"],
            ).execute()
            out = []
            for message in thread.get("messages") or []:
                headers = {str(h.get("name", "")).lower(): str(h.get("value", "")) for h in (message.get("payload") or {}).get("headers") or []}
                try:
                    when = int(message.get("internalDate") or 0)
                except (TypeError, ValueError):
                    when = 0
                out.append({"id": str(message.get("id") or ""), "labels": list(message.get("labelIds") or []), "at_ms": when, "from": headers.get("from", "")})
            return out
        return self._run("Could not read the thread", fetch)

    def list_drafts(self, query: str) -> list[dict]:
        """Drafts matching a Gmail query: id and the message id and thread of each."""
        def fetch():
            listing = self.service().users().drafts().list(userId="me", q=query, maxResults=10).execute()
            return [
                {"draft_id": str(d.get("id") or ""), "message_id": str((d.get("message") or {}).get("id") or ""), "thread_id": str((d.get("message") or {}).get("threadId") or "")}
                for d in listing.get("drafts") or []
            ]
        return self._run("Could not list drafts", fetch)

    def get_draft(self, draft_id: str) -> dict:
        """One draft in full: its message, for the card to print exactly what would go."""
        return self._run("Could not read the draft", lambda: self.service().users().drafts().get(userId="me", id=draft_id, format="full").execute())

    def find_messages(self, query: str) -> list[dict]:
        def fetch():
            listing = self.service().users().messages().list(userId="me", q=query, maxResults=10).execute()
            return [{"id": str(m.get("id") or ""), "thread_id": str(m.get("threadId") or "")} for m in listing.get("messages") or []]
        return self._run("Could not search", fetch)

    # --- the writes: named, fixed shapes, one call each

    def create_draft(self, raw: str, thread_id: str | None) -> dict:
        readonly.assert_writable("creating a Gmail draft")
        body = {"message": {"raw": raw, **({"threadId": thread_id} if thread_id else {})}}
        def call():
            draft = self.service().users().drafts().create(userId="me", body=body).execute()
            message = draft.get("message") or {}
            return {"draft_id": str(draft.get("id") or ""), "message_id": str(message.get("id") or ""), "thread_id": str(message.get("threadId") or "")}
        return self._run("Could not save the draft", call)

    def delete_draft(self, draft_id: str) -> None:
        readonly.assert_writable("deleting a Gmail draft")
        self._run("Could not delete the draft", lambda: self.service().users().drafts().delete(userId="me", id=draft_id).execute())

    def send_message(self, raw: str, thread_id: str | None) -> dict:
        readonly.assert_writable("sending a Gmail message")
        body = {"raw": raw, **({"threadId": thread_id} if thread_id else {})}
        def call():
            sent = self.service().users().messages().send(userId="me", body=body).execute()
            return {"message_id": str(sent.get("id") or ""), "thread_id": str(sent.get("threadId") or "")}
        return self._run("Could not send", call)

    def send_draft(self, draft_id: str) -> dict:
        readonly.assert_writable("sending a Gmail draft")
        def call():
            sent = self.service().users().drafts().send(userId="me", body={"id": draft_id}).execute()
            return {"message_id": str(sent.get("id") or ""), "thread_id": str(sent.get("threadId") or "")}
        return self._run("Could not send the draft", call)

    def modify_thread(self, thread_id: str, *, add: list[str], remove: list[str]) -> None:
        readonly.assert_writable("relabelling a Gmail thread")
        body = {"addLabelIds": list(add), "removeLabelIds": list(remove)}
        self._run("Could not change the thread's labels", lambda: self.service().users().threads().modify(userId="me", id=thread_id, body=body).execute())
