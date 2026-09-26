"""Intake handler: a published package, by its name in a registry — npm or PyPI.

    npm:<name>[@<version>]         npm:left-pad@1.3.0, npm:@scope/name@2.0.0
    pypi:<name>[==<version>]       pypi:requests==2.32.3 (or pypi:requests@2.32.3)

The version may be given as ref= instead. Without one, the registry's latest is taken, and the
intake's notes say which version that was.

Two network steps, both injectable: the registry's metadata for the version (the "registry"
fetcher, bounded by MAX_METADATA_BYTES), and the package archive it names (the "package"
fetcher: the url handler's bounded download, every redirect checked). The archive's URL comes
from the registry and is data like anything fetched: it must be a public https URL, as every
intake URL must. The archive must match the digest the registry publishes for it — npm's
sha512 integrity (or, for a package too old to have one, its sha1 shasum), PyPI's sha256 — or
intake stops: what is unpacked is exactly what was published. It is unpacked as any archive is,
with the one folder a package archive wraps its files in (npm's package/, or the package's own
name as @types packages have it; an sdist's <name>-<version>/) taken off, so the package's own manifest and licence are at the top of the
tree. From PyPI the source distribution is taken when there is one, else a pure-Python wheel.
Nothing is built, installed or run."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from dataclasses import replace
from typing import Any
from urllib.parse import quote

from app.digest.intake import (
    ArchiveUnreadable,
    FetchFailed,
    Limits,
    Pinned,
    Request,
    SourceRefused,
    TreeWriter,
    UnsafeArtifact,
    clean_name,
    https_url,
    shown,
)
from app.digest.intakes.archive import archive_format, unpack_file
from app.digest.intakes.url import live_download

NAME = "package"
ORIGIN_KIND = "package"

REGISTRIES = ("npm", "pypi")
NPM_REGISTRY = "https://registry.npmjs.org"
PYPI_REGISTRY = "https://pypi.org/pypi"
MAX_METADATA_BYTES = 8 << 20
MAX_PACKAGE_NAME = 214
_NPM_NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*")
_PYPI_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+!_-]{0,63}")
_PURE_WHEEL = re.compile(r"-py(?:2\.py3|3)-none-any\.whl$")
_SDIST = (".tar.gz", ".zip", ".tar.bz2", ".tar.xz", ".tgz")
_CHUNK = 1 << 16


def claims(request: Request) -> int:
    registry, _sep, _rest = request.source.partition(":")
    return 90 if registry in REGISTRIES and _rest else 0


def parse(source: str, ref: str | None = None) -> tuple[str, str, str | None]:
    """(registry, name, version or None) from a package source; SourceRefused when it is not
    one intake can name exactly."""
    registry, _sep, rest = source.partition(":")
    if registry not in REGISTRIES or not rest:
        raise SourceRefused(f"{shown(source)} is not a package source (npm:<name>, pypi:<name>)")
    version: str | None = None
    if registry == "npm":
        at = rest.rfind("@")
        name, version = (rest[:at], rest[at + 1:]) if at > 0 else (rest, None)
        valid = _NPM_NAME.fullmatch(name) is not None
    else:
        name, sep, given = rest.partition("==")
        if not sep:
            name, sep, given = rest.partition("@")
        version = given if sep else None
        valid = _PYPI_NAME.fullmatch(name) is not None
    if not valid or len(name) > MAX_PACKAGE_NAME:
        raise SourceRefused(f"{shown(name)} is not a {registry} package name intake takes")
    if ref is not None:
        if version is not None and version != ref:
            raise SourceRefused(f"the source names version {shown(version)} and ref= names "
                                f"{shown(ref)}: give one")
        version = ref
    if version is not None and _VERSION.fullmatch(version) is None:
        raise SourceRefused(f"{shown(version)} is not a version intake takes")
    return registry, name, version


def materialise(request: Request, writer: TreeWriter) -> Pinned:
    registry, name, version = parse(request.source, request.ref)
    if registry == "npm":
        found, url, digests, top = _npm(request, name, version)
    else:
        found, url, digests, top = _pypi(request, name, version)
    url = https_url(url)
    assert request.scratch is not None
    download = request.scratch / "package"
    fetch = request.fetcher("package", live_download)
    with open(download, "xb") as out:
        fetch(url, out, request.limits)
    pinned, checked = _verify(download, digests)
    kind = archive_format(download)
    if kind is None:
        raise ArchiveUnreadable(f"what {registry} serves for {shown(name)} {shown(found)} is not "
                                "an archive intake reads")
    unpack_file(download, kind, _Under(writer, top))
    notes = [f"{registry} package {shown(name)} {shown(found)}, from {shown(url)}",
             f"the archive matched the {checked} the registry publishes for it"]
    if version is None:
        notes.append(f"no version was given: the registry's latest, {shown(found)}, was taken")
    at = "@" if registry == "npm" else "=="
    return Pinned(origin=f"{registry}:{name}{at}{found}", pinned_ref=pinned, notes=tuple(notes))


# --- the registries -------------------------------------------------------------------------


def _metadata(request: Request, url: str) -> Any:
    fetch = request.fetcher("registry", live_metadata)
    body = fetch(https_url(url), request.limits)
    if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_METADATA_BYTES:
        raise FetchFailed("the registry's answer is not metadata intake can read")
    try:
        return json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise FetchFailed("the registry's answer is not JSON") from None


def live_metadata(url: str, limits: Limits) -> bytes:
    """The registry's JSON for url, bounded by MAX_METADATA_BYTES."""
    out = io.BytesIO()
    live_download(url, out, replace(limits, max_download_bytes=min(limits.max_download_bytes,
                                                                    MAX_METADATA_BYTES)))
    return out.getvalue()


