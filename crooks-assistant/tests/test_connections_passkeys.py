"""The passkey check every change to a connection asks for (app/connections/passkeys.py).

Real keys, made per test by the stand-in authenticator (tests/fake_passkey.py), and every way an
approval can fail to hold: another site, another action, a second use, too slow, no Face ID,
another key, a copied passkey whose counter goes backwards.
"""

from __future__ import annotations

import json
import stat

import pytest

from app.connections import passkeys
from tests.fake_passkey import (
    EDDSA,
    ES256,
    ORIGIN,
    RP_ID,
    RS256,
    Authenticator,
    b64url,
    cbor,
    unb64url,
)

OWNER = "owner@example.com"


@pytest.fixture(autouse=True)
def state(tmp_path):
    folder = tmp_path / "app"
    passkeys.configure(state_dir=folder)
    passkeys.reset()
    yield folder
    passkeys.configure(state_dir=None)
    passkeys.reset()


def register(device: Authenticator, *, approved: bool = False, label: str = "iPhone") -> dict:
    options = passkeys.begin_registration(login=OWNER, origin=ORIGIN, rp_id=RP_ID, approved=approved)
    return passkeys.finish_registration(device.create(options), login=OWNER, origin=ORIGIN, label=label)


def approve(device: Authenticator, action: str = "save:elevenlabs", **kw) -> dict:
    options = passkeys.begin_approval(action, login=OWNER, origin=ORIGIN, rp_id=RP_ID)
    return passkeys.verify_approval(device.get(options, **kw), action, login=OWNER, origin=ORIGIN)


# ------------------------------------------------------------------ registration and approval

@pytest.mark.parametrize("alg", [ES256, EDDSA, RS256], ids=["es256", "ed25519", "rs256"])
def test_a_registered_passkey_approves_a_change(alg):
    device = Authenticator(alg)
    shown = register(device)
    assert shown["label"] == "iPhone" and shown["id"] == b64url(device.credential_id)
    used = approve(device)
    assert used["id"] == shown["id"]
    assert passkeys.registered()[0]["last_used_at"]


def test_the_record_holds_public_keys_only_root_only(state):
    device = Authenticator()
    register(device)
    path = state / passkeys.FILE_NAME
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    record = json.loads(path.read_text())["credentials"][0]
    assert set(record) == {"id", "alg", "public_key", "sign_count", "login", "label", "rp_id", "origin",
                           "created_at", "last_used_at"}
    assert "PRIVATE" not in path.read_text()
    assert set(passkeys.registered()[0]) == {"id", "label", "created_at", "last_used_at"}


def test_a_second_passkey_needs_the_first_to_approve_it():
    register(Authenticator())
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        passkeys.begin_registration(login=OWNER, origin=ORIGIN, rp_id=RP_ID, approved=False)
    assert refused.value.code == "passkey_approval_needed"
    second = Authenticator(EDDSA)
    register(second, approved=True, label="Samsung tablet")
    assert [p["label"] for p in passkeys.registered()] == ["iPhone", "Samsung tablet"]


def test_a_first_passkey_prompt_left_open_cannot_become_a_second_passkey():
    """Two prompts opened while none was registered: the one finished second would otherwise be
    a passkey nobody approved."""
    early = Authenticator()
    options = passkeys.begin_registration(login=OWNER, origin=ORIGIN, rp_id=RP_ID, approved=False)
    register(Authenticator())
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        passkeys.finish_registration(early.create(options), login=OWNER, origin=ORIGIN, label="?")
    assert refused.value.code == "passkey_approval_needed"
    assert passkeys.count() == 1


def test_the_same_passkey_is_not_registered_twice():
    device = Authenticator()
    register(device)
    options = passkeys.begin_registration(login=OWNER, origin=ORIGIN, rp_id=RP_ID, approved=True)
    assert options["excludeCredentials"] == [{"type": "public-key", "id": b64url(device.credential_id)}]
    with pytest.raises(passkeys.PasskeyRefused):
        passkeys.finish_registration(device.create(options), login=OWNER, origin=ORIGIN, label="again")


