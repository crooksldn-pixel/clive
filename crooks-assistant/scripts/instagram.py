"""Instagram on this server: prove the stored token works, renew it, or exchange a new one.

    python scripts/instagram.py check      what the token can read, in counts only
    python scripts/instagram.py refresh    renew the stored long-lived token now (60 more days)
    python scripts/instagram.py exchange   swap a short-lived token (asked for, hidden) for a
                                           long-lived one and store it; needs instagram_app_secret

Store the token first with `python scripts/provision_secrets.py instagram_access_token`.

`check` prints the connected account's own handle and how many conversations, posts and
comments it could read; never a customer's handle or anything anybody wrote. Nothing here sends,
replies to or changes anything on Instagram.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.clients import instagram  # noqa: E402
from config.settings import get_settings  # noqa: E402


def _configure() -> None:
    settings = get_settings()
    instagram.configure(api_version=settings.instagram_api_version,
                        state_path=settings.objectives_dir / "instagram.json")


def _line(label: str, ok: bool, detail: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label:<14} {detail}")


async def check() -> int:
    if not instagram.token():
        print("No Instagram token is stored. Run: python scripts/provision_secrets.py instagram_access_token")
        return 1
    failures = 0
    try:
        account = await instagram.account()
        _line("account", True, f"@{account['username']} ({account['account_type'] or 'type not given'})")
    except instagram.InstagramUnavailable as exc:
        _line("account", False, f"{exc} [{exc.kind}]")
        return 1
    try:
        found = await instagram.conversations(limit=5)
        _line("messages", True, f"{len(found)} recent conversation(s) readable")
    except instagram.InstagramUnavailable as exc:
        failures += 1
        _line("messages", False, f"{exc} [{exc.kind}]")
    try:
        posts = await instagram.media(limit=5)
        _line("posts", True, f"{len(posts)} recent post(s) readable")
        with_comments = [p for p in posts if p.get("comments_count")]
        if with_comments:
            comments = await instagram.comments(with_comments[0]["media_id"], limit=5)
            _line("comments", True, f"{len(comments)} comment(s) readable on the latest post that has any")
        else:
            _line("comments", True, "no recent post has comments to read")
    except instagram.InstagramUnavailable as exc:
        failures += 1
        _line("posts/comments", False, f"{exc} [{exc.kind}]")
    state = instagram.state()
    expires = state.get("expires_at")
    if expires:
        _line("token", True, f"good for {int((float(expires) - time.time()) // 86400)} more day(s)")
    else:
        _line("token", True, "expiry not known yet: CLIVE renews it a day after first use, then weekly")
    print(f"  auth: token sent {'in the Authorization header' if instagram.auth_mode() == 'header' else 'as a parameter'}")
    return 1 if failures else 0


async def refresh() -> int:
    try:
        lasts = await instagram.refresh()
    except instagram.InstagramUnavailable as exc:
        print(f"Not renewed: {exc} [{exc.kind}]")
        return 1
    print(f"Renewed: good for {lasts // 86400} days.")
    return 0


async def exchange() -> int:
    print("Paste the short-lived token (hidden as you type or paste it).")
    short = getpass.getpass("token: ").strip()
    try:
        lasts = await instagram.exchange(short)
    except instagram.InstagramUnavailable as exc:
        print(f"Not exchanged: {exc} [{exc.kind}]")
        return 1
    print(f"Stored a long-lived token, good for {lasts // 86400} days.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("check", "refresh", "exchange"))
    args = parser.parse_args(argv)
    _configure()
    return asyncio.run({"check": check, "refresh": refresh, "exchange": exchange}[args.command]())


if __name__ == "__main__":
    raise SystemExit(main())
