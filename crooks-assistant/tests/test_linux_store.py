"""The Linux secret store, and the platform dispatch in front of it.

Nothing here touches a real Keychain, a real systemd, or the network. `linux_store` is plain
file handling and runs identically on either platform, so these tests are meaningful on the
Mac too — which matters, because the Mac runs this suite and must be able to prove it did not
break the backend it does not use.
"""

from __future__ import annotations

import stat

import pytest

from app.secrets import keychain, linux_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A writable tier in a temporary directory, and no systemd credentials."""
    directory = tmp_path / "secrets"
    monkeypatch.setenv(linux_store.STORE_DIR_ENV, str(directory))
    monkeypatch.delenv(linux_store.CREDENTIALS_ENV, raising=False)
    return directory


@pytest.fixture
def creds(tmp_path, monkeypatch):
    """A systemd credentials directory beside the writable tier."""
    directory = tmp_path / "creds"
    directory.mkdir()
    monkeypatch.setenv(linux_store.CREDENTIALS_ENV, str(directory))
    return directory


# Captured at import, before conftest's `_no_secrets` fixture replaces them for each test.
# That fixture exists so no test can reach the owner's login Keychain, and it is right; these
# tests need the genuine functions, so they put them back — together with the Linux dispatch,
# which is what makes doing so safe. With `_on_linux()` forced true, every call lands in a
# temporary directory and `keyring` is never imported, on either platform.
_REAL = {
    name: getattr(keychain, name)
    for name in ("get", "get_optional", "present", "set_secret", "delete", "where")
}


@pytest.fixture
def on_linux(monkeypatch):
    """Dispatch to the Linux backend, with the real implementations behind it."""
    monkeypatch.setattr(keychain, "_on_linux", lambda: True)
    for name, function in _REAL.items():
        monkeypatch.setattr(keychain, name, function)


# --------------------------------------------------------------- the writable tier


def test_round_trip_through_the_writable_tier(store):
    linux_store.write("elevenlabs_api_key", "sk-value")
    assert linux_store.read("elevenlabs_api_key") == "sk-value"
    assert linux_store.where("elevenlabs_api_key") == "file"
    linux_store.remove("elevenlabs_api_key")
    assert linux_store.read("elevenlabs_api_key") is None
    assert linux_store.where("elevenlabs_api_key") == ""


def test_the_directory_is_0700_and_the_file_is_0600(store):
    linux_store.write("elevenlabs_api_key", "sk-value")
    assert stat.S_IMODE(store.stat().st_mode) == 0o700
    assert stat.S_IMODE((store / "elevenlabs_api_key").stat().st_mode) == 0o600


def test_a_loose_directory_mode_is_tightened(store):
    store.mkdir(parents=True)
    store.chmod(0o755)
    linux_store.write("elevenlabs_api_key", "sk-value")
    assert stat.S_IMODE(store.stat().st_mode) == 0o700


def test_no_temporary_file_is_left_behind(store):
    linux_store.write("elevenlabs_api_key", "sk-value")
    assert [p.name for p in store.iterdir()] == ["elevenlabs_api_key"]


def test_removing_an_absent_secret_is_not_an_error(store):
    linux_store.remove("elevenlabs_api_key")   # must not raise


def test_a_trailing_newline_is_stripped(store):
    store.mkdir(parents=True)
    (store / "elevenlabs_api_key").write_text("sk-value\n", encoding="utf-8")
    assert linux_store.read("elevenlabs_api_key") == "sk-value"


def test_an_empty_file_reads_as_absent(store):
    store.mkdir(parents=True)
    (store / "elevenlabs_api_key").write_text("   \n", encoding="utf-8")
    assert linux_store.read("elevenlabs_api_key") is None


# --------------------------------------------------------------- the systemd tier


def test_systemd_credentials_win_over_the_file(store, creds):
    (creds / "shopify_client_id").write_text("from-systemd\n", encoding="utf-8")
    linux_store.write("gmail_token", "in-the-file")       # a key systemd does not provide
    store.mkdir(parents=True, exist_ok=True)
    (store / "shopify_client_id").write_text("stale-file-copy", encoding="utf-8")
    assert linux_store.read("shopify_client_id") == "from-systemd"
    assert linux_store.where("shopify_client_id") == "systemd-credential"
    assert linux_store.read("gmail_token") == "in-the-file"


def test_writing_a_systemd_provisioned_key_refuses_rather_than_shadowing(store, creds):
    (creds / "shopify_client_id").write_text("from-systemd", encoding="utf-8")
    with pytest.raises(linux_store.SecretShadowed) as caught:
        linux_store.write("shopify_client_id", "attempted-override")
    # The refusal names the key and what to do about it, so the operator is not left guessing.
    assert "shopify_client_id" in str(caught.value)
    assert "provision_secrets.py" in str(caught.value)
    assert linux_store.read("shopify_client_id") == "from-systemd"


def test_deleting_a_systemd_provisioned_key_refuses_too(store, creds):
    (creds / "shopify_client_id").write_text("from-systemd", encoding="utf-8")
    with pytest.raises(linux_store.SecretShadowed):
        linux_store.remove("shopify_client_id")
    assert linux_store.read("shopify_client_id") == "from-systemd"


def test_a_credentials_directory_that_is_not_there_is_simply_ignored(store, monkeypatch, tmp_path):
    monkeypatch.setenv(linux_store.CREDENTIALS_ENV, str(tmp_path / "nowhere"))
    linux_store.write("gmail_token", "value")
    assert linux_store.read("gmail_token") == "value"


# --------------------------------------------------------------- the dispatch in front


def test_keychain_uses_the_linux_store_when_dispatching_there(store, on_linux):
    keychain.set_secret("elevenlabs_api_key", "sk-value")
    assert keychain.get("elevenlabs_api_key") == "sk-value"
    assert keychain.present("elevenlabs_api_key") is True
    assert keychain.where("elevenlabs_api_key") == "file"
    keychain.delete("elevenlabs_api_key")
    assert keychain.get_optional("elevenlabs_api_key") is None


def test_get_and_set_and_delete_are_all_available_on_linux(store, on_linux):
    """The contract does not go half-missing: a backend where get() works and set() does not
    would make the Mac and this machine different products."""
    for key in keychain.KNOWN_KEYS:
        keychain.set_secret(key, f"value-for-{key}")
        assert keychain.get(key) == f"value-for-{key}"
        keychain.delete(key)
        assert keychain.get_optional(key) is None


def test_a_missing_secret_still_raises_secret_missing(store, on_linux):
    with pytest.raises(keychain.SecretMissing):
        keychain.get("shopify_client_id")


def test_an_unreadable_store_is_reported_as_unavailable_not_missing(store, on_linux, monkeypatch):
    store.mkdir(parents=True)
    monkeypatch.setattr(keychain.os, "access", lambda *a, **k: False)
    with pytest.raises(keychain.KeychainUnavailable):
        keychain.get("shopify_client_id")


def test_an_empty_value_is_still_refused_on_linux(store, on_linux):
    with pytest.raises(ValueError):
        keychain.set_secret("elevenlabs_api_key", "   ")


def test_an_unknown_key_is_still_refused_on_linux(store, on_linux):
    with pytest.raises(ValueError):
        keychain.get("not_a_real_secret")


def test_the_shadow_refusal_reaches_the_caller_through_keychain(store, creds, on_linux):
    (creds / "elevenlabs_api_key").write_text("from-systemd", encoding="utf-8")
    with pytest.raises(keychain.SecretShadowed):
        keychain.set_secret("elevenlabs_api_key", "override")


# --------------------------------------------------------------- the media signing key


def test_the_media_signing_key_is_a_known_key():
    """It is read and written by app/media.py. Left off this list, every lookup raised
    ValueError, every store was swallowed, and the key was regenerated per boot — which
    invalidated the tablet's thumbnail cache on every restart, on both platforms."""
    assert "media_signing_key" in keychain.KNOWN_KEYS


def test_the_media_signing_key_survives_a_restart(store, on_linux):
    """Two processes' worth of app.media, proved by calling the loader twice."""
    import app.media as media

    first = media._load_key()
    second = media._load_key()
    assert first == second
    assert len(first) >= 32
    assert keychain.where("media_signing_key") == "file"