def test_with_no_passkey_registered_an_approval_cannot_even_be_asked_for():
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        passkeys.begin_approval("save:elevenlabs", login=OWNER, origin=ORIGIN, rp_id=RP_ID)
    assert refused.value.code == "passkey_none"


def test_options_ask_for_user_verification_and_no_attestation():
    options = passkeys.begin_registration(login=OWNER, origin=ORIGIN, rp_id=RP_ID, approved=False)
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["attestation"] == "none"
    assert options["rp"] == {"id": RP_ID, "name": "CLIVE"}
    assert {p["alg"] for p in options["pubKeyCredParams"]} == {ES256, EDDSA, RS256}


# ------------------------------------------------------------------ approvals that do not hold

def test_an_approval_is_for_one_action_only():
    device = Authenticator()
    register(device)
    options = passkeys.begin_approval("save:elevenlabs", login=OWNER, origin=ORIGIN, rp_id=RP_ID)
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        passkeys.verify_approval(device.get(options), "disconnect:shopify", login=OWNER, origin=ORIGIN)
    assert refused.value.code == "passkey_stale"


def test_an_approval_is_good_once():
    device = Authenticator()
    register(device)
    options = passkeys.begin_approval("save:elevenlabs", login=OWNER, origin=ORIGIN, rp_id=RP_ID)
    assertion = device.get(options)
    passkeys.verify_approval(assertion, "save:elevenlabs", login=OWNER, origin=ORIGIN)
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        passkeys.verify_approval(assertion, "save:elevenlabs", login=OWNER, origin=ORIGIN)
    assert refused.value.code == "passkey_stale"


def test_an_approval_left_too_long_is_refused(monkeypatch):
    device = Authenticator()
    register(device)
    options = passkeys.begin_approval("save:elevenlabs", login=OWNER, origin=ORIGIN, rp_id=RP_ID)
    later = passkeys.time.monotonic() + passkeys.CHALLENGE_S + 1
    monkeypatch.setattr(passkeys.time, "monotonic", lambda: later)
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        passkeys.verify_approval(device.get(options), "save:elevenlabs", login=OWNER, origin=ORIGIN)
    assert refused.value.code == "passkey_stale"


def test_an_approval_without_face_id_or_a_pin_is_refused():
    device = Authenticator()
    register(device)
    device.uv = False
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        approve(device)
    assert refused.value.code == "passkey_unverified"


def test_a_registration_without_user_verification_is_refused():
    device = Authenticator()
    device.uv = False
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        register(device)
    assert refused.value.code == "passkey_unverified"
    assert passkeys.count() == 0


def test_an_approval_with_nobody_present_is_refused():
    device = Authenticator()
    register(device)
    device.up = False
    with pytest.raises(passkeys.PasskeyRefused, match="did not see you there"):
        approve(device)


def test_a_prompt_from_another_page_is_refused():
    device = Authenticator()
    register(device)
    options = passkeys.begin_approval("save:elevenlabs", login=OWNER, origin=ORIGIN, rp_id=RP_ID)
    device.origin = "https://evil.example"
    with pytest.raises(passkeys.PasskeyRefused, match="did not come from this CLIVE"):
        passkeys.verify_approval(device.get(options), "save:elevenlabs", login=OWNER, origin=ORIGIN)


def test_a_prompt_from_inside_another_site_is_refused():
    device = Authenticator()
    register(device)
    options = passkeys.begin_approval("save:elevenlabs", login=OWNER, origin=ORIGIN, rp_id=RP_ID)
    with pytest.raises(passkeys.PasskeyRefused, match="inside another site"):
        passkeys.verify_approval(device.get(options, crossOrigin=True), "save:elevenlabs",
                                 login=OWNER, origin=ORIGIN)


def test_a_passkey_made_for_another_site_is_refused():
    device = Authenticator()
    register(device)
    device.rp_id = "elsewhere.example"
    with pytest.raises(passkeys.PasskeyRefused, match="made for another site"):
        approve(device)