def _npm(request: Request, name: str, version: str | None
         ) -> tuple[str, str, dict[str, str], tuple[str, ...]]:
    doc = _metadata(request, f"{NPM_REGISTRY}/{quote(name, safe='@')}/{quote(version or 'latest', safe='')}")
    dist = doc.get("dist") if isinstance(doc, dict) else None
    found = doc.get("version") if isinstance(doc, dict) else None
    if not isinstance(dist, dict) or not isinstance(found, str) or doc.get("name") != name:
        raise FetchFailed(f"npm has no metadata for {shown(name)} {shown(version or 'latest')}")
    if version is not None and found != version:
        raise FetchFailed(f"npm answered with version {shown(found)} for {shown(version)}")
    if _VERSION.fullmatch(found) is None:
        raise FetchFailed(f"npm names a version intake does not take ({shown(found)})")
    digests: dict[str, str] = {}
    integrity = dist.get("integrity")
    if isinstance(integrity, str):
        for part in integrity.split():
            algorithm, _dash, value = part.partition("-")
            if algorithm == "sha512":
                digests.setdefault("sha512", value)
    if isinstance(dist.get("shasum"), str):
        digests["sha1"] = dist["shasum"].lower()
    tarball = dist.get("tarball")
    if not isinstance(tarball, str):
        raise FetchFailed(f"npm names no archive for {shown(name)} {shown(found)}")
    return found, tarball, digests, ("package", name.rsplit("/", 1)[-1])


