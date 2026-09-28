from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from finanzen.bank.enablebanking import EnableBankingProvider
from finanzen.bank.fake import FakeEnableBanking
from finanzen.bank.fake_scenario import build_scenario

APP_ID = "00000000-test-app"
TODAY = date(2026, 9, 28)


class Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture(scope="session")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
    return private_pem, public_pem


@pytest.fixture
def clock():
    return Clock(datetime(TODAY.year, TODAY.month, TODAY.day, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def fake(keypair, clock):
    return FakeEnableBanking(APP_ID, keypair[1], now=clock)


@pytest.fixture
def scenario(fake):
    return build_scenario(fake, TODAY)


@pytest.fixture
def provider(keypair, fake, clock):
    return EnableBankingProvider(APP_ID, keypair[0], transport=fake,
                                 clock=lambda: clock().timestamp())