def test_a_signature_from_another_key_is_refused():
    device = Authenticator()
    register(device)
    impostor = Authenticator()
    impostor.credential_id = device.credential_id          # claims to be the registered passkey
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        approve(impostor)
    assert refused.value.code == "passkey_signature"


def test_a_passkey_that_is_not_registered_is_refused():
    register(Authenticator())
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        approve(Authenticator())
    assert refused.value.code == "passkey_unknown"


def test_a_counter_that_goes_backwards_is_refused_and_one_that_stays_at_zero_is_not():
    device = Authenticator()
    register(device)
    approve(device, count=0)
    approve(device, count=0)                                # Apple's passkeys always say 0
    approve(device, count=5)
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        approve(device, count=5)
    assert refused.value.code == "passkey_counter"


def test_an_approval_opened_by_another_login_is_refused():
    device = Authenticator()
    register(device)
    options = passkeys.begin_approval("save:elevenlabs", login="someone@example.com", origin=ORIGIN, rp_id=RP_ID)
    with pytest.raises(passkeys.PasskeyRefused, match="opened by someone else"):
        passkeys.verify_approval(device.get(options), "save:elevenlabs", login=OWNER, origin=ORIGIN)


def test_a_registration_answer_is_not_an_approval():
    device = Authenticator()
    register(device)
    options = passkeys.begin_approval("save:elevenlabs", login=OWNER, origin=ORIGIN, rp_id=RP_ID)
    created = device.create(options)
    forged = {"id": created["id"], "rawId": created["rawId"], "response": {
        "clientDataJSON": created["response"]["clientDataJSON"], "authenticatorData": b64url(b"x" * 37),
        "signature": b64url(b"x")}}
    with pytest.raises(passkeys.PasskeyRefused, match="different kind of prompt"):
        passkeys.verify_approval(forged, "save:elevenlabs", login=OWNER, origin=ORIGIN)


@pytest.mark.parametrize("assertion", [
    None, "a string", {}, {"response": "not a dict"},
    {"id": "x", "response": {"clientDataJSON": "!!!", "authenticatorData": "", "signature": ""}},
    {"id": "x", "response": {"clientDataJSON": "a" * (passkeys.MAX_FIELD + 1)}},
])
def test_anything_that_is_not_a_passkey_is_a_refusal_never_a_crash(assertion):
    register(Authenticator())
    with pytest.raises(passkeys.PasskeyRefused):
        passkeys.verify_approval(assertion, "save:elevenlabs", login=OWNER, origin=ORIGIN)


def test_removing_a_passkey():
    device = Authenticator()
    shown = register(device)
    assert passkeys.remove(shown["id"]) is True
    assert passkeys.remove(shown["id"]) is False
    assert passkeys.count() == 0


def test_without_a_place_to_keep_them_passkeys_say_so():
    passkeys.configure(state_dir=None)
    with pytest.raises(passkeys.PasskeyRefused) as refused:
        passkeys.begin_registration(login=OWNER, origin=ORIGIN, rp_id=RP_ID, approved=False)
    assert refused.value.code == "passkeys_unconfigured"


# ------------------------------------------------------------------ the CBOR reader

def test_cbor_reads_what_webauthn_sends_and_refuses_the_rest():
    data = cbor({"fmt": "none", "attStmt": {}, "authData": b"\x01\x02", 3: -7, "list": [1, -1, True]})
    value, end = passkeys.cbor_decode(data)
    assert end == len(data)
    assert value == {"fmt": "none", "attStmt": {}, "authData": b"\x01\x02", 3: -7, "list": [1, -1, True]}
    for bad in (b"\x9f\x01\xff",            # an indefinite-length array
                b"\xfb" + bytes(8),         # a float
                b"\x5a\x00\x00\x10\x00",    # bytes that run past the end
                b"\x81" * 12 + b"\x01"):    # nested too deeply
        with pytest.raises(passkeys.PasskeyRefused):
            passkeys.cbor_decode(bad)
    assert unb64url(b64url(b"\x00\xff")) == b"\x00\xff"
