"""The hidden prompt refuses a value holding control characters (owner's production host,
30 September 2026: an arrow key's escape code was stored inside the engineering token, twice,
and every call with it failed)."""

from __future__ import annotations

import pytest

from scripts import provision_secrets as ps
from tests.fake_credentials import github_fine_grained_token


@pytest.fixture
def stored(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(ps, "where", lambda key: "")
    monkeypatch.setattr(ps, "have_systemd_creds", lambda: True)
    monkeypatch.setattr(ps, "encrypt", lambda key, value: calls.append((key, value)))
    monkeypatch.setattr(ps.keychain, "set_secret", lambda key, value: calls.append((key, value)))
    return calls


@pytest.mark.parametrize("junk", ["\x1b[A", "\x1b[B\x1b[A", "\x1b", "\x7f", "\x9b", "\x00"])
def test_a_value_with_control_characters_is_refused_and_never_stored_or_printed(monkeypatch, capsys, stored, junk):
    token = github_fine_grained_token("prompt")
    monkeypatch.setattr(ps.getpass, "getpass", lambda prompt: junk + token)
    assert ps.store_one("github_engineering_inbox_token", plain=False) == 1
    assert stored == []
    out = capsys.readouterr().out
    assert "control character" in out and "nothing was stored" in out
    assert token not in out


def test_a_clean_value_is_stored_as_typed(monkeypatch, stored):
    token = github_fine_grained_token("prompt")
    monkeypatch.setattr(ps.getpass, "getpass", lambda prompt: "  " + token + "\n")
    assert ps.store_one("github_engineering_inbox_token", plain=False) == 0
    assert stored == [("github_engineering_inbox_token", token)]


def test_control_characters_counts_only_control_characters():
    assert ps.control_characters("abc_DEF-123") == 0
    assert ps.control_characters("\x1b[Aabc\x1b[B") == 2
    assert ps.control_characters("café") == 0
