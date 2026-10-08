"""The release service's switches and paths, read from its own environment file.

Why it exists: the service must do nothing until George switches it on AND says who holds deploy
authority. Both are settings here, both default to off, and nothing else turns them on. The unit
(deploy/release/clive-release.service) reads /etc/crooks-os/release.env; CLIVE's own .env is never
read, so no switch of CLIVE's moves a switch of this, or the other way round.

    CLIVE_RELEASE_ENABLED   off  the service does nothing at all
    CLIVE_RELEASE_RULE      off  "exact_sha_review" or "owner_waiver"; anything else deploys nothing
    CLIVE_RELEASE_DRY_RUN   on   every tick works out the plan, says it, and changes nothing; only an
                                 explicit CLIVE_RELEASE_DRY_RUN=false deploys, so a release.env that
                                 lost the line stays a dry run (unknown is RED)

The paths are settings so a test can move them; on the server they stay as written here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

TRUNK = "clive/trunk"                      # the only branch anything is deployed from (DEC-058)
EXACT_SHA_REVIEW = "exact_sha_review"
OWNER_WAIVER = "owner_waiver"
RULES = (EXACT_SHA_REVIEW, OWNER_WAIVER)


class ReleaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLIVE_RELEASE_", env_file=None, extra="ignore")

    enabled: bool = False
    dry_run: bool = True
    rule: str = "off"

    repository: str = "crooksldn-pixel/clive"
    checkout: Path = Path("/opt/crooks-os")
    state_dir: Path = Path("/var/lib/clive-release")
    unit_path: Path = Path("/etc/systemd/system/crooks-assistant.service")
    # George's waivers given on the host (python -m app.release waive): a root-only folder.
    waivers_dir: Path = Path("/etc/crooks-os/release/waivers")
    # George's waivers given with his passkey: CLIVE writes them beside his other judgments
    # (app/builds/decisions.py); each carries its own signature, so where it lies is not trusted.
    passkey_waivers_dir: Path = Path("/var/lib/crooks-assistant/objectives/release-waivers")
    # The owner's registered passkeys (app/connections/passkeys.py), read only, for their public keys.
    passkeys_file: Path = Path("/etc/crooks-os/secrets/app/passkeys.json")
    # The GitHub token, as systemd hands it to the unit (LoadCredentialEncrypted=); never in a file
    # of ours, an argument, a log line or a record.
    token_name: str = "clive_release_github_token"
    # How long the restarted service is left before it is judged.
    settle_s: float = 20.0

    @property
    def assistant(self) -> Path:
        return self.checkout / "crooks-assistant"

    def rule_named(self) -> str | None:
        """The rule George picked, or None when he has not (or named something that is not one)."""
        value = (self.rule or "").strip().lower()
        return value if value in RULES else None


def load(env_file: Path | None = None) -> ReleaseSettings:
    """The settings from the process environment, or from `env_file` (python -m app.release --env)."""
    if env_file is not None:
        return ReleaseSettings(_env_file=str(env_file))
    return ReleaseSettings()
