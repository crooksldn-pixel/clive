"""Builder skills: exactly the owner's curated skills, each pinned by the hash of every file, and nothing else.

The owner's decision of 30 September 2026 (OWNER_DECISIONS_2026-09-30.md, "The owner's curated skill list is
the owner's decision"): a skill on his list needs no further sign-off. The list the loop's builders get is
``crooks-assistant/config/builder_skills.json`` (schema ``clive.builder_skills.v1``), a protected path read
from the loop's own pinned checkout, never from a task's base or a candidate. It names each skill, where its
files come from and the sha256 of every one of them:

- ``source: "repo"``: a skill vendored in the repository (``.claude/skills/<name>``), read from git's objects
  at the task's base commit in the engineering repo;
- ``source: "installed"``: a skill the skill installer put on the build server
  (``<installed dir>/<name>/skill/``, app/skills/install.py), read from that folder.

Per attempt the dispatcher builds the skills folder, a Claude Code plugin called ``clive-skills``, inside the
attempt's own fresh HOME, outside the workspace the builder's file tools are confined to:

    <home>/clive-skills/.claude-plugin/plugin.json
    <home>/clive-skills/skills/<name>/<file>        exactly the listed files, read-only

A skill is given to the builder only when its source holds exactly the listed files with exactly the listed
hashes. Any difference withholds that skill, says why in the launch notes, and loads nothing in its place.
Whatever the list says, a skill that would run something on its own is refused: a ``hooks`` key in its
front matter, a ``!`command``` line (Claude Code runs those before the model reads the skill), or a file that
is not text. The same rules as the skill installer's (app/skills/install.py). The plugin carries skills only:
no hooks, no MCP servers, no commands, no agents.

The launch check (workers/claude.py ``verify_started``) then holds the CLI to it: the init event's skills
must be exactly ``clive-skills:<name>`` for the skills in the folder, and the plugin exactly this folder.
Anything else, or anything missing, is a refused launch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

__all__ = [
    "ALLOW_LIST",
    "PLUGIN_NAME",
    "SCHEMA",
    "AllowList",
    "Built",
    "SkillEntry",
    "SkillsError",
    "build_plugin",
    "entry_for",
    "load_allow_list",
    "settings_json",
    "skill_id",
]

APP_ROOT = Path(__file__).resolve().parents[3]          # crooks-assistant
ALLOW_LIST = APP_ROOT / "config" / "builder_skills.json"
SCHEMA = "clive.builder_skills.v1"
PLUGIN_NAME = "clive-skills"
SKILL_FILE = "SKILL.md"
SOURCES = ("repo", "installed")
MAX_FILES = 200
MAX_BYTES = 2 * 1024 * 1024
TEXT_SUFFIXES = frozenset({".md", ".txt"})

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
# The skill installer's own rules (app/skills/install.py ``_HOOKS_KEY``, ``_COMMAND``), kept here so the loop's
# driver does not import the digester.
_HOOKS_KEY = re.compile(r"""[ \t]*["']?hooks["']?[ \t]*:""", re.I)
_COMMAND = "!`"


class SkillsError(ValueError):
    """The allow-list itself is malformed: no skill is given to any builder until it is corrected."""


@dataclass(frozen=True)
class SkillEntry:
    name: str
    source: str
    path: str                       # repo: the folder's repository path; installed: unused ("")
    files: tuple[tuple[str, str], ...]   # (relative path, sha256), sorted


@dataclass(frozen=True)
class AllowList:
    skills: tuple[SkillEntry, ...]
    # Skills the pinned Claude Code CLI ships inside itself that ``disableBundledSkills`` does not switch off:
    # switched off by name for builders (``skillOverrides``). A name here can only take a skill away.
    cli_skills_off: tuple[str, ...] = ()


@dataclass(frozen=True)
class Built:
    folder: Path | None                       # the plugin folder, or None when no skill could be given
    provided: tuple[str, ...]                 # skill names in it
    withheld: tuple[tuple[str, str], ...]     # (name, why) for every listed skill not given


def skill_id(name: str) -> str:
    """How the CLI names a plugin's skill in its init event and the Skill tool."""
    return f"{PLUGIN_NAME}:{name}"


def _rel(value: object) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise SkillsError("a skill file is named by a plain relative path")
    parts = value.split("/")
    if any(not _PART.fullmatch(p) or p in (".", "..") for p in parts):
        raise SkillsError("a skill file is named by a plain relative path")
    return value


def load_allow_list(path: Path = ALLOW_LIST) -> AllowList:
    """The owner's list, validated whole. Absent: no skills (an empty list). Malformed: SkillsError."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AllowList(skills=())
    except (OSError, ValueError) as exc:
        raise SkillsError(f"the builder skill list could not be read ({type(exc).__name__})") from None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise SkillsError(f"the builder skill list is not {SCHEMA}")
    entries, seen = [], set()
    for raw in data.get("skills") or ():
        if not isinstance(raw, dict):
            raise SkillsError("each listed skill is an object")
        name, source = raw.get("name"), raw.get("source")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in seen:
            raise SkillsError("each listed skill has a unique lowercase name")
        if source not in SOURCES:
            raise SkillsError(f"skill {name}: source is one of {', '.join(SOURCES)}")
        folder = ""
        if source == "repo":
            folder = _rel(raw.get("path"))
        files = raw.get("files")
        if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
            raise SkillsError(f"skill {name}: files maps each file to its sha256")
        pinned = []
        for rel, digest in files.items():
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise SkillsError(f"skill {name}: every file has a sha256")
            pinned.append((_rel(rel), digest))
        if SKILL_FILE not in dict(pinned):
            raise SkillsError(f"skill {name}: {SKILL_FILE} is listed")
        seen.add(name)
        entries.append(SkillEntry(name=name, source=source, path=folder, files=tuple(sorted(pinned))))
    off = data.get("cli_skills_off") or []
    if not isinstance(off, list) or any(not isinstance(n, str) or not _NAME.fullmatch(n) for n in off):
        raise SkillsError("cli_skills_off lists skill names")
    return AllowList(skills=tuple(entries), cli_skills_off=tuple(off))


def settings_json(allow: AllowList) -> str:
    """The session settings a skills launch passes with ``--settings``: the CLI's own bundled skills off, and
    the ones it ships in its built-in plugins off by name. Only ever takes skills away."""
    return json.dumps({"disableBundledSkills": True,
                       "skillOverrides": {name: "off" for name in allow.cli_skills_off}},
                      separators=(",", ":"), sort_keys=True)


# ------------------------------------------------------------------ reading a skill's files from its source


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=str(repo), capture_output=True,
                          timeout=60, check=False)


def _from_repo(entry: SkillEntry, repo: Path, sha: str) -> dict[str, bytes]:
    """The folder's files at ``sha``, from git's objects: every one a plain file (mode 100644)."""
    if not _SHA1.fullmatch(sha or ""):
        raise LookupError("no base commit to read it from")
    listed = _git(repo, "ls-tree", "-r", "-z", sha, "--", entry.path)
    if listed.returncode != 0:
        raise LookupError("its folder could not be listed at the base commit")
    out: dict[str, bytes] = {}
    for record in listed.stdout.split(b"\0"):
        if not record:
            continue
        meta, _, name = record.partition(b"\t")
        mode, kind, blob = meta.decode().split()
        rel = name.decode("utf-8", "replace")
        rel = rel[len(entry.path) + 1:] if rel.startswith(entry.path + "/") else rel
        if kind != "blob" or mode != "100644":
            raise LookupError(f"{rel} is not a plain file (git mode {mode})")
        shown = _git(repo, "cat-file", "blob", blob)
        if shown.returncode != 0:
            raise LookupError(f"{rel} could not be read at the base commit")
        out[rel] = shown.stdout
        if len(out) > MAX_FILES:
            raise LookupError("it has more files than any listed skill may")
    if not out:
        raise LookupError(f"{entry.path} is not at the base commit")
    return out


def _from_folder(folder: Path) -> dict[str, bytes]:
    """Every file under ``folder``: plain files only, no link anywhere on the way."""
    if folder.is_symlink() or not folder.is_dir():
        raise LookupError("its installed folder is not there")
    out: dict[str, bytes] = {}
    for root, dirs, files in os.walk(folder, followlinks=False):
        for name in (*dirs, *files):
            path = Path(root) / name
            if path.is_symlink():
                raise LookupError(f"{path.relative_to(folder)} is a link")
        for name in files:
            path = Path(root) / name
            if not path.is_file():
                raise LookupError(f"{path.relative_to(folder)} is not a plain file")
            out[path.relative_to(folder).as_posix()] = path.read_bytes()
            if len(out) > MAX_FILES:
                raise LookupError("it has more files than any listed skill may")
    return out


def _refusal(files: dict[str, bytes]) -> str | None:
    """Why a skill may not be given whatever the list says: something in it would run on its own."""
    for rel, data in sorted(files.items()):
        if PurePosixPath(rel).suffix.lower() not in TEXT_SUFFIXES or data.startswith(b"#!"):
            return f"{rel} is not a text file (a skill that carries anything else waits for the owner)"
        text = data.decode("utf-8", "replace").removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        if PurePosixPath(rel).name == SKILL_FILE and lines and lines[0].strip() == "---":
            end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), len(lines))
            if any(_HOOKS_KEY.match(line) for line in lines[1:end]):
                return f"a hooks key in the front matter of {rel}"
        number = next((n for n, line in enumerate(lines, 1) if _COMMAND in line), 0)
        if number:
            return f"a !`command` on line {number} of {rel}, which Claude Code would run on its own"
    return None


def _verified(entry: SkillEntry, files: dict[str, bytes]) -> str | None:
    """None when ``files`` is exactly the listed files with exactly the listed hashes; else what differs."""
    wanted = dict(entry.files)
    extra = sorted(set(files) - set(wanted))
    missing = sorted(set(wanted) - set(files))
    if extra:
        return f"its folder holds file(s) the list does not name: {', '.join(extra[:5])}"
    if missing:
        return f"listed file(s) missing: {', '.join(missing[:5])}"
    if sum(len(d) for d in files.values()) > MAX_BYTES:
        return "it is larger than any listed skill may be"
    changed = sorted(rel for rel, data in files.items() if hashlib.sha256(data).hexdigest() != wanted[rel])
    if changed:
        return f"content differs from the hash the list pins: {', '.join(changed[:5])}"
    return _refusal(files)


# ------------------------------------------------------------------ the plugin folder


def build_plugin(allow: AllowList, dest: Path, *, repo: Path, base_sha: str, installed_dir: Path | None) -> Built:
    """Build ``dest`` (removed first) as the ``clive-skills`` plugin with every listed skill that verifies.

    Nothing is written for a skill that does not verify, and no folder at all when none does."""
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    remove_plugin(dest)
    provided: list[tuple[str, dict[str, bytes]]] = []
    withheld: list[tuple[str, str]] = []
    for entry in allow.skills:
        try:
            if entry.source == "repo":
                files = _from_repo(entry, repo, base_sha)
            elif installed_dir is None:
                raise LookupError("no installed-skills folder is configured on this build server")
            else:
                files = _from_folder(Path(installed_dir) / entry.name / "skill")
        except (LookupError, OSError, UnicodeDecodeError, ValueError, subprocess.SubprocessError) as exc:
            withheld.append((entry.name, f"not readable: {exc}"[:300]))
            continue
        problem = _verified(entry, files)
        if problem is not None:
            withheld.append((entry.name, problem[:300]))
            continue
        provided.append((entry.name, files))
    if not provided:
        return Built(folder=None, provided=(), withheld=tuple(withheld))
    manifest = dest / ".claude-plugin"
    manifest.mkdir(parents=True)
    (manifest / "plugin.json").write_text(json.dumps({
        "name": PLUGIN_NAME, "version": "1.0.0",
        "description": "The owner's curated skills for CLIVE's builders (config/builder_skills.json)",
    }, indent=2) + "\n", encoding="utf-8")
    for name, files in provided:
        for rel, data in files.items():
            target = dest / "skills" / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o444)
    for root, dirs, _files in os.walk(dest):
        for name in dirs:
            (Path(root) / name).chmod(0o555)
    (manifest / "plugin.json").chmod(0o444)
    dest.chmod(0o555)
    return Built(folder=dest, provided=tuple(name for name, _ in provided), withheld=tuple(withheld))


def remove_plugin(dest: Path) -> None:
    """Take a built folder down again (its folders are read-only, so they are made writable first)."""
    if not dest.exists():
        return
    for root, dirs, _files in os.walk(dest):
        Path(root).chmod(0o755)
        for name in dirs:
            (Path(root) / name).chmod(0o755)
    shutil.rmtree(dest)


def entry_for(name: str, folder: Path, *, source: str = "installed", path: str = "") -> dict:
    """The allow-list entry for the skill in ``folder``, hashed now: what a Director adds to
    config/builder_skills.json (through a reviewed change) for a curated skill the installer put on the host."""
    if not _NAME.fullmatch(name or ""):
        raise SkillsError("a skill name is lowercase letters, digits and hyphens")
    files = _from_folder(Path(folder))
    problem = _refusal(files)
    if problem is not None:
        raise SkillsError(f"{name} cannot be a builder skill: {problem}")
    entry = {"name": name, "source": source, "files": {rel: hashlib.sha256(data).hexdigest()
                                                       for rel, data in sorted(files.items())}}
    if source == "repo":
        entry["path"] = path
    return entry
