"""The app tier (app/secrets/vault.py): keys the owner stores from the Connections screen,
encrypted on this machine, asked before the systemd credentials and the plain 0600 files.

Nothing here runs systemd-creds, touches a Keychain or reaches the network: the cipher is a
stand-in that is reversible and visibly not the plain text, and every tier lives in a temporary
directory. `vault.bind(cipher)` also makes the file tier run on a Mac, so the suite means the
same on either platform.
"""

from __future__ import annotations

import stat
import subprocess

import pytest

from app.secrets import linux_store, vault
from scripts import provision_secrets as ps
from tests.fake_credentials import bearer_token, elevenlabs_key, github_fine_grained_token

NEW = elevenlabs_key("vault-new")
OLD = elevenlabs_key("vault-old")
STATIC = elevenlabs_key("vault-static")


class FakeCipher:
    """Reversible, bound to the key's name, and never the plain text on the disk."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def why_not(self) -> str:
        return ""

    @staticmethod
    def _prefix(key: str) -> bytes:
        return b"FAKE1:" + key.encode() + b":"

    def encrypt(self, key: str, plain: bytes) -> bytes:
        self.calls.append(("encrypt", key))
        return self._prefix(key) + bytes(b ^ 0x5A for b in plain)

    def decrypt(self, key: str, blob: bytes) -> bytes:
        self.calls.append(("decrypt", key))
        if not blob.startswith(self._prefix(key)):
            raise vault.VaultUnavailable("Embedded credential name does not match")
        return bytes(b ^ 0x5A for b in blob[len(self._prefix(key)):])


class BrokenCipher(FakeCipher):
    def __init__(self, *, encrypt_fails: bool = False, garbles: bool = False) -> None:
        super().__init__()
        self.encrypt_fails = encrypt_fails
        self.garbles = garbles

    def encrypt(self, key: str, plain: bytes) -> bytes:
        if self.encrypt_fails:
            raise vault.VaultUnavailable("systemd-creds encrypt failed: No TPM2 device")
        return super().encrypt(key, plain)

    def decrypt(self, key: str, blob: bytes) -> bytes:
        if self.garbles:
            return b"not what was stored"
        return super().decrypt(key, blob)


@pytest.fixture
def tiers(tmp_path, monkeypatch):
    """The writable tier and the app tier in a temporary directory, a systemd credentials
    directory beside them, and the stand-in cipher. Put back afterwards."""
    store = tmp_path / "secrets"
    creds = tmp_path / "creds"
    creds.mkdir()
    monkeypatch.setenv(linux_store.STORE_DIR_ENV, str(store))
    monkeypatch.setenv(linux_store.CREDENTIALS_ENV, str(creds))
    cipher = FakeCipher()
    vault.bind(cipher)
    yield {"store": store, "creds": creds, "app": store / vault.DIR_NAME, "cipher": cipher}
    vault.bind()


# ----------------------------------------------------------------- stored, and read back

def test_a_key_stored_from_the_app_is_encrypted_0600_and_read_back_at_once(tiers):
    vault.store("elevenlabs_api_key", "  " + NEW + "\n")
    blob = tiers["app"] / "elevenlabs_api_key.cred"
    assert blob.is_file()
    assert stat.S_IMODE(blob.stat().st_mode) == 0o600
    assert stat.S_IMODE(tiers["app"].stat().st_mode) == 0o700
    assert NEW.encode() not in blob.read_bytes()            # never the plain text on the disk
    assert linux_store.read("elevenlabs_api_key") == NEW    # no restart: the next read has it
    assert linux_store.where("elevenlabs_api_key") == "app"
    leftovers = [p.name for p in tiers["app"].iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_the_app_tier_wins_over_systemd_and_the_plain_file_until_it_is_cleared(tiers):
    (tiers["creds"] / "elevenlabs_api_key").write_text(STATIC)
    tiers["store"].mkdir(parents=True, exist_ok=True)
    (tiers["store"] / "elevenlabs_api_key").write_text(OLD)
    vault.store("elevenlabs_api_key", NEW)
    assert linux_store.read("elevenlabs_api_key") == NEW
    vault.clear("elevenlabs_api_key")
    assert linux_store.read("elevenlabs_api_key") == STATIC
    assert linux_store.where("elevenlabs_api_key") == "systemd-credential"


def test_a_key_disconnected_in_the_app_reads_as_absent_whatever_the_server_still_holds(tiers):
    (tiers["creds"] / "elevenlabs_api_key").write_text(STATIC)
    vault.store("elevenlabs_api_key", NEW)
    vault.disconnect("elevenlabs_api_key")
    assert not (tiers["app"] / "elevenlabs_api_key.cred").exists()
    assert linux_store.read("elevenlabs_api_key") is None
    assert linux_store.where("elevenlabs_api_key") == "app-off"
    vault.store("elevenlabs_api_key", NEW)                   # connecting again lifts the mark
    assert linux_store.read("elevenlabs_api_key") == NEW
    assert not (tiers["app"] / "elevenlabs_api_key.off").exists()


def test_a_renewal_lands_in_the_app_tier_when_the_key_lives_there(tiers):
    first, renewed = bearer_token("ig-first"), bearer_token("ig-renewed")
    vault.store("instagram_access_token", first)
    linux_store.write("instagram_access_token", renewed)    # what the client's refresh does
    assert linux_store.read("instagram_access_token") == renewed
    assert not (tiers["store"] / "instagram_access_token").exists()   # never the plain file


def test_a_renewal_of_a_key_disconnected_in_the_app_is_refused_not_quietly_reconnected(tiers):
    vault.disconnect("instagram_access_token")
    with pytest.raises(linux_store.SecretDisconnected) as raised:
        linux_store.write("instagram_access_token", bearer_token("ig-sneaky"))
    assert isinstance(raised.value, linux_store.SecretShadowed)     # the clients already catch this
    assert linux_store.read("instagram_access_token") is None


def test_with_nothing_in_the_app_tier_the_old_tiers_behave_exactly_as_before(tiers):
    linux_store.write("gmail_token", "in-the-file")
    assert (tiers["store"] / "gmail_token").read_text() == "in-the-file"
    (tiers["creds"] / "shopify_client_id").write_text("from-systemd")
    with pytest.raises(linux_store.SecretShadowed):
        linux_store.write("shopify_client_id", "attempted-override")
    assert not tiers["app"].exists()


def test_a_reader_that_may_not_look_into_the_directory_finds_nothing_here_rather_than_failing(tiers, monkeypatch):
    real = vault.Path.exists

    def refused(self, *args, **kwargs):
        if vault.DIR_NAME in self.parts:
            raise PermissionError(13, "Permission denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(vault.Path, "exists", refused)
    assert vault.entry("gmail_token").kind == "none"
    linux_store.write("gmail_token", "in-the-file")
    assert linux_store.read("gmail_token") == "in-the-file"


def test_remove_takes_the_app_tiers_say_away_too(tiers):
    vault.disconnect("gmail_token")
    linux_store.remove("gmail_token")
    assert linux_store.where("gmail_token") == ""


# ----------------------------------------------------------------- what cannot be read

def test_a_value_this_machine_cannot_decrypt_is_absent_never_the_older_key_beneath_it(tiers):
    (tiers["creds"] / "elevenlabs_api_key").write_text(STATIC)
    vault.store("elevenlabs_api_key", NEW)
    (tiers["app"] / "elevenlabs_api_key.cred").write_bytes(b"FAKE1:another_key:xyz")
    assert linux_store.read("elevenlabs_api_key") is None
    assert linux_store.where("elevenlabs_api_key") == "app-unreadable"
    held = vault.entry("elevenlabs_api_key")
    assert held.kind == "unreadable" and "does not match" in held.why


def test_a_file_is_decrypted_once_until_it_changes(tiers):
    vault.store("youtube_api_key", NEW)
    cipher = tiers["cipher"]
    cipher.calls.clear()
    for _ in range(5):
        assert linux_store.read("youtube_api_key") == NEW
    assert ("decrypt", "youtube_api_key") not in cipher.calls      # remembered since the store
    (tiers["app"] / "youtube_api_key.cred").write_bytes(cipher.encrypt("youtube_api_key", OLD.encode()))
    assert linux_store.read("youtube_api_key") == OLD                # another process changed it
    (tiers["app"] / "youtube_api_key.cred").write_bytes(b"garbage")
    cipher.calls.clear()
    for _ in range(3):
        assert linux_store.read("youtube_api_key") is None
    assert cipher.calls.count(("decrypt", "youtube_api_key")) == 1   # nor re-run for a bad one


# ----------------------------------------------------------------- what is refused

@pytest.mark.parametrize("value, says", [
    ("", "nothing was entered"),
    ("   ", "nothing was entered"),
    ("\x1b[A" + NEW, "control character"),
    (NEW + "\x00", "control character"),
    ("x" * (vault.MAX_VALUE + 1), "longer than"),
])
def test_a_value_no_key_could_be_is_refused_and_never_quoted(tiers, value, says):
    with pytest.raises(ValueError) as raised:
        vault.store("elevenlabs_api_key", value)
    assert says in str(raised.value)
    assert NEW not in str(raised.value)
    assert not (tiers["app"] / "elevenlabs_api_key.cred").exists()


def test_an_unknown_key_is_refused():
    with pytest.raises(ValueError):
        vault.store("not_a_key_we_hold", "value")


def test_a_failed_encryption_writes_nothing_and_keeps_the_old_key(tiers):
    vault.store("elevenlabs_api_key", OLD)
    vault.bind(BrokenCipher(encrypt_fails=True))
    with pytest.raises(vault.VaultUnavailable):
        vault.store("elevenlabs_api_key", NEW)
    vault.bind(tiers["cipher"])
    assert linux_store.read("elevenlabs_api_key") == OLD


def test_a_blob_that_does_not_decrypt_back_is_never_written(tiers):
    vault.store("elevenlabs_api_key", OLD)
    vault.bind(BrokenCipher(garbles=True))
    with pytest.raises(vault.VaultUnavailable) as raised:
        vault.store("elevenlabs_api_key", NEW)
    assert "did not decrypt back" in str(raised.value)
    vault.bind(tiers["cipher"])
    assert linux_store.read("elevenlabs_api_key") == OLD


# ----------------------------------------------------------------- the real cipher's shape

def test_systemd_creds_gets_the_value_on_stdin_never_in_its_arguments():
    seen: list[dict] = []

    def runner(argv, **kwargs):
        seen.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, 0, stdout=b"ciphertext", stderr=b"")

    cipher = vault.SystemdCreds(binary="/usr/bin/systemd-creds", runner=runner)
    assert cipher.encrypt("elevenlabs_api_key", NEW.encode()) == b"ciphertext"
    call = seen[0]
    assert call["argv"] == ["/usr/bin/systemd-creds", "encrypt", "--name=elevenlabs_api_key", "-", "-"]
    assert call["input"] == NEW.encode()
    assert all(NEW not in part for part in call["argv"])
    assert call["timeout"] == vault.TIMEOUT_S and call["check"] is False


def test_a_systemd_creds_failure_names_its_reason_and_never_the_value():
    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"warning\nFailed to decrypt: Bad message\n")

    cipher = vault.SystemdCreds(binary="/usr/bin/systemd-creds", runner=runner)
    with pytest.raises(vault.VaultUnavailable) as raised:
        cipher.decrypt("elevenlabs_api_key", NEW.encode())
    assert str(raised.value) == "systemd-creds decrypt failed: Failed to decrypt: Bad message"


def test_without_systemd_creds_the_app_tier_says_so(monkeypatch):
    monkeypatch.setattr(vault.shutil, "which", lambda name: None)
    cipher = vault.SystemdCreds()
    assert cipher.why_not() == "systemd-creds is not installed on this server"
    with pytest.raises(vault.VaultUnavailable):
        cipher.encrypt("elevenlabs_api_key", b"x")


def test_check_proves_the_machine_can_keep_a_key_with_a_probe_and_never_a_real_key(tiers):
    assert vault.check() == (True, "")
    assert ("encrypt", vault.PROBE_KEY) in tiers["cipher"].calls
    vault.bind(BrokenCipher(encrypt_fails=True))
    ok, why = vault.check()
    assert not ok and "No TPM2 device" in why


# ----------------------------------------------------------------- the server prompt

def test_storing_or_removing_at_the_server_prompt_clears_the_app_tier_first(tiers, monkeypatch):
    token = github_fine_grained_token("vault-prompt")
    monkeypatch.setattr(ps, "CRED_DIR", tiers["store"] / "no-encrypted-blobs")   # never the host's
    vault.disconnect("gmail_token")
    stored: list[tuple[str, str]] = []
    monkeypatch.setattr(ps, "where", lambda key: "")
    monkeypatch.setattr(ps.keychain, "set_secret", lambda key, value: stored.append((key, value)))
    monkeypatch.setattr(ps.getpass, "getpass", lambda prompt: token)
    assert ps.store_one("gmail_token", plain=True) == 0
    assert stored == [("gmail_token", token)]
    assert vault.entry("gmail_token").kind == "none"

    vault.store("youtube_api_key", NEW)
    monkeypatch.setattr(ps.keychain, "delete", lambda key: None)
    assert ps.remove_one("youtube_api_key") == 0
    assert vault.entry("youtube_api_key").kind == "none"


def test_the_server_prompt_says_where_an_app_stored_key_is_and_whether_it_is_usable(tiers, monkeypatch):
    monkeypatch.setattr(ps.keychain, "where", linux_store.where)
    monkeypatch.setattr(ps, "CRED_DIR", tiers["store"] / "no-encrypted-blobs")
    vault.store("youtube_api_key", NEW)
    assert ps.where("youtube_api_key").startswith("stored from the app")
    assert ps.usable("youtube_api_key")
    vault.disconnect("youtube_api_key")
    assert ps.where("youtube_api_key") == "disconnected in the app (Connections)"
    assert not ps.usable("youtube_api_key")
