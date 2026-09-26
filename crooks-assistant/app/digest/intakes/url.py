"""Intake handler: a single file fetched by https URL — a release tarball, a package archive, a
specification, a document.

The URL is checked as every intake URL is (intake.https_url), and so is every redirect: it may
lead only to another public https URL, at most MAX_REDIRECTS times. The download — the only
network step, injectable as the "url" fetcher — goes to the intake's private scratch directory,
bounded by Limits.max_download_bytes and Limits.timeout, and is pinned by the digest of its
bytes: a URL can serve different bytes tomorrow, the digest cannot. If what arrived is an
archive (by its first bytes) it is unpacked as the archive handler unpacks one; otherwise it is
kept as one file, named from the URL's last path segment. Nothing is sent but the request: no
cookies, no credentials, no referrer."""

from __future__ import annotations

import os
import posixpath
import re
import time
import urllib.error
import urllib.request
from typing import BinaryIO
from urllib.parse import unquote, urlsplit

from app.digest.intake import (
    FetchFailed,
    LimitExceeded,
    Limits,
    Pinned,
    Request,
    SourceRefused,
    TreeWriter,
    https_url,
    sha256_file,
    shown,
)
from app.digest.intakes.archive import archive_format, unpack_file

NAME = "url"
ORIGIN_KIND = "url"

MAX_REDIRECTS = 5
USER_AGENT = "clive-digester-intake/1"
_SAFE_NAME = re.compile(r"[A-Za-z0-9._-]{1,200}")
_CHUNK = 1 << 16


def claims(request: Request) -> int:
    try:
        https_url(request.source)
    except SourceRefused:
        return 0
    return 20


def materialise(request: Request, writer: TreeWriter) -> Pinned:
    url = https_url(request.source)
    assert request.scratch is not None
    download = request.scratch / "download"
    fetch = request.fetcher(NAME, live_download)
    with open(download, "xb") as out:
        final = fetch(url, out, request.limits)
    if os.path.getsize(download) > request.limits.max_download_bytes:
        raise LimitExceeded(f"the download is over the {request.limits.max_download_bytes}-byte limit")
    pinned = sha256_file(download)
    notes = []
    if isinstance(final, str) and final and final != url:
        notes.append(f"redirected to {shown(https_url(final))}")
    kind = archive_format(download)
    if kind is not None:
        unpack_file(download, kind, writer)
        notes.append(f"unpacked from a {kind} archive")
    else:
        with open(download, "rb") as reader:
            writer.file(file_name(url), reader)
    return Pinned(origin=url, pinned_ref=pinned, notes=tuple(notes))


def file_name(url: str) -> str:
    """A plain name for the downloaded file from the URL's last path segment, or 'download'."""
    last = posixpath.basename(unquote(urlsplit(url).path))
    return last if _SAFE_NAME.fullmatch(last) and last not in (".", "..") else "download"


class _PublicHttpsRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        try:
            https_url(newurl)
        except SourceRefused as error:
            raise FetchFailed(f"the download redirected somewhere intake does not fetch from: {error}") from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def live_download(url: str, out: BinaryIO, limits: Limits) -> str:
    """Download url into out over https, bounded; return the URL finally served."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(), _PublicHttpsRedirects())
    opener.addheaders = [("User-Agent", USER_AGENT), ("Accept-Encoding", "identity")]
    deadline = time.monotonic() + limits.timeout
    try:
        with opener.open(url, timeout=min(limits.timeout, 60)) as response:
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > limits.max_download_bytes:
                raise LimitExceeded(f"the download declares {declared} bytes, over the {limits.max_download_bytes}-byte limit")
            total = 0
            while chunk := response.read(_CHUNK):
                total += len(chunk)
                if total > limits.max_download_bytes:
                    raise LimitExceeded(f"the download is over the {limits.max_download_bytes}-byte limit")
                if time.monotonic() > deadline:
                    raise FetchFailed(f"the download took longer than {limits.timeout:g} seconds")
                out.write(chunk)
            return response.geturl()
    except urllib.error.HTTPError as error:
        raise FetchFailed(f"the server answered {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FetchFailed(f"the download failed: {type(error).__name__}") from None
