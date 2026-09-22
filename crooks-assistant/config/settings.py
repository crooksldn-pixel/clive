"""Non-secret configuration. Secrets are never read from here — see secrets/keychain.py."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env_file() -> str | None:
    """Which file the settings read, normally `.env` beside this repository.

    CROOKS_ENV_FILE names a different one, and set to nothing it names none: the offline test
    suite runs that way, because `.env` is the owner's own configuration — his allow-list, his
    voice, whether changes are on — and pydantic-settings reads it in every process that
    imports this module, pytest included. A test whose result depends on which Mac it runs on
    is not a test. Nothing else sets it, so the assistant itself reads `.env` exactly as before.
    """
    return os.environ.get("CROOKS_ENV_FILE", ".env") or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CROOKS_", env_file=_env_file(), env_file_encoding="utf-8", extra="ignore"
    )

    # --- transport ---
    host: str = "127.0.0.1"
    port: int = 8000
    # Who may ask, as Tailscale logins ("you@example.com, partner@example.com"). Empty means
    # anyone on the tailnet — it is the owner's own private network. Set it and every request
    # proxied by `tailscale serve` from another login is refused; requests made on the Mac
    # itself carry no login and are always allowed.
    allowed_logins: str = ""

    # --- Shopify ---
    # The myshopify domain, not the storefront domain. Verified against the live store.
    shopify_shop_domain: str = "5wn03t-nm.myshopify.com"
    shopify_api_version: str = "2025-07"
    # "client_credentials" (Dev Dashboard app) or "static_token" (legacy shpat_ fallback, M6).
    shopify_auth_mode: str = "client_credentials"

    # --- speech ---
    # Which recogniser runs first: "scribe" (ElevenLabs, the default) or "whisper" (local only).
    # Whisper is the automatic fallback either way and is never switched off by this setting.
    stt_primary: str = "scribe"
    scribe_model: str = "scribe_v2"
    scribe_language: str = "eng"  # ISO-639-3, as the ElevenLabs API expects
    scribe_timeout_s: float = 10.0   # Scribe answers in one to two seconds; past this, whisper takes the turn
    # Bias Scribe with the live/seed product catalogue. Product words only — never customers.
    scribe_keyterms: bool = True
    # ElevenLabs bills a 20-second minimum for requests carrying 100 or more keyterms.
    scribe_max_keyterms: int = 99
    # After a rejected key or an exhausted account, stop calling Scribe for this long and go
    # straight to Whisper, so a broken account does not add a round trip to every sentence.
    scribe_cooldown_s: float = 300.0
    elevenlabs_base_url: str = "https://api.elevenlabs.io/v1"

    # --- the assistant's voice (ElevenLabs text-to-speech) ---
    # Off falls the tablet back to Android's own speechSynthesis, which is what it used before.
    tts_enabled: bool = True
    # Derek, from the ElevenLabs library — used by id, without being added to the account.
    # This is the assistant's approved voice; `.env` overrides it and `make voice` hears a
    # change here. The id is what ElevenLabs synthesises from and the name is only what this
    # code calls it, so /health asks ElevenLabs whose voice the id really is and fails the
    # check when the two disagree: an id changed without its name is caught there, not by ear.
    tts_voice_id: str = "Q0Et7LOU7VpeoeCRQAVS"
    tts_voice_name: str = "Derek"
    tts_model: str = "eleven_flash_v2_5"  # the low-latency model; this is a conversation
    # ~16 kB/s. The 32 kbps stream this replaced was audibly compressed on the tablet
    # speaker, and four times the bytes is nothing next to the generation time.
    tts_output_format: str = "mp3_44100_128"
    # ElevenLabs answers the first byte of an MP3 within a second or two; a voice that has
    # not started by now is a voice that is not coming, and Android's should take over.
    tts_timeout_s: float = 10.0
    # Start synthesising an answer the moment /turn knows it, so it is generating while the
    # tablet asks for it. Off means /speak synthesises on request, as it did before.
    tts_prefetch: bool = True
    # Longer than one answer can be (max_answer_chars is 700) with room for the spoken forms,
    # which are longer than the digits they replace.
    tts_max_chars: int = 1200
    tts_cooldown_s: float = 300.0

    # Whether local speech recognition is deployed on this host at all. True everywhere the
    # Mac runs: whisper.cpp is its automatic fallback and nothing about that changes. False on
    # the Linux server, which has no Core ML, no model and no build toolchain, and where a
    # permanently red whisper check would be a check nobody reads.
    #
    # False does four things and no more: /health reports whisper as DISABLED rather than
    # FAILED, the Core ML probe is skipped, the absence does not make the host degraded, and
    # the transcriber stops offering a fallback it does not have. It never hides a real
    # failure — with no fallback behind it, Scribe going down makes speech UNHEALTHY here,
    # where on the Mac the same outage is only slower.
    whisper_enabled: bool = True
    whisper_url: str = "http://127.0.0.1:8910"
    whisper_model: str = "small.en"
    whisper_bin_dir: Path = Path.home() / "tools" / "whisper.cpp"
    # How much audio to keep either side of detected speech. whisper.cpp's default is 30 ms,
    # which shaves the soft start of a first word; 200 ms keeps it.
    whisper_vad_pad_ms: int = 200

    # --- Claude ---
    claude_model: str = "sonnet"
    claude_cli_path: str = ""  # absolute path; resolved at startup if blank

    # --- writes ---
    # The assistant proposes changes; the owner applies them on the tablet. Off (the default)
    # hides every write tool from the assistant and refuses every commit, so the system is the
    # read-only one it always was. On is not enough by itself: a commit also needs
    # CROOKS_ALLOWED_LOGINS to name who may tap, the caller to be one of them, and the store
    # to have granted the scope the action needs. Each is checked on every commit.
    writes_enabled: bool = False
    # A request made on the Mac itself carries no Tailscale login. It may commit only when
    # this is on — for the owner at the keyboard, deliberately, never by default.
    writes_local_owner: bool = False
    # Before a change is applied, the login `tailscale serve` stamped is confirmed against
    # `tailscale whois` for the forwarded address: a header is a claim, and anything on the
    # Mac can write one. Off only on a machine without the CLI, knowingly.
    tailscale_verify: bool = True
    tailscale_cli: str = ""
    # What a cancellation does, beyond cancelling: policy, not a model argument, and printed
    # on the card the owner holds. A customer who asked to cancel expects the email; a
    # cancellation for fraud or a declined payment sends none whatever this says.
    cancel_refund: bool = True
    cancel_restock: bool = True
    cancel_notify: bool = True
    # Whether a refund emails the customer. Policy, printed on the card.
    refund_notify: bool = True
    # Marking an order shipped: the carrier Shopify is told (exactly as Shopify names it, so
    # the tracking number becomes a link) and whether the shipping email goes out. Off by
    # default: Click & Drop or Admin may already send one; printed on the card either way.
    carrier: str = "Royal Mail"
    fulfil_notify: bool = False
    # Email the assistant prepares. What it may do is read from the Gmail credential itself
    # (modify: read and label; compose: draft and send) and shown per change on /health; these
    # are how the emails read. The sign-off goes on every draft and every send; links are
    # allowed only to these hosts, so a made-up URL never reaches a customer.
    gmail_from_name: str = "CROOKS"
    gmail_signature: str = "CROOKS"
    gmail_link_hosts: str = "crooksldn.com,royalmail.com,parcelforce.com,evri.com,dpd.co.uk,yodel.co.uk"

    # --- the read layer ---
    # How many days of orders the Mac reads into memory at boot, so the first question about
    # sales or stock is answered from memory. 0 leaves the cache cold until asked.
    analytics_warm_days: int = 90
    # Where the shop ships FROM, as a two-letter country code. It is the other half of the
    # "international" filter — an order is international when its shipping country is not this
    # one. Read from the shop itself when the shop reports one; this is the override, and the
    # default is the country CROOKS is in.
    shop_country_code: str = "GB"

    # --- behaviour ---
    tool_timeout_s: float = 8.0
    session_idle_timeout_s: int = 1800
    max_answer_chars: int = 700

    # --- paths ---
    kb_dir: Path = REPO_ROOT / "kb"
    # The shop's clock: every question carries the date and time in this zone.
    shop_timezone: str = "Europe/London"
    bench_audio_dir: Path = REPO_ROOT / "bench" / "audio"
    bench_results_dir: Path = REPO_ROOT / "bench" / "results"
    log_dir: Path = REPO_ROOT / "logs"
    # Product thumbnails fetched for the tablet, kept so the same image is not fetched for
    # every look at the same order. Bounded; never a customer's data.
    media_cache_dir: Path = REPO_ROOT / ".cache" / "media"

    # --- the production experience recorder (app/observability/recorder.py) ---
    # An hour of real use, written down. Off, and normal production is normal production:
    # nothing about a turn changes when this is on except that its events are also minimised
    # and appended to a file in logs/experience-recordings/. It is not fixture mode and it is
    # not a test session; it can never authorise a change.
    record_experience: bool = False
    # The second opt-in. Off, a recording holds the SHAPE of what was said — how many
    # characters, how many words, which order numbers, which catalogue words matched — and the
    # normalised intent, which is what makes an interaction understandable. On, it holds the
    # sentence too, still scrubbed of addresses, postcodes, telephone numbers and long digit
    # runs. For an afternoon spent diagnosing a mis-hearing, deliberately, never by default.
    record_transcripts: bool = False

    # --- dev toggles ---
    # Every recording is a recording of the office. Kept on disk only when asked for
    # (CROOKS_SAVE_CAPTURES=true), for diagnosing a mis-hearing; never by default.
    save_captures: bool = False
    # Keep only this many tablet recordings on disk. They are recordings of an office.
    max_saved_captures: int = 200


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Re-read the env file name each time rather than trusting the one baked into model_config
    # at import: the test suite clears this cache after fixing its environment.
    return Settings(_env_file=_env_file())
