from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ["RETURNS_ENV_FILE"] = ""

from returns.fake import FakeLabels, FakeShopify, sample_orders  # noqa: E402
from returns.service import Notifier, ReturnsService  # noqa: E402
from returns.settings import Settings  # noqa: E402
from returns.store import Store  # noqa: E402

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class RecordingNotifier(Notifier):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.sent: list[tuple[str, str]] = []

    def send(self, event, ret) -> None:
        self.sent.append((event, ret.id))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        db_path=str(tmp_path / "t.sqlite3"),
        session_secret="test-secret",
        shopify_client_secret="shpss_test",
        dev_skip_proxy_signature=True,
        return_label_cost_pence=350,
        clive_read_keys="read-key",
        clive_write_keys="write-key",
        public_base_url="https://returns.example.com",
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def shop() -> FakeShopify:
    return FakeShopify(sample_orders(NOW))


@pytest.fixture
def labels() -> FakeLabels:
    return FakeLabels()


@pytest.fixture
def svc(settings, shop, labels, clock) -> ReturnsService:
    return ReturnsService(
        settings, Store(settings.db_path), shop, labels, RecordingNotifier(settings), clock=clock
    )