def _pypi(request: Request, name: str, version: str | None
          ) -> tuple[str, str, dict[str, str], tuple[str, ...]]:
    path = f"{quote(name, safe='')}/{quote(version, safe='')}/json" if version else f"{quote(name, safe='')}/json"
    doc = _metadata(request, f"{PYPI_REGISTRY}/{path}")
    info = doc.get("info") if isinstance(doc, dict) else None
    files = doc.get("urls") if isinstance(doc, dict) else None
    found = info.get("version") if isinstance(info, dict) else None
    if not isinstance(found, str) or not isinstance(files, list):
        raise FetchFailed(f"PyPI has no metadata for {shown(name)} {shown(version or 'latest')}")
    if version is not None and found != version:
        raise FetchFailed(f"PyPI answered with version {shown(found)} for {shown(version)}")
    if _VERSION.fullmatch(found) is None:
        raise FetchFailed(f"PyPI names a version intake does not take ({shown(found)})")
    files = [f for f in files if isinstance(f, dict) and isinstance(f.get("filename"), str)
             and isinstance(f.get("url"), str) and not f.get("yanked")]
    chosen = next((f for f in files if f.get("packagetype") == "sdist"
                   and f["filename"].endswith(_SDIST)), None)
    top: tuple[str, ...] = ()
    if chosen is not None:
        top = tuple(chosen["filename"][: -len(suffix)] for suffix in _SDIST
                    if chosen["filename"].endswith(suffix))[:1]
    else:
        chosen = next((f for f in files if f.get("packagetype") == "bdist_wheel"
                       and _PURE_WHEEL.search(f["filename"])), None)
    if chosen is None:
        raise SourceRefused(f"PyPI has no source distribution or pure-Python wheel of "
                            f"{shown(name)} {shown(found)}: nothing intake can read without building")
    digests = chosen.get("digests") if isinstance(chosen.get("digests"), dict) else {}
    sha256 = digests.get("sha256")
    return found, chosen["url"], ({"sha256": sha256.lower()} if isinstance(sha256, str) else {}), top


# --- the archive ----------------------------------------------------------------------------


def _verify(path, digests: dict[str, str]) -> tuple[str, str]:
    """The archive's pin ("sha256:<hex>"), and which published digest it matched; UnsafeArtifact
    when it matches none, SourceRefused when the registry publishes none."""
    if not digests:
        raise SourceRefused("the registry publishes no digest for the archive, so what arrives "
                            "could not be checked against what was published")
    sha256, sha512, sha1 = hashlib.sha256(), hashlib.sha512(), hashlib.sha1(usedforsecurity=False)
    with open(path, "rb") as reader:
        while chunk := reader.read(_CHUNK):
            for hasher in (sha256, sha512, sha1):
                hasher.update(chunk)
    actual = {"sha256": sha256.hexdigest(), "sha1": sha1.hexdigest(),
              "sha512": base64.b64encode(sha512.digest()).decode("ascii")}
    for algorithm in ("sha512", "sha256", "sha1"):
        if algorithm in digests:
            if digests[algorithm] != actual[algorithm]:
                raise UnsafeArtifact(f"the archive does not match the {algorithm} digest the "
                                     "registry publishes for it: it is not what was published")
            return f"sha256:{actual['sha256']}", f"{algorithm} digest"
    raise SourceRefused("the registry publishes no digest intake can check for the archive")


class _Under:
    """A TreeWriter that takes the first of the folders `tops` a name is in off its front
    (names in none of them are written as they are)."""

    def __init__(self, writer: TreeWriter, tops: tuple[str, ...]) -> None:
        self._writer = writer
        self._tops = tuple(top for top in tops if top)
        self.limits = writer.limits

    def _strip(self, name: Any) -> str:
        rel = clean_name(name, max_bytes=self.limits.max_name_bytes)
        for top in self._tops:
            if rel == top:
                return ""
            if rel.startswith(top + "/"):
                return rel[len(top) + 1:]
        return rel

    def name(self, name: Any, *, backslash_is_separator: bool = False) -> str:
        return self._writer.name(name, backslash_is_separator=backslash_is_separator)

    def directory(self, name: str) -> None:
        self._writer.directory(self._strip(name))

    def file(self, name: str, data, *, size: int | None = None, executable: bool = False) -> str:
        return self._writer.file(self._strip(name), data, size=size, executable=executable)

    def symlink(self, name: str, target: Any) -> None:
        self._writer.symlink(self._strip(name), target)

    def copy(self, name: str, existing: Any, *, backslash_is_separator: bool = False) -> str:
        return self._writer.copy(self._strip(name), self._strip(existing),
                                 backslash_is_separator=backslash_is_separator)

    def withhold(self, name: str, reason: str) -> None:
        self._writer.withhold(self._strip(name) or name, reason)
