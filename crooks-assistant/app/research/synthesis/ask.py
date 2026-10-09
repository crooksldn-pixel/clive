"""How every synthesis step asks the model, and reads what it says.

Why this exists: five steps of the synthesis (extract, match, consolidate, judge, summary) ask Claude
on the Max plan (app/research/model.py). They share the same three needs: research goes in only as
data, inside <research> tags it cannot close; each call has a time limit of its own and is counted for
run.json; and an answer that is not the JSON asked for is an error with words, never "nothing".

What it promises:
- `research(...)` is the only way research text enters a prompt. Inside it, anything that looks like a
  <research> or </research> tag is defused, so the research can't end its own block.
- `Calls.ask` counts every call it makes, made or failed, and gives each its stage's time limit when
  the model can take one (MaxPlanModel.with_timeout); a scripted model is asked as it is.
- `parse_object` returns the JSON object in an answer (fenced or bare) or raises SynthesisError.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Seconds each stage may take for one call. A judge call reads CLIVE's whole design and three ideas
# with every quote, so it can need ten minutes; `scripts/research.py --call-timeout` replaces them all.
STAGE_TIMEOUT_S = {"extract": 600.0, "repair": 300.0, "match": 600.0, "consolidate": 600.0,
                   "judge": 900.0, "owner_view": 600.0, "summary": 600.0}


class SynthesisError(Exception):
    """A synthesis step could not finish, said in words."""


class Calls:
    """The model, and how many times it has been asked, by stage."""

    def __init__(self, model, *, timeout_s: float | None = None) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self.made = 0
        self.by_stage: dict[str, int] = {}

    @property
    def name(self) -> str:
        return str(getattr(self.model, "name", "model"))

    async def ask(self, stage: str, system: str, prompt: str) -> str:
        self.made += 1
        self.by_stage[stage] = self.by_stage.get(stage, 0) + 1
        model = self.model
        limit = self.timeout_s or STAGE_TIMEOUT_S.get(stage)
        if limit and hasattr(model, "with_timeout"):
            model = model.with_timeout(limit)
        return await model.ask(system, prompt)


_TAG = re.compile(r"<(/?)(research\b)", re.IGNORECASE)


def data(text: Any) -> str:
    """Research text made safe to sit inside a <research> block: it cannot open or close one."""
    return _TAG.sub(lambda m: f"‹{m.group(1)}{m.group(2)}", str(text or ""))


def research(body: str, **attrs: str) -> str:
    """A block of research, as data. Attributes are JSON strings (names may hold any character)."""
    said = "".join(f" {k}={json.dumps(str(v))}" for k, v in attrs.items() if v not in (None, ""))
    return f"<research{said}>\n{data(body)}\n</research>"


def parse_object(answer: str, what: str) -> dict[str, Any]:
    """The JSON object in the model's answer, or SynthesisError naming `what` was asked for."""
    text = str(answer or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise SynthesisError(f"Claude's answer wasn't the {what} CLIVE asked for.")
    try:
        found = json.loads(text[start:end + 1])
    except ValueError:
        raise SynthesisError(f"Claude's answer ({what}) wasn't readable JSON.") from None
    if not isinstance(found, dict):
        raise SynthesisError(f"Claude's answer ({what}) wasn't a JSON object.")
    return found


def line(value: Any, limit: int) -> str:
    """One line of plain text, at most `limit` characters."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def items(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def strings(value: Any, limit: int, most: int) -> list[str]:
    out = []
    for v in value if isinstance(value, list) else []:
        said = line(v, limit) if isinstance(v, str | int | float) else ""
        if said and said not in out:
            out.append(said)
    return out[:most]


def words_at_most(text: str, n: int) -> str:
    parts = str(text or "").split()
    return " ".join(parts[:n])
